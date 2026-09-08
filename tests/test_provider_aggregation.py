"""Provider ordering, absence and Trust Kernel compatibility boundaries."""

from dataclasses import replace

import pytest

from preflightops.provider_aggregation import aggregate_provider_evidence
from preflightops.provider_contract import ProviderContractError, ProviderEvidence


def item(provider="fake", **kw):
    return ProviderEvidence(
        **{
            "provider": provider,
            "provider_version": "1",
            "control_id": "monitoring",
            "status": "PASS",
            "summary": "Reviewed evidence.",
            "source_reference": "ref-1",
            "collected_at": "2026-09-08T12:00:00Z",
            "valid_until": "2026-09-08T13:00:00Z",
            "confidence": 90,
            **kw,
        }
    )


def aggregate(items, **kw):
    return aggregate_provider_evidence(
        items,
        **{
            "expected": [("fake", "1", "monitoring"), ("other", "1", "monitoring")],
            "evaluated_at": "2026-09-08T12:30:00Z",
            **kw,
        },
    )


def test_order_independent_and_no_control_id_collision():
    a, b = item(), item("other", confidence=60)
    first, second = aggregate([a, b]), aggregate([b, a])
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.digest == second.digest
    assert first.confidence_cap == 60
    controls = first.controls()
    assert len({c.control_id for c in controls}) == 2
    assert all(c.status == "PASS" and c.risk_points == 0 for c in controls)


def test_missing_provider_is_visible_and_confidence_is_zero():
    result = aggregate([item()])
    assert result.evidence[1].status == "UNKNOWN"
    assert result.evidence[1].error_code == "MISSING"
    assert result.confidence_cap == 0
    assert result.controls()[1].status == "UNKNOWN"


@pytest.mark.parametrize("status", ["ERROR", "UNKNOWN"])
def test_partial_uncertainty_survives_kernel_projection(status):
    result = aggregate(
        [item(), item("other", status=status, confidence=0, error_code="UNAVAILABLE")]
    )
    assert result.controls()[1].status == status
    assert result.confidence_cap == 0


def test_stale_pass_is_unknown():
    result = aggregate([item(), item("other")], evaluated_at="2026-09-08T13:00:00Z")
    assert all(c.status == "UNKNOWN" for c in result.controls())
    assert result.confidence_cap == 0


def test_not_applicable_never_becomes_pass_in_legacy_kernel():
    na = item(status="NOT_APPLICABLE", confidence=0, not_applicable_reason="Approved exclusion.")
    result = aggregate([na])
    assert result.evidence[0].status == "NOT_APPLICABLE"
    assert result.controls()[0].status == "UNKNOWN"


@pytest.mark.parametrize("items", [[item(), item()], [item("unrequested")]])
def test_ambiguous_or_unexpected_identity_rejected(items):
    with pytest.raises(ProviderContractError):
        aggregate(items)


def test_digest_binds_confidence_and_evaluation_time():
    first = aggregate([item()])
    assert first.digest != aggregate([replace(item(), confidence=89)]).digest
    assert first.digest != aggregate([item()], evaluated_at="2026-09-08T12:31:00Z").digest


def test_expired_failure_preserves_failure_but_has_no_current_confidence():
    result = aggregate([item(status="FAIL"), item("other")], evaluated_at="2026-09-08T13:00:00Z")
    assert result.controls()[0].status == "FAIL"
    assert result.confidence_cap == 0

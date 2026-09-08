"""End-to-end normalized evidence consumption without a provider SDK."""

import copy

import pytest

from preflightops.assessment import AssessmentContext, validate_assessment_v1
from preflightops.provider_aggregation import aggregate_provider_evidence
from preflightops.provider_contract import ProviderEvidence
from preflightops.risk_engine import assess_risk, assess_risk_with_provider_evidence


@pytest.mark.parametrize("status", ["PASS", "FAIL", "ERROR", "UNKNOWN", "NOT_APPLICABLE"])
def test_provider_confidence_does_not_rewrite_legacy_risk(status):
    services = {"services": [{"name": "svc", "owner": "team", "criticality": "low"}]}
    change = {"change": {"service": "svc", "environment": "staging", "change_type": "deployment"}}
    original = copy.deepcopy((services, change))
    item = ProviderEvidence(
        "fake",
        "1",
        "monitoring",
        status,
        "Reviewed monitoring evidence.",
        "ref-1",
        "2026-09-08T12:00:00Z",
        "2026-09-08T13:00:00Z",
        50 if status in {"PASS", "FAIL"} else 0,
        error_code="UNAVAILABLE" if status in {"ERROR", "UNKNOWN"} else None,
        not_applicable_reason="Reviewed exclusion." if status == "NOT_APPLICABLE" else None,
    )
    aggregate = aggregate_provider_evidence(
        [item], expected=[("fake", "1", "monitoring")], evaluated_at="2026-09-08T12:30:00Z"
    )
    kwargs = dict(
        provider_evidence=aggregate,
        change_id="change-1",
        input_digests={"change": "c" * 64},
        context=AssessmentContext(
            "reviewer", "human", "run-1", 1, "org/repo", None, "a" * 40, "preflight"
        ),
    )
    result = assess_risk_with_provider_evidence(services, change, **kwargs)
    validate_assessment_v1(result["assessment"])
    assert result["legacy"] == assess_risk(services, change)
    assert result == assess_risk_with_provider_evidence(services, change, **kwargs)
    assert (services, change) == original
    assert result["assessment"]["scores"]["risk"]["value"] == result["legacy"]["risk_score"]
    assert result["assessment"]["scores"]["confidence"]["value"] <= aggregate.confidence_cap
    assert result["legacy"]["decision_record"]["automatic_approval"] is False
    if status in {"UNKNOWN", "ERROR", "NOT_APPLICABLE"}:
        assert result["assessment"]["scores"]["confidence"]["value"] == 0

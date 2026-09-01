"""Assessment Contract v1 and deterministic Trust Kernel tests."""

import copy
import datetime as dt
import json
import socket
from pathlib import Path

import jsonschema
import pytest

from preflightops.assessment import (
    AssessmentContext,
    AssessmentContractError,
    ControlObservation,
    HumanDecision,
    InputDigest,
    PolicyIdentity,
    TrustKernel,
    WaiverReference,
    adapt_legacy_assessment,
    serialize_assessment_v1,
    validate_assessment_v1,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 8, 31, 12, 0, tzinfo=dt.UTC)
CONTEXT = AssessmentContext(
    actor_id="release-bot",
    actor_type="automation",
    run_id="4242",
    run_attempt=1,
    repository="acme/payments-api",
    pull_request="87",
    commit="a" * 40,
    pipeline_name="preflight",
    pipeline_url="https://github.example.test/acme/payments-api/actions/runs/4242",
)
POLICY = PolicyIdentity(name="production", version="2.1.0", sha256="b" * 64)
INPUTS = (
    InputDigest("change-request", "c" * 64),
    InputDigest("service-catalog", "d" * 64),
)


def _control(
    status="PASS",
    *,
    control_id="rollback-plan",
    collected_at=NOW,
    valid_until=NOW + dt.timedelta(hours=1),
    evidence_sha256="e" * 64,
):
    return ControlObservation(
        control_id=control_id,
        status=status,
        summary="Rollback plan is present and testable.",
        source="change-request-validator",
        collected_at=collected_at,
        valid_until=valid_until,
        risk_points=0,
        evidence_sha256=evidence_sha256,
        evidence_kind="control-result",
    )


def _assessment(**overrides):
    arguments = {
        "change_id": "CHG-2026-0042",
        "timestamp": NOW,
        "context": CONTEXT,
        "policy": POLICY,
        "inputs": INPUTS,
        "controls": (_control(),),
        "risk_score": 20,
        "risk_level": "LOW",
        "recommendation_summary": "Proceed to an authorized human review.",
        "evidence_links": ("https://evidence.example.test/runs/4242",),
    }
    arguments.update(overrides)
    return TrustKernel().evaluate(**arguments)


def test_contract_is_deterministic_strict_and_matches_schema():
    first = _assessment(inputs=tuple(reversed(INPUTS)))
    second = _assessment()
    assert first == second
    assert serialize_assessment_v1(first) == serialize_assessment_v1(second)
    assert serialize_assessment_v1(first).endswith(b"\n")
    validate_assessment_v1(first)
    schema = json.loads(
        (ROOT / "schemas" / "assessment-contract-v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(first, schema, format_checker=jsonschema.FormatChecker())
    assert first["assessment_id"].endswith(first["integrity"]["value"])


def test_golden_contract_bytes_are_stable():
    expected = (
        ROOT / "tests" / "fixtures" / "assessment" / "assessment-v1.golden.json"
    ).read_bytes()
    assert serialize_assessment_v1(_assessment()) == expected


@pytest.mark.parametrize("status", ["ERROR", "UNKNOWN"])
def test_error_and_unknown_never_become_pass(status):
    contract = _assessment(controls=(_control(status),))
    assert contract["controls"][0]["status"] == status
    assert contract["passed_controls"] == []
    assert contract["verdict"] == "INDETERMINATE"
    assert contract["recommendation"]["action"] == "DO_NOT_PROCEED"


@pytest.mark.parametrize(
    "control",
    [
        _control(evidence_sha256=None),
        _control(
            collected_at=NOW - dt.timedelta(hours=1),
            valid_until=NOW - dt.timedelta(seconds=1),
        ),
    ],
)
def test_pass_without_fresh_digest_pinned_evidence_is_downgraded(control):
    contract = _assessment(controls=(control,))
    assert contract["controls"][0]["status"] == "UNKNOWN"
    assert contract["passed_controls"] == []
    assert {warning["code"] for warning in contract["warnings"]} >= {
        "CONTROL_UNKNOWN",
        "PASS_DOWNGRADED",
    }


def test_risk_confidence_recommendation_and_human_decision_are_independent():
    contract = _assessment(
        risk_score=100,
        risk_level="CRITICAL",
        human_decision=HumanDecision(
            status="RECORDED",
            decision="DEFER",
            actor_id="cab-chair",
            decided_at=NOW,
            rationale_code="awaiting-window",
        ),
    )
    assert contract["scores"]["risk"] == {"value": 100, "level": "CRITICAL"}
    assert contract["scores"]["confidence"]["value"] == 100
    assert contract["verdict"] == "BLOCK"
    assert contract["recommendation"]["grants_approval"] is False
    assert contract["human_decision"]["decision"] == "DEFER"


def test_verified_waiver_is_a_reference_and_does_not_lower_risk_or_failure():
    waiver = WaiverReference(
        waiver_id="WAIVER-42",
        sha256="f" * 64,
        policy_sha256=POLICY.sha256,
        control_ids=("rollback-plan",),
        status="VERIFIED",
        valid_until=NOW + dt.timedelta(days=1),
        reason_code="emergency-window",
        evidence_links=("https://evidence.example.test/waivers/42",),
    )
    contract = _assessment(
        controls=(_control("FAIL"),),
        risk_score=75,
        risk_level="HIGH",
        waivers=(waiver,),
    )
    assert contract["scores"]["risk"]["value"] == 75
    assert contract["controls"][0]["status"] == "FAIL"
    assert contract["verdict"] == "REVIEW_REQUIRED"
    assert contract["waivers"][0]["status"] == "VERIFIED"


def test_legacy_adapter_preserves_source_and_maps_risk_without_network(monkeypatch):
    legacy = {
        "risk_score": 55,
        "risk_level": "MEDIUM",
        "recommendation": "Proceed with caution.",
        "triggered_rules": [
            {
                "id": "database-change",
                "description": "Database change detected",
                "severity": "high",
                "score": 25,
                "source": "Change Type",
            }
        ],
        "missing_controls": ["rollback_plan"],
        "policy_pack": {"name": "default", "version": "1.0", "digest": "1" * 64},
        "monitor_validation": {
            "status": "pass",
            "dashboard_count": 1,
            "valid_dashboard_count": 1,
            "inventory_monitor_count": 1,
            "enabled_monitor_count": 1,
            "referenced_monitor_ids": ["db-alert"],
            "providers": ["prometheus"],
        },
    }
    original = copy.deepcopy(legacy)

    def deny_network(*args, **kwargs):
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "socket", deny_network)
    contract = adapt_legacy_assessment(
        legacy,
        change_id="CHG-42",
        timestamp=NOW,
        context=CONTEXT,
        input_digests={"change-request": "2" * 64, "service-catalog": "3" * 64},
    )
    assert legacy == original
    assert contract["scores"]["risk"] == {"value": 55, "level": "MEDIUM"}
    assert contract["scores"]["confidence"]["value"] == 80
    assert contract["compatibility"] == {
        "source_contract": "risk-report-v1",
        "adapter_version": "1.0",
        "legacy_output_preserved": True,
    }


def test_legacy_adapter_redacts_inline_secret_and_omits_arbitrary_content():
    legacy = {
        "risk_score": 25,
        "risk_level": "LOW",
        "recommendation": "Review token=do-not-serialize before proceeding.",
        "triggered_rules": [
            {
                "id": "custom",
                "description": "authorization=must-never-enter-evidence",
                "severity": "low",
                "score": 25,
                "source": "custom",
                "raw_payload": "full-sensitive-payload",
            }
        ],
        "missing_controls": [],
        "policy_pack": {"name": "default", "version": "1.0"},
    }
    serialized = serialize_assessment_v1(
        adapt_legacy_assessment(
            legacy,
            change_id="CHG-SECRET",
            timestamp=NOW,
            context=CONTEXT,
            input_digests={"safe-projection": "4" * 64},
        )
    )
    assert b"must-never-enter-evidence" not in serialized
    assert b"full-sensitive-payload" not in serialized
    assert b"do-not-serialize" not in serialized
    assert serialized.count(b"[redacted]") == 2


def test_strict_validation_rejects_unknown_fields_and_integrity_tampering():
    unknown = copy.deepcopy(_assessment())
    unknown["unexpected"] = True
    with pytest.raises(AssessmentContractError, match="unexpected"):
        validate_assessment_v1(unknown)

    tampered = copy.deepcopy(_assessment())
    tampered["scores"]["risk"]["value"] = 99
    with pytest.raises(AssessmentContractError, match="integrity"):
        validate_assessment_v1(tampered)


def test_duplicate_control_ids_and_invalid_hashes_fail_closed():
    with pytest.raises(AssessmentContractError, match="unique control_ids"):
        _assessment(controls=(_control(), _control()))
    with pytest.raises(AssessmentContractError, match="64 hexadecimal"):
        _assessment(inputs=(InputDigest("change-request", "not-a-digest"),))


def test_future_evidence_becomes_error_and_cannot_pass():
    contract = _assessment(
        controls=(
            _control(
                collected_at=NOW + dt.timedelta(minutes=1),
                valid_until=NOW + dt.timedelta(hours=1),
            ),
        )
    )
    assert contract["controls"][0]["status"] == "ERROR"
    assert contract["passed_controls"] == []
    assert {error["code"] for error in contract["errors"]} >= {
        "CONTROL_ERROR",
        "EVIDENCE_FROM_FUTURE",
    }


@pytest.mark.parametrize(
    "context,match",
    [
        (
            AssessmentContext(
                actor_id="release-bot",
                actor_type="root",  # type: ignore[arg-type]
                run_id="42",
                run_attempt=1,
                repository="acme/service",
                pull_request=None,
                commit="abc",
                pipeline_name="preflight",
            ),
            "actor.type",
        ),
        (
            AssessmentContext(
                actor_id="release-bot",
                actor_type="automation",
                run_id="42",
                run_attempt=0,
                repository="acme/service",
                pull_request=None,
                commit="abc",
                pipeline_name="preflight",
            ),
            "attempt",
        ),
        (
            AssessmentContext(
                actor_id="release-bot",
                actor_type="automation",
                run_id="42",
                run_attempt=1,
                repository="acme/service",
                pull_request=None,
                commit="abc",
                pipeline_name="preflight",
                pipeline_url="https://ci.example.test/run?token=secret",
            ),
            "query",
        ),
    ],
)
def test_invalid_context_is_rejected_without_echoing_values(context, match):
    with pytest.raises(AssessmentContractError, match=match) as error:
        _assessment(context=context)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"timestamp": dt.datetime(2026, 8, 31, 12, 0)}, "timezone"),
        ({"timestamp": "not-a-time"}, "RFC 3339"),
        ({"risk_score": True}, "risk_score"),
        ({"risk_score": 101}, "risk_score"),
        ({"risk_level": "SEVERE"}, "risk_level"),
        ({"confidence_cap": -1}, "confidence_cap"),
        ({"data_classification": "secret"}, "data_classification"),
        ({"inputs": ()}, "inputs"),
        (
            {"inputs": (InputDigest("same", "1" * 64), InputDigest("same", "2" * 64))},
            "unique names",
        ),
        (
            {"controls": (_control(status="SKIPPED"),)},  # type: ignore[arg-type]
            "unsupported status",
        ),
        ({"controls": (_control(),), "source_contract": "bad value"}, "identifier"),
    ],
)
def test_kernel_rejects_invalid_boundary_inputs(overrides, match):
    with pytest.raises(AssessmentContractError, match=match):
        _assessment(**overrides)


def test_kernel_rejects_invalid_control_points_interval_and_digest():
    negative_points = ControlObservation(
        control_id="negative",
        status="FAIL",
        summary="Invalid negative points.",
        source="test",
        collected_at=NOW,
        valid_until=NOW + dt.timedelta(hours=1),
        risk_points=-1,
        evidence_sha256="1" * 64,
    )
    with pytest.raises(AssessmentContractError, match="non-negative"):
        _assessment(controls=(negative_points,))

    with pytest.raises(AssessmentContractError, match="cannot precede"):
        _assessment(
            controls=(
                _control(
                    collected_at=NOW,
                    valid_until=NOW - dt.timedelta(seconds=1),
                ),
            )
        )

    with pytest.raises(AssessmentContractError, match="64 hexadecimal"):
        _assessment(controls=(_control(evidence_sha256="bad"),))


@pytest.mark.parametrize(
    "decision,match",
    [
        (HumanDecision(status="OTHER"), "status"),  # type: ignore[arg-type]
        (HumanDecision(status="NOT_RECORDED", decision="DEFER"), "cannot contain"),
        (HumanDecision(status="RECORDED"), "requires a decision"),
        (
            HumanDecision(status="RECORDED", decision="DEFER", actor_id="cab", rationale_code="x"),
            "decided_at",
        ),
    ],
)
def test_human_decision_model_rejects_ambiguous_states(decision, match):
    with pytest.raises(AssessmentContractError, match=match):
        _assessment(human_decision=decision)


@pytest.mark.parametrize(
    "waiver,match",
    [
        (
            WaiverReference(
                waiver_id="W-1",
                sha256="1" * 64,
                policy_sha256="2" * 64,
                control_ids=("rollback-plan",),
                status="OTHER",  # type: ignore[arg-type]
                valid_until=NOW + dt.timedelta(hours=1),
                reason_code="reason",
            ),
            "status",
        ),
        (
            WaiverReference(
                waiver_id="W-1",
                sha256="1" * 64,
                policy_sha256="2" * 64,
                control_ids=(),
                status="VERIFIED",
                valid_until=NOW + dt.timedelta(hours=1),
                reason_code="reason",
            ),
            "must not be empty",
        ),
    ],
)
def test_waiver_model_rejects_invalid_states(waiver, match):
    with pytest.raises(AssessmentContractError, match=match):
        _assessment(waivers=(waiver,))


def test_legacy_verified_waiver_is_minimized_and_preserves_failed_control():
    legacy = {
        "risk_score": 90,
        "risk_level": "CRITICAL",
        "recommendation": "Block pending review.",
        "triggered_rules": [
            {
                "id": "missing-rollback-plan",
                "description": "Rollback plan is missing.",
                "severity": "high",
                "score": 55,
                "source": "Service Controls",
            }
        ],
        "missing_controls": [],
        "policy_pack": {"name": "production", "version": "2", "digest": "5" * 64},
        "verified_waivers": [
            {
                "id": "WAIVER-9",
                "digest": "sha256:" + "6" * 64,
                "rules": ["missing-rollback-plan"],
                "reason_code": "emergency",
                "expires_at": "2026-09-01T12:00:00Z",
                "evidence_references": [
                    "CHG-42",
                    "https://evidence.example.test/waivers/9",
                    "https://evidence.example.test/waivers/9?token=drop",
                ],
                "justification": "Sensitive narrative must not be copied.",
            }
        ],
    }
    contract = adapt_legacy_assessment(
        legacy,
        change_id="CHG-42",
        timestamp=NOW,
        context=CONTEXT,
        input_digests={"change-request": "7" * 64},
    )
    assert contract["controls"][0]["status"] == "FAIL"
    assert contract["scores"]["risk"]["value"] == 90
    assert contract["waivers"][0]["evidence_links"] == ["https://evidence.example.test/waivers/9"]
    assert b"Sensitive narrative" not in serialize_assessment_v1(contract)


@pytest.mark.parametrize(
    "legacy,match",
    [
        ([], "object"),
        ({"policy_pack": []}, "policy_pack"),
        ({"policy_pack": {}, "triggered_rules": {}}, "triggered_rules"),
        ({"policy_pack": {}, "triggered_rules": [], "missing_controls": {}}, "missing_controls"),
        (
            {
                "policy_pack": {},
                "triggered_rules": [],
                "missing_controls": [],
                "errors": "failed",
            },
            "errors",
        ),
        (
            {
                "policy_pack": {},
                "triggered_rules": [],
                "missing_controls": [],
                "risk_score": "0",
            },
            "risk_score",
        ),
    ],
)
def test_legacy_adapter_rejects_malformed_shapes(legacy, match):
    with pytest.raises(AssessmentContractError, match=match):
        adapt_legacy_assessment(
            legacy,
            change_id="CHG-42",
            timestamp=NOW,
            context=CONTEXT,
            input_digests={"change-request": "8" * 64},
        )


def test_empty_legacy_result_is_unknown_and_invalid_validity_is_rejected():
    contract = adapt_legacy_assessment(
        {"risk_score": 0, "risk_level": "LOW", "policy_pack": {}},
        change_id="CHG-EMPTY",
        timestamp=NOW,
        context=CONTEXT,
        input_digests={"change-request": "9" * 64},
    )
    assert contract["controls"][0]["status"] == "UNKNOWN"
    assert contract["verdict"] == "INDETERMINATE"

    with pytest.raises(AssessmentContractError, match="valid_for"):
        adapt_legacy_assessment(
            {"risk_score": 0, "risk_level": "LOW", "policy_pack": {}},
            change_id="CHG-EMPTY",
            timestamp=NOW,
            context=CONTEXT,
            input_digests={"change-request": "9" * 64},
            valid_for=dt.timedelta(0),
        )


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda value: value.update(verdict="APPROVED"), "verdict"),
        (
            lambda value: value["recommendation"].update(grants_approval=True),
            "cannot grant approval",
        ),
        (
            lambda value: value["data"].update(content_embedded=True),
            "handling invariants",
        ),
        (
            lambda value: value["controls"][0]["evidence_ids"].append(
                "urn:preflightops:evidence:sha256:" + "f" * 64
            ),
            "unknown evidence_ids",
        ),
        (
            lambda value: value["human_decision"].update(actor_id="unexpected"),
            "Unrecorded",
        ),
        (
            lambda value: value["controls"][0].update(status="ERROR"),
            "passed_controls",
        ),
    ],
)
def test_strict_validator_rejects_cross_field_invariant_mutations(mutation, match):
    contract = copy.deepcopy(_assessment())
    mutation(contract)
    with pytest.raises(AssessmentContractError, match=match):
        validate_assessment_v1(contract)


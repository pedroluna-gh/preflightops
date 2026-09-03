"""Semantic validation, confidence, freshness, privacy, and compatibility tests."""

from __future__ import annotations

import copy
import hashlib
import json
import socket
from pathlib import Path

import jsonschema
import pytest

import preflightops
from preflightops.evidence import canonical_json
from preflightops.semantic_validation import (
    SemanticEvidenceReference,
    SemanticValidationError,
    SemanticValidationPolicy,
    SemanticValidator,
    adapt_legacy_change_request,
    serialize_semantic_validation_v1,
    validate_semantic_validation_v1,
)

ROOT = Path(__file__).resolve().parents[1]
EVALUATED_AT = "2026-09-03T12:30:00Z"
COLLECTED_AT = "2026-09-03T12:00:00Z"
VALID_UNTIL = "2026-09-03T13:00:00Z"


def _step():
    return {
        "action": "Run the read-only production health check",
        "observable_signal": "HTTP status and five-minute error-rate metric",
        "expected_result": "HTTP 200 and error rate below one percent",
    }


def _plans():
    return {
        "rollback_plan": {
            "applicable": True,
            "not_applicable_reason": None,
            "owner": "payments-sre",
            "duration_minutes": 15,
            "success_criteria": ["Previous release serves healthy production traffic"],
            "steps": [_step()],
            "contradictions": [],
            "action": "Redeploy the previously approved container image",
            "trigger": "Error rate exceeds one percent for five minutes",
        },
        "monitoring_plan": {
            "applicable": True,
            "not_applicable_reason": None,
            "owner": "payments-sre",
            "duration_minutes": 30,
            "success_criteria": ["Error rate remains below one percent"],
            "steps": [_step()],
            "contradictions": [],
            "dashboards": [
                {
                    "id": "payments-overview",
                    "url": "https://grafana.example.test/d/payments",
                    "state": "ACTIVE",
                }
            ],
            "alerts": [{"id": "payments-high-errors", "url": None, "state": "ACTIVE"}],
        },
        "validation_plan": {
            "applicable": True,
            "not_applicable_reason": None,
            "owner": "payments-sre",
            "duration_minutes": 20,
            "success_criteria": ["Smoke checks and one business transaction succeed"],
            "steps": [_step()],
            "contradictions": [],
        },
    }


def _evidence(**overrides):
    defaults = {
        "source": "change-request-validator",
        "collected_at": COLLECTED_AT,
        "valid_until": VALID_UNTIL,
        "sha256": "a" * 64,
    }
    defaults.update(overrides)
    return SemanticEvidenceReference(**defaults)


def _evidence_set(**overrides):
    return {
        control_id: _evidence(**overrides)
        for control_id in ("monitoring-plan", "rollback-plan", "validation-plan")
    }


def _evaluate(plans=None, evidence=None, **kwargs):
    return SemanticValidator().evaluate(
        plans=_plans() if plans is None else plans,
        evidence=_evidence_set() if evidence is None else evidence,
        evaluated_at=EVALUATED_AT,
        **kwargs,
    )


def _control(contract, control_id):
    return next(item for item in contract["controls"] if item["control_id"] == control_id)


def test_complete_contract_is_pass_deterministic_and_matches_schema():
    first = _evaluate()
    second = _evaluate(plans=copy.deepcopy(_plans()), evidence=_evidence_set())

    assert serialize_semantic_validation_v1(first) == serialize_semantic_validation_v1(second)
    assert first["summary"]["status"] == "PASS"
    assert first["summary"]["confidence"]["value"] == 100
    assert all(item["status"] == "PASS" for item in first["controls"])
    assert all(item["confidence"]["value"] == 100 for item in first["controls"])

    schema = json.loads(
        (ROOT / "schemas" / "semantic-validation-v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(first, schema)


def test_structured_input_matches_schema():
    schema = json.loads(
        (ROOT / "schemas" / "semantic-change-controls-v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(_plans(), schema)


def test_golden_contract_bytes_are_stable():
    expected = (ROOT / "tests" / "fixtures" / "semantic" / "semantic-v1.golden.json").read_bytes()
    assert serialize_semantic_validation_v1(_evaluate()) == expected


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("action", "todo", "PLACEHOLDER_TEXT"),
        ("trigger", "qwerty", "PLACEHOLDER_TEXT"),
        ("owner", "aaaaaaaaaaaaaaaa", "NON_SEMANTIC_TEXT"),
    ],
)
def test_placeholders_and_gibberish_fail_with_high_confidence(field, value, code):
    plans = _plans()
    plans["rollback_plan"][field] = value
    control = _control(_evaluate(plans=plans), "rollback-plan")

    assert control["status"] == "FAIL"
    assert control["confidence"]["value"] == 100
    assert control["confidence"]["level"] == "HIGH"
    assert code in {item["code"] for item in control["issues"]}


@pytest.mark.parametrize("field", ["steps", "success_criteria"])
def test_empty_required_lists_fail(field):
    plans = _plans()
    plans["validation_plan"][field] = []
    control = _control(_evaluate(plans=plans), "validation-plan")
    assert control["status"] == "FAIL"
    assert "EMPTY_LIST" in {item["code"] for item in control["issues"]}


def test_absent_provider_is_unknown_and_never_passes():
    evidence = _evidence_set()
    evidence.pop("rollback-plan")
    control = _control(_evaluate(evidence=evidence), "rollback-plan")

    assert control["status"] == "UNKNOWN"
    assert control["freshness"] == "UNKNOWN"
    assert control["confidence"]["cap"] == 25
    assert control["confidence"]["level"] == "LOW"
    assert "PROVIDER_ABSENT" in {item["code"] for item in control["issues"]}


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"parser_status": "ERROR"}, "PARSER_ERROR"),
        ({"provider_status": "ERROR"}, "PROVIDER_ERROR"),
        ({"collected_at": "2026-09-03T14:00:00Z"}, "EVIDENCE_FROM_FUTURE"),
        ({"sha256": "not-a-digest"}, "DIGEST_INVALID"),
        ({"valid_until": "2026-09-03T11:00:00Z"}, "INVALID_VALIDITY_INTERVAL"),
    ],
)
def test_evidence_errors_are_error_with_nonlinear_cap(overrides, expected_code):
    control = _control(_evaluate(evidence=_evidence_set(**overrides)), "rollback-plan")
    assert control["status"] == "ERROR"
    assert control["confidence"]["cap"] == 20
    assert expected_code in {item["code"] for item in control["issues"]}


def test_expired_pass_becomes_unknown_but_expired_failure_stays_failure():
    stale = _evidence_set(valid_until="2026-09-03T12:15:00Z")
    passed = _control(_evaluate(evidence=stale), "rollback-plan")
    assert passed["freshness"] == "STALE"
    assert passed["status"] == "UNKNOWN"
    assert passed["confidence"]["cap"] == 49

    plans = _plans()
    plans["rollback_plan"]["action"] = "todo"
    failed = _control(_evaluate(plans=plans, evidence=stale), "rollback-plan")
    assert failed["freshness"] == "STALE"
    assert failed["status"] == "FAIL"
    assert failed["confidence"]["cap"] == 49


def test_policy_ttl_can_expire_before_declared_valid_until():
    contract = _evaluate(policy=SemanticValidationPolicy(max_age_seconds=600))
    control = _control(contract, "rollback-plan")
    assert control["evidence"]["valid_until"] == VALID_UNTIL
    assert control["evidence"]["effective_valid_until"] == "2026-09-03T12:10:00Z"
    assert control["freshness"] == "STALE"
    assert control["status"] == "UNKNOWN"


def test_not_applicable_requires_reason_and_fresh_evidence():
    plans = _plans()
    plans["validation_plan"] = {
        "applicable": False,
        "not_applicable_reason": "No runtime behavior changes in this documentation-only update",
        "owner": None,
        "duration_minutes": None,
        "success_criteria": [],
        "steps": [],
        "contradictions": [],
    }
    control = _control(_evaluate(plans=plans), "validation-plan")
    assert control["status"] == "NOT_APPLICABLE"
    assert control["confidence"]["value"] == 100

    plans["validation_plan"]["not_applicable_reason"] = "todo"
    invalid = _control(_evaluate(plans=plans), "validation-plan")
    assert invalid["status"] == "FAIL"


def test_broken_unknown_and_invalid_references_fail_closed_without_network(monkeypatch):
    def forbidden_socket(*args, **kwargs):
        raise AssertionError("semantic validation attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    plans = _plans()
    plans["monitoring_plan"]["dashboards"][0]["state"] = "BROKEN"
    broken = _control(_evaluate(plans=plans), "monitoring-plan")
    assert broken["status"] == "FAIL"
    assert "BROKEN_REFERENCE" in {item["code"] for item in broken["issues"]}

    plans = _plans()
    plans["monitoring_plan"]["alerts"][0]["state"] = "UNKNOWN"
    unknown = _control(_evaluate(plans=plans), "monitoring-plan")
    assert unknown["status"] == "UNKNOWN"

    plans = _plans()
    plans["monitoring_plan"]["dashboards"][0]["url"] = "https://user:secret@example.test/x"
    invalid = _control(_evaluate(plans=plans), "monitoring-plan")
    assert invalid["status"] == "FAIL"
    assert "INVALID_REFERENCE_URL" in {item["code"] for item in invalid["issues"]}


def test_declared_contradiction_fails_without_copying_content():
    marker = "CONTRADICTION-SENSITIVE-MARKER-84912"
    plans = _plans()
    plans["rollback_plan"]["contradictions"] = [marker]
    serialized = serialize_semantic_validation_v1(_evaluate(plans=plans))

    assert _control(_evaluate(plans=plans), "rollback-plan")["status"] == "FAIL"
    assert marker.encode() not in serialized


def test_plan_content_and_secret_markers_are_never_serialized():
    marker = "PASSWORD=never-copy-this-58391"
    plans = _plans()
    plans["rollback_plan"]["action"] = (
        "Redeploy the previous image using the protected pipeline " + marker
    )
    output = serialize_semantic_validation_v1(_evaluate(plans=plans))
    assert marker.encode() not in output
    assert b"Redeploy the previous image" not in output
    assert b"success_criteria" not in output


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["controls"][0].__setitem__("status", "FAIL"),
        lambda value: value["controls"][0]["confidence"].__setitem__("value", 1),
        lambda value: value["controls"][0]["issues"].append(
            {"code": "EXTRA", "field": "x", "message": "tampered"}
        ),
        lambda value: value["data"].__setitem__("content_embedded", True),
    ],
)
def test_strict_validation_rejects_tamper(mutation):
    contract = _evaluate()
    mutation(contract)
    with pytest.raises(SemanticValidationError):
        validate_semantic_validation_v1(contract)


def test_resealed_confidence_component_tamper_is_rejected():
    contract = _evaluate()
    control = contract["controls"][0]
    control["confidence"]["components"]["provenance"] = 0
    control["confidence"]["value"] = 85
    body = dict(control)
    body.pop("execution_id")
    control["execution_id"] = (
        "urn:preflightops:semantic-control:sha256:"
        + hashlib.sha256(canonical_json(body)).hexdigest()
    )
    contract["summary"]["confidence"]["value"] = 95
    contract["summary"]["confidence"]["level"] = "HIGH"
    semantic = dict(contract)
    semantic.pop("semantic_validation_id")
    semantic.pop("integrity")
    digest = hashlib.sha256(canonical_json(semantic)).hexdigest()
    contract["semantic_validation_id"] = f"urn:preflightops:semantic-validation:sha256:{digest}"
    contract["integrity"]["value"] = digest

    with pytest.raises(SemanticValidationError, match="provenance confidence"):
        validate_semantic_validation_v1(contract)


def test_legacy_adapter_is_additive_and_does_not_infer_prose():
    change = {
        "change": {
            "rollback_plan": "Redeploy the previous image when errors exceed one percent",
            "monitoring_plan": {"dashboards": ["https://grafana.example.test/d/x"]},
            "validation_plan": ["Run smoke tests"],
        }
    }
    before = copy.deepcopy(change)
    contract = adapt_legacy_change_request(
        change,
        evidence=_evidence_set(),
        evaluated_at=EVALUATED_AT,
    )

    assert change == before
    assert contract["compatibility"] == {
        "source_contract": "change-request-v1",
        "adapter_version": "1.0",
        "legacy_validators_preserved": True,
        "legacy_output_preserved": True,
    }
    assert all(item["status"] == "FAIL" for item in contract["controls"])
    assert callable(preflightops.is_bad_rollback_plan)
    assert callable(preflightops.is_monitoring_plan_incomplete)
    assert callable(preflightops.is_validation_plan_valid)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"plans": {"unsupported": {}}, "evidence": {}},
        {"plans": {}, "evidence": {"unsupported": _evidence()}},
        {"plans": {}, "evidence": {}, "policy": SemanticValidationPolicy(max_age_seconds=0)},
        {"plans": {}, "evidence": {}, "evaluated_at": "2026-09-03T12:30:00"},
    ],
)
def test_invalid_api_boundaries_are_rejected(kwargs):
    values = {"plans": _plans(), "evidence": _evidence_set(), "evaluated_at": EVALUATED_AT}
    values.update(kwargs)
    with pytest.raises(SemanticValidationError):
        SemanticValidator().evaluate(**values)

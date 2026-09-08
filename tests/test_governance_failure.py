"""Failure modes must not turn unavailable evidence or exceptions into approval."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_policy_governance import NOW, _bundle, _keys

from preflightops.governance_failure import evaluate_failure_modes
from preflightops.policy_governance import (
    apply_verified_waivers,
    sign_governance_document,
    validate_policy_bundle,
)
from preflightops.risk_engine import assess_risk


@pytest.mark.parametrize("mode", ["open", "closed"])
def test_evidence_failure_disposition(mode):
    modes = _bundle()["spec"]["failure_modes"]
    modes["evidence_unavailable"] = mode
    result = evaluate_failure_modes(modes, ["evidence_unavailable"])
    assert result["blocking"] is (mode == "closed")
    assert result["disposition"] == ("stop" if mode == "closed" else "continue_informative")
    assert result["automatic_approval"] is False
    assert result["human_decision"] == "not_recorded"
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/governance-failure-v1.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(result)


@pytest.mark.parametrize("error", ["signature", "policy_validation", "context_conflict", "secret"])
def test_governance_and_unknown_errors_always_stop(error):
    modes = _bundle()["spec"]["failure_modes"]
    modes["evidence_unavailable"] = "open"
    result = evaluate_failure_modes(modes, [error, "evidence_unavailable"])
    assert result["blocking"] is True
    assert "secret" not in str(result)
    assert result == evaluate_failure_modes(modes, ["evidence_unavailable", error, error])


def test_invalid_modes_rejected():
    modes = _bundle()["spec"]["failure_modes"]
    modes["signature"] = "open"
    with pytest.raises(ValueError):
        evaluate_failure_modes(modes, [])
    with pytest.raises(ValueError):
        evaluate_failure_modes({}, [])


@pytest.mark.parametrize("failures", ["signature", [None], ["signature"] * 1001])
def test_invalid_or_excessive_failure_collection(failures):
    with pytest.raises(ValueError):
        evaluate_failure_modes(_bundle()["spec"]["failure_modes"], failures)


@pytest.mark.parametrize("mode", ["open", "closed"])
def test_risk_integration_preserves_scores_and_waiver_cannot_remove_stop(mode):
    document = _bundle()
    document["spec"]["failure_modes"]["evidence_unavailable"] = mode
    private, public = _keys()
    bundle = validate_policy_bundle(
        sign_governance_document(document, private, "policy"), public_key=public, at=NOW
    )
    services = {"services": [{"name": "checkout", "owner": "sre", "criticality": "low"}]}
    change = {"change": {"service": "checkout", "environment": "production"}}
    result = assess_risk(services, change, policy=bundle)
    original = deepcopy(result)
    decision = result["decision_record"]["failure_handling"]
    assert decision["blocking"] is (mode == "closed")
    annotated = apply_verified_waivers(result, [])
    assert annotated["decision_record"]["failure_handling"] == decision
    assert annotated["risk_score"] == result["risk_score"]
    assert result == original
    available = assess_risk(services, change, policy=bundle, monitor_inventory={"monitors": []})
    assert available["decision_record"]["failure_handling"]["disposition"] == "none"
    assert available["monitor_validation"]["status"] == "fail"
    assert available["risk_score"] == result["risk_score"]


def test_legacy_output_has_no_new_failure_handling():
    result = assess_risk({"services": [{"name": "checkout"}]}, {"change": {"service": "checkout"}})
    assert "failure_handling" not in result["decision_record"]

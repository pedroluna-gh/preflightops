"""Offline contract checks for the ServiceNow enterprise design."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
EXAMPLES = ROOT / "examples"
DOCS = ROOT / "docs"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _schema(name: str):
    return _json(SCHEMAS / name)


def _validate(instance, schema_name: str):
    jsonschema.validate(
        instance,
        _schema(schema_name),
        format_checker=jsonschema.FormatChecker(),
    )


@pytest.mark.parametrize(
    "name",
    [
        "servicenow-mapping-v2.schema.json",
        "servicenow-adapter-request-v2.schema.json",
        "servicenow-adapter-result-v2.schema.json",
    ],
)
def test_v2_design_schemas_are_strict_draft_2020_12(name):
    schema = _schema(name)
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False


def test_v2_examples_validate_without_network_or_secrets():
    mapping_text = (EXAMPLES / "servicenow-enterprise-mapping-v2.yaml").read_text(encoding="utf-8")
    mapping = yaml.safe_load(mapping_text)
    enrich = _json(EXAMPLES / "servicenow-enrich-request-v2.json")
    create = _json(EXAMPLES / "servicenow-create-draft-request-v2.json")
    result = _json(EXAMPLES / "servicenow-preview-result-v2.json")

    _validate(mapping, "servicenow-mapping-v2.schema.json")
    _validate(enrich, "servicenow-adapter-request-v2.schema.json")
    _validate(create, "servicenow-adapter-request-v2.schema.json")
    _validate(result, "servicenow-adapter-result-v2.schema.json")

    serialized = "\n".join(
        [mapping_text, json.dumps(enrich), json.dumps(create), json.dumps(result)]
    ).lower()
    for forbidden in ("servicenow_token", "client_secret", "password", "bearer ", "private key"):
        assert forbidden not in serialized


def test_mapping_uses_expected_semantics_and_no_workflow_fields():
    mapping = yaml.safe_load(
        (EXAMPLES / "servicenow-enterprise-mapping-v2.yaml").read_text(encoding="utf-8")
    )
    expected_sources = {
        "assessment_status": "decision.verdict",
        "risk": "scores.risk",
        "confidence": "scores.confidence",
        "assessment_id": "audit.assessment_id",
        "policy": "audit.policy",
        "blockers": "controls.top_blockers",
        "risk_impact": "decision.technical_recommendation.summary",
        "automation_details": "automation_details",
        "evidence_url": "delivery.evidence_url",
        "commit": "audit.commit",
        "timestamp": "audit.assessment_timestamp",
    }
    assert {key: value["source"] for key, value in mapping["fields"].items()} == expected_sources
    destinations = {rule["destination"] for rule in mapping["fields"].values()}
    forbidden = {
        "state",
        "approval",
        "assignment_group",
        "assigned_to",
        "start_date",
        "end_date",
        "close_code",
        "work_notes",
    }
    assert not destinations.intersection(forbidden)
    assert mapping["api"]["table_api_legacy_mode"] == "read_only"
    assert mapping["concurrency"]["strategy"] == "server_compare_and_set"


def test_mapping_schema_rejects_privileged_destination_and_extra_semantic():
    mapping = yaml.safe_load(
        (EXAMPLES / "servicenow-enterprise-mapping-v2.yaml").read_text(encoding="utf-8")
    )
    privileged = copy.deepcopy(mapping)
    privileged["fields"]["assessment_status"]["destination"] = "state"
    with pytest.raises(jsonschema.ValidationError):
        _validate(privileged, "servicenow-mapping-v2.schema.json")

    extra = copy.deepcopy(mapping)
    extra["fields"]["approval"] = {
        "source": "decision.verdict",
        "destination": "u_approval",
        "max_length": 32,
    }
    with pytest.raises(jsonschema.ValidationError):
        _validate(extra, "servicenow-mapping-v2.schema.json")


def test_enrich_requires_exact_target_and_expected_mod_count():
    enrich = _json(EXAMPLES / "servicenow-enrich-request-v2.json")
    missing_target = copy.deepcopy(enrich)
    missing_target.pop("target")
    with pytest.raises(jsonschema.ValidationError):
        _validate(missing_target, "servicenow-adapter-request-v2.schema.json")

    ambiguous = copy.deepcopy(enrich)
    ambiguous["target"]["sys_id"] = "1" * 32
    with pytest.raises(jsonschema.ValidationError):
        _validate(ambiguous, "servicenow-adapter-request-v2.schema.json")

    no_cas = copy.deepcopy(enrich)
    no_cas["preconditions"].pop("expected_sys_mod_count")
    with pytest.raises(jsonschema.ValidationError):
        _validate(no_cas, "servicenow-adapter-request-v2.schema.json")


def test_create_requires_model_and_never_accepts_target():
    create = _json(EXAMPLES / "servicenow-create-draft-request-v2.json")
    no_model = copy.deepcopy(create)
    no_model["creation"].pop("model_sys_id")
    with pytest.raises(jsonschema.ValidationError):
        _validate(no_model, "servicenow-adapter-request-v2.schema.json")

    with_target = copy.deepcopy(create)
    with_target["target"] = {"number": "CHG0000002"}
    with pytest.raises(jsonschema.ValidationError):
        _validate(with_target, "servicenow-adapter-request-v2.schema.json")


def test_live_write_requires_gateway_and_disables_dry_run():
    enrich = _json(EXAMPLES / "servicenow-enrich-request-v2.json")
    direct = copy.deepcopy(enrich)
    direct.update(
        {"write_enabled": True, "dry_run": False, "transport_profile": "change_management_v1"}
    )
    with pytest.raises(jsonschema.ValidationError):
        _validate(direct, "servicenow-adapter-request-v2.schema.json")

    contradictory = copy.deepcopy(enrich)
    contradictory.update({"write_enabled": True, "dry_run": True})
    with pytest.raises(jsonschema.ValidationError):
        _validate(contradictory, "servicenow-adapter-request-v2.schema.json")


def test_result_cannot_claim_unverified_success_or_hide_failure():
    result = _json(EXAMPLES / "servicenow-preview-result-v2.json")
    false_success = copy.deepcopy(result)
    false_success.update(
        {
            "outcome": "UPDATED",
            "verified": False,
            "target": {"number": "CHG0000001", "sys_id": "1" * 32, "sys_mod_count": 8},
        }
    )
    with pytest.raises(jsonschema.ValidationError):
        _validate(false_success, "servicenow-adapter-result-v2.schema.json")

    hidden_failure = copy.deepcopy(result)
    hidden_failure["outcome"] = "PARTIAL_FAILURE_UNKNOWN"
    with pytest.raises(jsonschema.ValidationError):
        _validate(hidden_failure, "servicenow-adapter-result-v2.schema.json")


def test_design_documents_cover_required_controls_and_migration():
    golden = (DOCS / "SERVICENOW_ENTERPRISE_GOLDEN_PATH.md").read_text(encoding="utf-8")
    contract = (DOCS / "SERVICENOW_ADAPTER_CONTRACT_V2.md").read_text(encoding="utf-8")
    test_plan = (DOCS / "SERVICENOW_TEST_PLAN_V2.md").read_text(encoding="utf-8")
    migration = (DOCS / "SERVICENOW_MIGRATION_V2.md").read_text(encoding="utf-8")
    diagram = (DOCS / "diagrams" / "servicenow-enterprise-golden-path.mmd").read_text(
        encoding="utf-8"
    )
    combined = "\n".join([golden, contract, test_plan, migration, diagram])
    for required in (
        "SSRF",
        "REDIRECT_REJECTED",
        "wrong-record",
        "Privilege escalation",
        "Replay",
        "PARTIAL_FAILURE_UNKNOWN",
        "OAuth",
        "mTLS",
        "Retry-After",
        "sys_mod_count",
        "create_draft",
        "Table API",
        "Change Management API",
        "rollback",
    ):
        assert required.lower() in combined.lower()


def test_v1_runtime_contract_remains_present_and_unchanged_in_authority():
    legacy_mapping = yaml.safe_load(
        (EXAMPLES / "servicenow-field-map.yaml").read_text(encoding="utf-8")
    )
    integration = (ROOT / "preflightops" / "servicenow.py").read_text(encoding="utf-8")
    normalized_integration = " ".join(integration.split())
    assert legacy_mapping["version"] == "1"
    assert legacy_mapping["table"] == "change_request"
    assert (
        "deliberately refuses to map workflow, approval, assignment, or closure fields"
        in normalized_integration
    )

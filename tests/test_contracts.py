"""Contract, versioning, schema, and critical documentation checks."""

import importlib.metadata
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

import preflightops
from preflightops import cli, sample_data
from preflightops._version import __version__ as source_version
from preflightops.report import generate_json_report
from preflightops.risk_engine import assess_risk
from preflightops.ticket import DEFAULT_TEMPLATE

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


def _schema(name):
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    [
        "service-catalog-v1.schema.json",
        "change-request-v1.schema.json",
        "risk-report-v1.schema.json",
        "ticket-template-v1.schema.json",
        "policy-pack-v1.schema.json",
        "monitor-inventory-v1.schema.json",
    ],
)
def test_schemas_are_valid_draft_2020_12(name):
    jsonschema.Draft202012Validator.check_schema(_schema(name))


def test_shipped_examples_match_input_schemas():
    services = yaml.safe_load(
        (ROOT / "examples" / "services-high-risk.yaml").read_text(encoding="utf-8")
    )
    change = yaml.safe_load(
        (ROOT / "examples" / "change-high-risk.yaml").read_text(encoding="utf-8")
    )
    jsonschema.validate(services, _schema("service-catalog-v1.schema.json"))
    jsonschema.validate(change, _schema("change-request-v1.schema.json"))
    monitors = yaml.safe_load((ROOT / "examples" / "monitors.yaml").read_text(encoding="utf-8"))
    jsonschema.validate(monitors, _schema("monitor-inventory-v1.schema.json"))
    for policy in (ROOT / "policy-packs").glob("*.yaml"):
        jsonschema.validate(
            yaml.safe_load(policy.read_text(encoding="utf-8")),
            _schema("policy-pack-v1.schema.json"),
        )


def test_json_report_matches_v1_schema():
    result = assess_risk(sample_data.HIGH_RISK_SERVICES, sample_data.HIGH_RISK_CHANGE)
    report = json.loads(generate_json_report(result))
    jsonschema.validate(report, _schema("risk-report-v1.schema.json"))


def test_default_ticket_template_matches_v1_schema():
    jsonschema.validate(DEFAULT_TEMPLATE, _schema("ticket-template-v1.schema.json"))


def test_package_and_module_versions_have_one_value():
    assert preflightops.__version__ == source_version
    assert importlib.metadata.version("preflightops") == source_version


def test_cli_version_uses_the_same_source(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"preflightops {source_version}"


def test_public_api_is_in_contract_inventory():
    contracts = (ROOT / "docs" / "CONTRACTS.md").read_text(encoding="utf-8")
    for symbol in preflightops.__all__:
        assert f"`{symbol}`" in contracts


def test_source_workflow_is_documented_as_manual_adoption_example():
    workflow = (ROOT / ".github" / "workflows" / "preflightops.yml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "\n  pull_request:" not in workflow
    assert "manually dispatched adoption example" in readme
    assert "Engineering quality gates run separately" in readme


def test_security_policy_acknowledges_opt_in_network_calls():
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "calls ServiceNow or Jira only when" in policy
    assert "does not call external APIs;" not in policy

"""Security contract for the manual ServiceNow evidence demo workflow."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "servicenow-demo.yml"
MAPPING_PATH = ROOT / "examples" / "servicenow-field-map.yaml"


def _workflow():
    with WORKFLOW_PATH.open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=yaml.BaseLoader)


def test_demo_is_manual_only_and_read_only():
    workflow = _workflow()
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}


def test_live_job_is_environment_protected_and_dry_run_gated():
    workflow = _workflow()
    publish = workflow["jobs"]["publish"]
    assert publish["environment"]["name"] == "servicenow-demo"
    assert "inputs.dry_run == false" in publish["if"]
    preview = workflow["jobs"]["preview"]
    preview_text = yaml.safe_dump(preview)
    assert "servicenow-dry-run" in preview_text
    assert "servicenow-attach-evidence" in preview_text


def test_live_job_enriches_existing_change_and_scopes_secrets():
    workflow = _workflow()
    publish = workflow["jobs"]["publish"]
    serialized = yaml.safe_dump(publish)
    assert "servicenow-change" in serialized
    assert "secrets.SERVICENOW_TOKEN" in serialized
    assert "secrets.SERVICENOW_PASSWORD" in serialized
    assert "pull_request" not in WORKFLOW_PATH.read_text(encoding="utf-8").split("permissions:")[0]


def test_example_mapping_cannot_write_cab_workflow_fields():
    mapping = yaml.safe_load(MAPPING_PATH.read_text(encoding="utf-8"))
    forbidden = {
        "state",
        "approval",
        "assignment_group",
        "assigned_to",
        "start_date",
        "end_date",
        "close_code",
    }
    assert not forbidden.intersection(mapping["fields"])

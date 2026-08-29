"""Tests for the composite GitHub Action manifest (``action.yml``).

These lock in that ``action.yml`` exposes the optional ticket / integration
inputs and the ``ticket-path`` output, that the existing inputs/outputs are
preserved, and that the run script maps the ``assume-yes`` input to the CLI's
``--yes`` flag. The ``action.yml`` file lives at the repository root.
"""

import os

import pytest
import yaml

ACTION_YML = os.path.join(os.path.dirname(os.path.dirname(__file__)), "action.yml")


@pytest.fixture(scope="module")
def action_text():
    with open(ACTION_YML, encoding="utf-8") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def action(action_text):
    return yaml.safe_load(action_text)


def test_action_yml_exists():
    assert os.path.isfile(ACTION_YML), "action.yml must exist at the repository root"


@pytest.mark.parametrize(
    "name",
    [
        "ticket-output",
        "ticket-template",
        "servicenow",
        "servicenow-mapping",
        "servicenow-change",
        "servicenow-attach-evidence",
        "servicenow-dry-run",
        "servicenow-preview-output",
        "jira",
        "assume-yes",
        "evidence-v2-output",
        "evidence-v1-output",
        "evidence-data-classification",
    ],
)
def test_new_optional_inputs_present(action, name):
    assert name in action["inputs"], f"action.yml is missing the '{name}' input"
    # New inputs must be optional so existing workflows keep working unchanged.
    assert action["inputs"][name].get("required", False) is False


def test_existing_inputs_preserved(action):
    for name in (
        "services",
        "change",
        "terraform",
        "k8s",
        "output",
        "json-output",
        "fail-on",
    ):
        assert name in action["inputs"], f"existing input '{name}' was removed"


def test_existing_outputs_preserved(action):
    for name in ("risk-level", "risk-score", "report-path", "json-report-path"):
        assert name in action["outputs"], f"existing output '{name}' was removed"


def test_servicenow_preview_output_added(action):
    assert "servicenow-preview-path" in action["outputs"]


def test_ticket_path_output_added(action):
    assert "ticket-path" in action["outputs"]


def test_authenticated_evidence_outputs_are_present(action):
    assert "evidence-v2-path" in action["outputs"]
    assert "evidence-v1-path" in action["outputs"]


def test_action_never_accepts_private_key_as_an_input(action, action_text):
    assert "evidence-private-key" not in action["inputs"]
    assert "--private-key" not in action_text
    assert "PREFLIGHTOPS_EVIDENCE_PRIVATE_KEY" in action_text


@pytest.mark.parametrize(
    "name",
    [
        "changed-files",
        "auto-detect-changes",
        "html-output",
        "github-comment-output",
        "full-report-url",
    ],
)
def test_reporting_and_detection_inputs_are_optional(action, name):
    assert name in action["inputs"]
    assert action["inputs"][name].get("required", False) is False


@pytest.mark.parametrize(
    "name",
    ["html-report-path", "github-comment-path", "changed-files-path", "scanner-scope"],
)
def test_reporting_and_detection_outputs_are_present(action, name):
    assert name in action["outputs"]


def test_run_script_passes_new_flags(action_text):
    # The run script must translate the inputs into the real CLI flags, and map
    # the assume-yes input to --yes (the CLI flag is --yes / --assume-yes).
    for flag in (
        "--ticket-output",
        "--ticket-template",
        "--servicenow",
        "--servicenow-mapping",
        "--servicenow-change",
        "--servicenow-attach-evidence",
        "--servicenow-dry-run",
        "--jira",
        "--yes",
    ):
        assert flag in action_text, f"run script does not pass {flag}"


def test_action_detects_pr_files_and_passes_report_flags(action_text):
    assert "python -m preflightops.changed_files" in action_text
    assert "--changed-files" in action_text
    assert "--repository-root" in action_text
    assert "--html-output" in action_text
    assert "--github-comment-output" in action_text


def test_no_changeguard_references(action_text):
    assert "ChangeGuard" not in action_text

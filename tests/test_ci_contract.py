"""Contract tests for reproducible CI and the separate adoption example."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
EXAMPLE_PATH = ROOT / ".github" / "workflows" / "preflightops.yml"


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=yaml.BaseLoader)


def test_ci_has_minimum_permissions_and_no_skipped_quality_steps():
    workflow = _load(CI_PATH)
    assert workflow["permissions"] == {"contents": "read"}
    quality_steps = workflow["jobs"]["quality"]["steps"]
    names = {step["name"] for step in quality_steps}
    assert {
        "Check formatting",
        "Lint",
        "Type check",
        "Test with branch coverage",
        "Build distributions",
        "Test clean wheel installation and CLI",
    } <= names
    assert all("continue-on-error" not in step for step in quality_steps)


def test_ci_covers_declared_python_floor_and_current_versions():
    workflow = _load(CI_PATH)
    entries = workflow["jobs"]["compatibility"]["strategy"]["matrix"]["include"]
    linux_versions = {entry["python"] for entry in entries if entry["os"] == "ubuntu-24.04"}
    assert linux_versions == {"3.11", "3.12", "3.13"}
    assert {entry["os"] for entry in entries} >= {"windows-2025", "macos-15"}


def test_ci_audits_every_supported_python_version():
    workflow = _load(CI_PATH)
    audit = workflow["jobs"]["dependency-audit"]
    assert set(audit["strategy"]["matrix"]["python"]) == {"3.11", "3.12", "3.13"}
    steps = {step["name"]: step for step in audit["steps"]}
    export = steps["Export runtime and toolchain dependencies for Python ${{ matrix.python }}"][
        "run"
    ]
    assert '--python "${{ matrix.python }}"' in export
    assert "--all-groups --all-extras" in export
    audit_run = steps["Audit runtime and toolchain dependencies for Python ${{ matrix.python }}"][
        "run"
    ]
    assert audit_run.count("pip-audit") == 2


def test_ci_distinguishes_product_risk_from_pipeline_failure():
    workflow = _load(CI_PATH)
    steps = workflow["jobs"]["action-contract"]["steps"]
    low = next(step for step in steps if step["name"] == "LOW risk must pass")
    critical = next(
        step for step in steps if step["name"] == "CRITICAL risk must fail the risk gate"
    )
    assertion = next(step for step in steps if step["name"] == "Assert CRITICAL contract")
    # These are hermetic fixture contracts. PR changed-file discovery is tested
    # separately and must not make the LOW fixture depend on the PR's contents.
    assert low["with"]["auto-detect-changes"] == "false"
    assert critical["with"]["auto-detect-changes"] == "false"
    assert critical["continue-on-error"] == "true"
    assert "steps.critical.outcome" in assertion["run"]
    assert "CRITICAL" in assertion["run"]


def test_adoption_workflow_is_manual_read_only_and_uses_real_examples():
    workflow = _load(EXAMPLE_PATH)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    text = EXAMPLE_PATH.read_text(encoding="utf-8")
    assert "uses: ./" in text
    assert "examples/services-${{ inputs.scenario }}-risk.yaml" in text
    assert "services.yaml" not in text


def test_ci_exposes_stable_required_check_contract():
    workflow = _load(CI_PATH)
    required = workflow["jobs"]["required"]
    assert required["name"] == "Required"
    assert set(required["needs"]) == {
        "quality",
        "compatibility",
        "dependency-audit",
        "action-contract",
    }
    assert required["if"] == "${{ always() }}"
    step = required["steps"][0]
    assert step["name"] == "Verify required CI contracts"
    assert all(
        result in step["run"]
        for result in (
            "QUALITY_RESULT",
            "COMPATIBILITY_RESULT",
            "DEPENDENCY_AUDIT_RESULT",
            "ACTION_CONTRACT_RESULT",
        )
    )

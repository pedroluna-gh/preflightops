"""Contracts for the enterprise governance and secure release baseline."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
EXTERNAL_USE = re.compile(r"^\s*uses:\s+([^./\s][^@\s]*)@([^\s#]+)", re.MULTILINE)
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _load(name: str) -> dict:
    with (WORKFLOWS / name).open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=yaml.BaseLoader)


def test_all_external_actions_are_immutable():
    surfaces = [ROOT / "action.yml", *WORKFLOWS.glob("*.yml")]
    found = []
    for path in surfaces:
        text = path.read_text(encoding="utf-8")
        if path.parent == WORKFLOWS:
            assert not re.search(r"^\s*pull_request_target\s*:", text, re.MULTILINE)
        for action, ref in EXTERNAL_USE.findall(text):
            found.append((path.name, action))
            assert FULL_SHA.fullmatch(ref), f"{path}: {action}@{ref} is not pinned"
    assert found


def test_security_workflow_is_least_privilege_and_fail_closed():
    workflow = _load("security.yml")
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["codeql"]["permissions"]["security-events"] == "write"
    dependency = workflow["jobs"]["dependency-review"]
    assert dependency["if"] == "${{ github.event_name == 'pull_request' }}"
    step = next(
        s for s in dependency["steps"] if s["name"] == "Reject vulnerable dependency changes"
    )
    assert step["with"]["fail-on-severity"] == "high"
    assert all(
        "continue-on-error" not in step
        for job in workflow["jobs"].values()
        for step in job["steps"]
    )


def test_release_builds_once_and_attests_exact_bundle():
    workflow = _load("release.yml")
    job = workflow["jobs"]["build-attest-release"]
    assert job["needs"] == "dependency-audit"
    assert job["environment"] == "release"
    assert job["permissions"] == {
        "contents": "write",
        "id-token": "write",
        "attestations": "write",
    }
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert text.count("python -m build") == 1
    assert "anchore/sbom-action@" in text
    assert "actions/attest@" in text
    assert "sha256sum * > SHA256SUMS" in text
    assert "gh release create" in text


def test_release_audits_every_supported_python_before_publish():
    workflow = _load("release.yml")
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


def test_fuzzing_workflow_is_bounded_pinned_and_least_privilege():
    workflow = _load("fuzzing.yml")
    job = workflow["jobs"]["clusterfuzzlite"]
    assert workflow["permissions"] == "read-all"
    assert job["permissions"] == {
        "contents": "read",
        "security-events": "write",
    }
    assert job["timeout-minutes"] == "25"
    assert "head.repo.full_name == github.repository" in job["if"]
    actions = [step["uses"] for step in job["steps"]]
    assert all(FULL_SHA.fullmatch(action.rsplit("@", 1)[1]) for action in actions)
    run = next(step for step in job["steps"] if step["name"] == "Run fuzz targets")
    assert run["with"]["output-sarif"] == "true"
    assert run["with"]["mode"] == (
        "${{ github.event_name == 'pull_request' && 'code-change' || 'batch' }}"
    )


def test_clusterfuzzlite_python_contract_exists():
    project = yaml.safe_load((ROOT / ".clusterfuzzlite" / "project.yaml").read_text())
    dockerfile = (ROOT / ".clusterfuzzlite" / "Dockerfile").read_text()
    build = (ROOT / ".clusterfuzzlite" / "build.sh").read_text()
    requirements = ROOT / ".clusterfuzzlite" / "requirements.lock"
    target = (ROOT / "fuzz" / "preflightops_fuzzer.py").read_text()
    assert project == {"language": "python"}
    assert re.search(r"base-builder-python@sha256:[0-9a-f]{64}", dockerfile)
    assert requirements.is_file()
    assert "--require-hashes" in build
    assert "requirements.lock" in build
    assert "pip3 install --no-cache-dir ." not in build
    assert "--hash=sha256:" in requirements.read_text(encoding="utf-8")
    assert "pyinstaller" in build
    assert "atheris.Setup" in target
    assert "validate_instance_url" in target
    assert "load_mapping" in target
    assert "validate_monitoring_evidence" in target


def test_enterprise_governance_artifacts_exist():
    required = [
        ROOT / ".github" / "CODEOWNERS",
        ROOT / ".github" / "dependabot.yml",
        ROOT / ".github" / "pull_request_template.md",
        ROOT / "docs" / "ENTERPRISE_GOVERNANCE.md",
        ROOT / "docs" / "THREAT_MODEL.md",
        ROOT / "docs" / "DATA_GOVERNANCE.md",
        ROOT / "docs" / "ENTERPRISE_DOD.md",
        ROOT / "docs" / "RELEASE_MANAGEMENT.md",
    ]
    assert all(path.is_file() and path.stat().st_size > 200 for path in required)


def test_cab_boundary_is_explicit_in_governance():
    text = (ROOT / "docs" / "ENTERPRISE_GOVERNANCE.md").read_text(encoding="utf-8")
    for prohibited in ("approval", "assignment", "scheduling", "state transitions", "closure"):
        assert prohibited in text

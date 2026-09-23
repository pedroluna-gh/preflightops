"""Installed-wheel smoke gates reject missing or misleading assessment outputs."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package_smoke", ROOT / "scripts/package_smoke.py")
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


@pytest.mark.parametrize("risk", ["LOW", "CRITICAL"])
def test_installed_assessment_contract(tmp_path, monkeypatch, risk):
    def run(command, *, cwd, capture_output, text, timeout):
        assert cwd != ROOT and cwd.parent == tmp_path
        assert capture_output and text and timeout == 60
        assert (cwd / "services.yaml").is_file()
        assert ("--terraform" in command) == (risk == "CRITICAL")
        for name in ("report.md", "report.html", "comment.md"):
            (cwd / name).write_text("report", encoding="utf-8")
        (cwd / "report.json").write_text(json.dumps({"risk_level": risk}), encoding="utf-8")
        return subprocess.CompletedProcess(command, int(risk == "CRITICAL"))

    monkeypatch.setattr(smoke.subprocess, "run", run)
    smoke._assessment_smoke(Path("installed-cli"), tmp_path, ROOT / "examples", risk)


@pytest.mark.parametrize("failure", ["exit", "risk", "missing", "empty"])
def test_installed_assessment_rejects_invalid_outputs(tmp_path, monkeypatch, failure):
    def run(command, **kwargs):
        cwd = kwargs["cwd"]
        for name in ("report.md", "report.html", "comment.md"):
            if failure != "missing":
                (cwd / name).write_text("" if failure == "empty" else "report", encoding="utf-8")
        (cwd / "report.json").write_text(
            json.dumps({"risk_level": "UNKNOWN" if failure == "risk" else "LOW"}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 2 if failure == "exit" else 0)

    monkeypatch.setattr(smoke.subprocess, "run", run)
    with pytest.raises(RuntimeError):
        smoke._assessment_smoke(Path("installed-cli"), tmp_path, ROOT / "examples", "LOW")

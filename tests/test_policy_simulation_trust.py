"""Regression: an active baseline must be authenticated during offline simulation."""

from __future__ import annotations

import json

import pytest
import yaml
from test_policy_governance import _bundle, _keys

from preflightops import cli
from preflightops.policy_governance import sign_governance_document


def _simulation(tmp_path, *, active_candidate=False):
    private, public = _keys()
    other_private, other_public = _keys()
    base = sign_governance_document(_bundle(), private, "baseline")
    candidate = _bundle()
    candidate["metadata"]["version"] = "2.1.0"
    if active_candidate:
        candidate = sign_governance_document(candidate, other_private, "candidate")
    documents = {
        "base": base,
        "candidate": candidate,
        "services": {"services": [{"name": "checkout", "owner": "sre", "criticality": "low"}]},
        "change": {"change": {"service": "checkout", "environment": "production"}},
    }
    args = ["policy", "simulate"]
    for name, document in documents.items():
        path = tmp_path / f"{name}.yaml"
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        args.extend([f"--{name}", str(path)])
    for name, value in (("base", public), ("candidate", other_public)):
        path = tmp_path / f"{name}.pem"
        path.write_text(value, encoding="utf-8")
        args.extend([f"--{name}-public-key", str(path)])
    args.extend(["--at", "2026-08-28T12:00:00Z", "--output", str(tmp_path / "result.json")])
    return args


@pytest.mark.parametrize("active_candidate", [False, True])
def test_simulation_active_baseline_and_independent_candidate_keys(tmp_path, active_candidate):
    args = _simulation(tmp_path, active_candidate=active_candidate)
    candidate_before = (tmp_path / "candidate.yaml").read_bytes()
    assert cli.main(args) == 0
    first = (tmp_path / "result.json").read_bytes()
    result = json.loads(first)
    assert result["evaluated_at"] == "2026-08-28T12:00:00Z"
    assert result["automatic_approval"] is False
    assert result["human_decision"] == "not_recorded"
    assert result["mode"] == "non_authoritative_simulation"
    assert cli.main(args) == 0
    assert (tmp_path / "result.json").read_bytes() == first
    assert (tmp_path / "candidate.yaml").read_bytes() == candidate_before


@pytest.mark.parametrize("side", ["base", "candidate"])
def test_simulation_wrong_key_fails_without_output(tmp_path, side):
    args = _simulation(tmp_path, active_candidate=True)
    opposite = "candidate" if side == "base" else "base"
    args[args.index(f"--{side}-public-key") + 1] = str(tmp_path / f"{opposite}.pem")
    assert cli.main(args) == 2
    assert not (tmp_path / "result.json").exists()


def test_simulation_missing_trust_fails_without_output(tmp_path, monkeypatch):
    args = _simulation(tmp_path)
    index = args.index("--base-public-key")
    del args[index : index + 2]
    monkeypatch.delenv("PREFLIGHTOPS_POLICY_PUBLIC_KEY", raising=False)
    assert cli.main(args) == 2
    assert not (tmp_path / "result.json").exists()


def test_simulation_invalid_explicit_time_fails_without_output(tmp_path):
    args = _simulation(tmp_path)
    args[args.index("--at") + 1] = "not-a-time"
    assert cli.main(args) == 2
    assert not (tmp_path / "result.json").exists()


def test_simulation_tampered_baseline_fails_without_output(tmp_path):
    args = _simulation(tmp_path)
    path = tmp_path / "base.yaml"
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    value["metadata"]["owner"] = "changed-owner"
    path.write_text(yaml.safe_dump(value), encoding="utf-8")
    assert cli.main(args) == 2
    assert not (tmp_path / "result.json").exists()

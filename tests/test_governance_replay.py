"""Governance replay, version immutability, closed shapes and CLI stop gates."""

import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
import yaml
from test_policy_governance import NOW, _bundle, _context, _keys, _waiver

from preflightops import cli
from preflightops.policy_governance import (
    policy_diff,
    resolve_policy_bundle,
    sign_governance_document,
    validate_policy_bundle,
    validate_waiver,
)


def test_changed_policy_requires_new_version_and_rollback_is_reproducible():
    original = _bundle()
    candidate = deepcopy(original)
    candidate["spec"]["base"]["risk_weights"]["production-change"] = 21
    before = validate_policy_bundle(original, for_assessment=False)
    after = validate_policy_bundle(candidate, for_assessment=False)
    with pytest.raises(ValueError, match="different version"):
        policy_diff(before, after, _context())
    candidate["metadata"]["version"] = "2.1.0"
    after = validate_policy_bundle(candidate, for_assessment=False)
    snapshot = resolve_policy_bundle(before, _context())
    assert policy_diff(before, after, _context())["automatic_approval"] is False
    assert resolve_policy_bundle(before, _context()) == snapshot
    assert original == _bundle()


@pytest.mark.parametrize("section", ["root", "metadata", "spec", "base", "monitoring"])
def test_unknown_policy_fields_rejected(section):
    value = _bundle()
    target = {
        "root": value,
        "metadata": value["metadata"],
        "spec": value["spec"],
        "base": value["spec"]["base"],
        "monitoring": value["spec"]["base"]["monitoring"],
    }[section]
    target["automatic_approval"] = True
    with pytest.raises(ValueError, match="unsupported or missing"):
        validate_policy_bundle(value, for_assessment=False)


@pytest.mark.parametrize("change_class", ["normal", "standard", "emergency"])
def test_every_change_class_preserves_base_and_mandatory_controls(change_class):
    bundle = validate_policy_bundle(_bundle(), for_assessment=False)
    resolved = resolve_policy_bundle(bundle, {**_context(), "change_class": change_class})
    assert resolved["risk_weights"]["missing-rollback-plan"] >= 40
    assert resolved["context"]["change_class"] == change_class


def test_waiver_exact_expiry_boundary_and_historical_replay():
    private, public = _keys()
    document = _waiver("sha256:" + "a" * 64)
    signed = sign_governance_document(document, private, "waiver")
    kwargs = {
        "public_key": public,
        "policy_digest": document["scope"]["policy_digest"],
        "context": {"service": "checkout", **_context()},
    }
    first = validate_waiver(signed, at=NOW, **kwargs)
    with pytest.raises(ValueError, match="expired"):
        validate_waiver(signed, at=datetime(2026, 8, 29, 10, tzinfo=UTC), **kwargs)
    assert validate_waiver(signed, at=NOW, **kwargs) == first


@pytest.mark.parametrize("mode,expected", [("closed", 2), ("open", 1)])
def test_cli_writes_evidence_before_closed_gate_and_replays_identically(tmp_path, mode, expected):
    private, public = _keys()
    document = _bundle()
    document["metadata"]["expires_at"] = "2026-09-01T00:00:00Z"
    document["spec"]["failure_modes"]["evidence_unavailable"] = mode
    files = {
        "policy": sign_governance_document(document, private, "policy"),
        "services": {"services": [{"name": "checkout"}]},
        "change": {"change": {"service": "checkout", "environment": "production"}},
    }
    args = []
    for name, value in files.items():
        path = tmp_path / f"{name}.yaml"
        path.write_text(yaml.safe_dump(value), encoding="utf-8")
        args.extend([f"--{name}", str(path)])
    key = tmp_path / "public.pem"
    key.write_text(public, encoding="utf-8")
    output = tmp_path / "report.json"
    args.extend(
        [
            "--policy-public-key",
            str(key),
            "--governance-at",
            "2026-08-28T12:00:00Z",
            "--json-output",
            str(output),
            "--output",
            str(tmp_path / "report.md"),
        ]
    )
    assert cli.main(args) == expected
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["decision_record"]["evaluated_at"] == "2026-08-28T12:00:00Z"
    assert result["decision_record"]["failure_handling"]["blocking"] is (mode == "closed")
    assert result["decision_record"]["automatic_approval"] is False
    first = output.read_bytes()
    assert cli.main(args) == expected
    assert output.read_bytes() == first


def test_historical_time_cannot_be_used_for_live_integration(tmp_path, capsys):
    assert (
        cli.main(
            [
                "--services",
                "absent",
                "--change",
                "absent",
                "--governance-at",
                "2026-08-28T12:00:00Z",
                "--jira",
                "https://example.test",
            ]
        )
        == 2
    )
    assert "Historical governance replay" in capsys.readouterr().err

"""Enterprise policy hierarchy, signature, waiver, and decision-boundary tests."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from preflightops import cli
from preflightops.policy_governance import (
    apply_verified_waivers,
    load_governance_document,
    policy_diff,
    read_governance_key,
    resolve_policy_bundle,
    sign_governance_document,
    validate_policy_bundle,
    validate_waiver,
)

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _keys() -> tuple[str, str]:
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _bundle() -> dict:
    return {
        "api_version": "preflightops.dev/policy/v2",
        "kind": "PolicyBundle",
        "metadata": {
            "name": "enterprise-core",
            "version": "2.0.0",
            "owner": "change-governance",
            "effective_from": "2026-01-01T00:00:00Z",
            "status": "draft",
        },
        "spec": {
            "failure_modes": {
                "policy_validation": "closed",
                "signature": "closed",
                "context_conflict": "closed",
                "evidence_unavailable": "closed",
            },
            "mandatory_controls": ["missing-rollback-plan"],
            "base": {
                "risk_weights": {"missing-rollback-plan": 40, "production-change": 20},
                "risk_level_thresholds": {"low": 30, "medium": 60, "high": 80},
                "monitoring": {"minimum_enabled_monitors": 1, "required_providers": []},
            },
            "overlays": [
                {
                    "id": "production",
                    "priority": 10,
                    "match": {"environment": "production"},
                    "apply": {"risk_weights": {"production-change": 35}},
                },
                {
                    "id": "tier-zero-normal",
                    "priority": 20,
                    "match": {"tier": ["critical", "tier-0"], "change_class": "normal"},
                    "apply": {
                        "risk_weights": {"missing-rollback-plan": 55},
                        "monitoring": {
                            "minimum_enabled_monitors": 2,
                            "required_providers": ["zabbix"],
                        },
                    },
                },
            ],
        },
    }


def _context() -> dict[str, str]:
    return {
        "environment": "production",
        "tier": "critical",
        "change_class": "normal",
        "change_type": "deployment",
    }


def _signed_bundle() -> tuple[dict, str, str]:
    private, public = _keys()
    return sign_governance_document(_bundle(), private, "policy-key-2026-01"), private, public


def _waiver(policy_digest: str) -> dict:
    return {
        "api_version": "preflightops.dev/waiver/v1",
        "kind": "Waiver",
        "metadata": {
            "id": "WV-2026-0042",
            "issued_at": "2026-08-28T10:00:00Z",
            "expires_at": "2026-08-29T10:00:00Z",
        },
        "scope": {
            "policy_digest": policy_digest,
            "rules": ["missing-rollback-plan"],
            "service": "checkout",
            "environment": "production",
            "change_class": "normal",
            "change_type": "deployment",
        },
        "requester": "deployment-owner@example.com",
        "approver": "independent-risk@example.com",
        "reason_code": "TIME_BOUND_OPERATIONAL_EXCEPTION",
        "justification": "External dependency prevents the normal rollback path for this window.",
        "evidence_references": ["CHG0012345", "https://evidence.example.test/run/42"],
        "compensating_controls": ["Named incident commander and five-minute error-rate abort."],
    }


def test_signed_active_policy_resolves_hierarchy_and_lineage():
    signed, _, public = _signed_bundle()
    bundle = validate_policy_bundle(signed, public_key=public, at=NOW)
    resolved = resolve_policy_bundle(bundle, _context())
    assert resolved["risk_weights"]["production-change"] == 35
    assert resolved["risk_weights"]["missing-rollback-plan"] == 55
    assert resolved["monitoring"]["required_providers"] == ["zabbix"]
    assert resolved["lineage"] == ["base", "production", "tier-zero-normal"]
    assert resolved["verified_key_id"] == "policy-key-2026-01"
    assert resolved["digest"].startswith("sha256:")


def test_active_policy_tamper_and_unsigned_assessment_fail_closed():
    signed, _, public = _signed_bundle()
    signed["spec"]["base"]["risk_weights"]["production-change"] = 1
    with pytest.raises(ValueError, match="signature verification failed"):
        validate_policy_bundle(signed, public_key=public, at=NOW)
    with pytest.raises(ValueError, match="Only an active"):
        validate_policy_bundle(_bundle(), at=NOW)


def test_mandatory_control_cannot_be_weakened():
    bundle = _bundle()
    bundle["spec"]["overlays"][0]["apply"]["risk_weights"] = {"missing-rollback-plan": 10}
    with pytest.raises(ValueError, match="weakens mandatory control"):
        validate_policy_bundle(bundle, for_assessment=False)


def test_same_priority_conflict_is_rejected_deterministically():
    bundle = _bundle()
    bundle["spec"]["overlays"].append(
        {
            "id": "production-conflict",
            "priority": 10,
            "match": {"environment": "production"},
            "apply": {"risk_weights": {"production-change": 60}},
        }
    )
    validated = validate_policy_bundle(bundle, for_assessment=False)
    with pytest.raises(ValueError, match="context conflict"):
        resolve_policy_bundle(validated, _context())


def test_policy_diff_flags_weakening_without_activating_candidate():
    base = validate_policy_bundle(_bundle(), for_assessment=False)
    candidate_doc = _bundle()
    candidate_doc["metadata"]["version"] = "2.1.0"
    candidate_doc["spec"]["base"]["risk_weights"]["production-change"] = 10
    candidate_doc["spec"]["overlays"][0]["apply"]["risk_weights"]["production-change"] = 15
    candidate_doc["spec"]["mandatory_controls"] = []
    candidate_doc["spec"]["failure_modes"]["evidence_unavailable"] = "open"
    candidate_doc["spec"]["overlays"][1]["apply"]["monitoring"] = {
        "minimum_enabled_monitors": 1,
        "required_providers": [],
    }
    candidate = validate_policy_bundle(candidate_doc, for_assessment=False)
    result = policy_diff(base, candidate, _context())
    assert result["weakening"] is True
    assert any(change["direction"] == "weakened" for change in result["changes"])
    fields = {change["field"] for change in result["changes"]}
    assert "mandatory_controls.missing-rollback-plan" in fields
    assert "monitoring.required_providers.zabbix" in fields
    assert "failure_modes.evidence_unavailable" in fields


def test_verified_waiver_is_scoped_expiring_and_never_approves():
    signed_policy, _, policy_public = _signed_bundle()
    policy = validate_policy_bundle(signed_policy, public_key=policy_public, at=NOW)
    waiver_private, waiver_public = _keys()
    signed_waiver = sign_governance_document(
        _waiver(policy["digest"]), waiver_private, "waiver-key-2026-01"
    )
    verified = validate_waiver(
        signed_waiver,
        public_key=waiver_public,
        policy_digest=policy["digest"],
        context={"service": "checkout", **_context()},
        at=NOW,
    )
    result = apply_verified_waivers(
        {
            "risk_score": 90,
            "risk_level": "CRITICAL",
            "recommendation": "Review required.",
            "triggered_rules": [{"id": "missing-rollback-plan", "score": 55}],
        },
        [verified],
    )
    assert result["risk_score"] == 90
    assert result["triggered_rules"][0]["waiver_status"] == "verified_exception_recorded"
    assert result["verified_waivers"][0]["evidence_references"] == [
        "CHG0012345",
        "https://evidence.example.test/run/42",
    ]
    assert result["decision_record"]["automatic_approval"] is False
    assert result["decision_record"]["human_decision"]["status"] == "not_recorded"


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda waiver: waiver.update(approver=waiver["requester"]), "must be different"),
        (
            lambda waiver: waiver["scope"].update(policy_digest="sha256:" + "0" * 64),
            "does not match",
        ),
        (lambda waiver: waiver["metadata"].update(expires_at="2026-08-28T11:00:00Z"), "expired"),
    ],
)
def test_invalid_waiver_fails_closed(mutation, match):
    signed_policy, _, policy_public = _signed_bundle()
    policy = validate_policy_bundle(signed_policy, public_key=policy_public, at=NOW)
    private, public = _keys()
    waiver = _waiver(policy["digest"])
    mutation(waiver)
    signed = sign_governance_document(waiver, private, "waiver-key")
    with pytest.raises(ValueError, match=match):
        validate_waiver(
            signed,
            public_key=public,
            policy_digest=policy["digest"],
            context={"service": "checkout", **_context()},
            at=NOW,
        )


def test_policy_simulation_is_non_authoritative(tmp_path):
    base = _bundle()
    candidate = deepcopy(base)
    candidate["metadata"]["version"] = "2.1.0"
    candidate["spec"]["base"]["risk_weights"]["production-change"] = 50
    candidate["spec"]["overlays"][0]["apply"]["risk_weights"]["production-change"] = 60
    services = {
        "services": [
            {
                "name": "checkout",
                "owner": "sre",
                "criticality": "low",
                "runbook": "https://runbook.example.test/checkout",
                "business_impact": "Checkout unavailable.",
            }
        ]
    }
    change = {
        "change": {
            "service": "checkout",
            "environment": "production",
            "change_type": "deployment",
            "change_class": "normal",
            "rollback_plan": "Redeploy the previous image within ten minutes.",
            "monitoring_plan": {"dashboards": ["https://grafana.example.test/d/checkout"]},
            "validation_plan": ["Run smoke tests"],
        }
    }
    paths = {}
    for name, value in (
        ("base", base),
        ("candidate", candidate),
        ("services", services),
        ("change", change),
    ):
        path = tmp_path / f"{name}.yaml"
        path.write_text(yaml.safe_dump(value), encoding="utf-8")
        paths[name] = path
    output = tmp_path / "simulation.json"
    code = cli.main(
        [
            "policy",
            "simulate",
            "--base",
            str(paths["base"]),
            "--candidate",
            str(paths["candidate"]),
            "--services",
            str(paths["services"]),
            "--change",
            str(paths["change"]),
            "--output",
            str(output),
        ]
    )
    assert code == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["mode"] == "non_authoritative_simulation"
    assert result["automatic_approval"] is False
    assert result["human_decision"] == "not_recorded"


def test_policy_cli_sign_lint_and_diff_lifecycle(tmp_path, monkeypatch, capsys):
    private, public = _keys()
    draft = tmp_path / "draft.yaml"
    active = tmp_path / "active.yaml"
    public_path = tmp_path / "policy.pub.pem"
    context = tmp_path / "context.yaml"
    diff_output = tmp_path / "diff.json"
    draft.write_text(yaml.safe_dump(_bundle()), encoding="utf-8")
    public_path.write_text(public, encoding="utf-8")
    context.write_text(yaml.safe_dump(_context()), encoding="utf-8")
    monkeypatch.setenv("PREFLIGHTOPS_POLICY_PRIVATE_KEY", private)

    assert cli.main(["policy", "lint", "--policy", str(draft), "--draft"]) == 0
    assert (
        cli.main(
            [
                "policy",
                "sign",
                "--policy",
                str(draft),
                "--output",
                str(active),
                "--key-id",
                "policy-key-lifecycle",
            ]
        )
        == 0
    )
    assert (
        cli.main(["policy", "lint", "--policy", str(active), "--public-key", str(public_path)]) == 0
    )
    assert (
        cli.main(
            [
                "policy",
                "diff",
                "--base",
                str(active),
                "--candidate",
                str(draft),
                "--context",
                str(context),
                "--base-public-key",
                str(public_path),
                "--output",
                str(diff_output),
            ]
        )
        == 0
    )
    assert json.loads(diff_output.read_text(encoding="utf-8"))["changes"] == []
    assert "status" in capsys.readouterr().out


def test_waiver_cli_sign_and_verify_lifecycle(tmp_path, monkeypatch, capsys):
    policy_private, policy_public = _keys()
    signed_policy = sign_governance_document(_bundle(), policy_private, "policy-key")
    policy = validate_policy_bundle(signed_policy, public_key=policy_public, at=NOW)
    waiver_private, waiver_public = _keys()
    draft_value = _waiver(policy["digest"])
    draft_value["metadata"] = {
        "id": "WV-LIFECYCLE",
        "issued_at": "2020-01-01T00:00:00Z",
        "expires_at": "2035-01-01T00:00:00Z",
    }
    draft = tmp_path / "waiver-draft.yaml"
    signed = tmp_path / "waiver-signed.yaml"
    public_path = tmp_path / "waiver.pub.pem"
    context = tmp_path / "context.yaml"
    draft.write_text(yaml.safe_dump(draft_value), encoding="utf-8")
    public_path.write_text(waiver_public, encoding="utf-8")
    context.write_text(yaml.safe_dump({"service": "checkout", **_context()}), encoding="utf-8")
    monkeypatch.setenv("PREFLIGHTOPS_WAIVER_PRIVATE_KEY", waiver_private)

    assert (
        cli.main(
            [
                "waiver",
                "sign",
                "--waiver",
                str(draft),
                "--output",
                str(signed),
                "--key-id",
                "waiver-key-lifecycle",
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "waiver",
                "verify",
                "--waiver",
                str(signed),
                "--public-key",
                str(public_path),
                "--policy-digest",
                policy["digest"],
                "--context",
                str(context),
            ]
        )
        == 0
    )
    assert '"status": "verified"' in capsys.readouterr().out


def test_governance_load_and_key_failures_are_bounded(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="does not exist"):
        load_governance_document(tmp_path / "missing.yaml")
    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a YAML/JSON mapping"):
        load_governance_document(scalar)
    oversized = tmp_path / "oversized.yaml"
    oversized.write_text("x" * (1024 * 1024 + 1), encoding="utf-8")
    with pytest.raises(ValueError, match="1 MiB"):
        load_governance_document(oversized)
    monkeypatch.delenv("MISSING_GOVERNANCE_KEY", raising=False)
    with pytest.raises(ValueError, match="A key is required"):
        read_governance_key(None, "MISSING_GOVERNANCE_KEY")


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda value: value.update(api_version="wrong"), "must use"),
        (lambda value: value.update(metadata=[]), "metadata and spec"),
        (lambda value: value["metadata"].update(owner=""), "metadata.owner"),
        (lambda value: value["metadata"].update(status="unknown"), "status must"),
        (lambda value: value["metadata"].update(effective_from="not-a-time"), "RFC 3339"),
        (lambda value: value["metadata"].update(effective_from="2026-01-01T00:00:00"), "timezone"),
        (lambda value: value["spec"].update(failure_modes=[]), "failure_modes is required"),
        (lambda value: value["spec"]["failure_modes"].update(signature="open"), "must fail closed"),
        (lambda value: value["spec"].update(base=[]), "spec.base"),
        (
            lambda value: value["spec"].update(mandatory_controls=["unknown"]),
            "require base weights",
        ),
        (lambda value: value["spec"].update(overlays={}), "overlays must be a list"),
        (lambda value: value["spec"]["overlays"].append("bad"), "overlay must be a mapping"),
        (lambda value: value["spec"]["overlays"][0].update(priority=True), "priority must"),
        (lambda value: value["spec"]["overlays"][0].update(match={}), "invalid or empty"),
        (lambda value: value["spec"]["overlays"][0].update(apply={}), "requires apply"),
        (
            lambda value: value["spec"]["overlays"][0]["apply"].update(unknown={}),
            "unsupported apply",
        ),
    ],
)
def test_policy_bundle_invalid_structures_fail_closed(mutation, match):
    value = _bundle()
    mutation(value)
    with pytest.raises(ValueError, match=match):
        validate_policy_bundle(value, for_assessment=False)


def test_cli_errors_are_machine_safe(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("[]\n", encoding="utf-8")
    assert cli.main(["policy", "lint", "--policy", str(bad), "--draft"]) == 2
    assert "Policy governance error" in capsys.readouterr().err
    assert (
        cli.main(
            [
                "waiver",
                "verify",
                "--waiver",
                str(bad),
                "--policy-digest",
                "sha256:" + "0" * 64,
                "--context",
                str(bad),
            ]
        )
        == 2
    )
    assert "Waiver governance error" in capsys.readouterr().err

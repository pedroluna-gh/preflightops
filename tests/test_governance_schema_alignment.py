"""Runtime enforces the public closed shapes plus semantic constraints."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from test_policy_governance import NOW, _bundle, _context, _keys, _waiver

from preflightops.policy_governance import (
    governance_digest,
    governance_time,
    load_governance_document,
    sign_governance_document,
    validate_policy_bundle,
    validate_waiver,
)

ROOT = Path(__file__).parents[1]


def _schema(name):
    return Draft202012Validator(
        json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    )


def test_shipped_v2_policy_is_valid_in_schema_and_runtime():
    document = load_governance_document(ROOT / "policy-packs/enterprise-example-v2.yaml")
    _schema("policy-bundle-v2.schema.json").validate(document)
    assert validate_policy_bundle(document, for_assessment=False)["digest"] == governance_digest(
        document
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["spec"].update(mandatory_controls=["missing-rollback-plan"] * 2),
        lambda d: d["spec"]["overlays"][0]["match"].update(environment=["production"] * 2),
        lambda d: d["spec"]["base"]["monitoring"].update(required_providers=["zabbix"] * 2),
        lambda d: d["metadata"].update(expires_at=None),
        lambda d: d["metadata"].pop("status"),
    ],
)
def test_schema_invalid_policy_also_fails_runtime(mutation):
    document = _bundle()
    mutation(document)
    assert list(_schema("policy-bundle-v2.schema.json").iter_errors(document))
    with pytest.raises(ValueError):
        validate_policy_bundle(document, for_assessment=False)


def test_invalid_digest_cannot_be_self_matched_by_waiver_caller():
    private, public = _keys()
    signed = sign_governance_document(_waiver("invalid"), private, "waiver")
    assert list(_schema("waiver-contract-v1.schema.json").iter_errors(signed))
    with pytest.raises(ValueError, match="SHA-256"):
        validate_waiver(
            signed,
            public_key=public,
            policy_digest="invalid",
            context={"service": "checkout", **_context()},
            at=NOW,
        )


def test_signed_waiver_roundtrip_both_validators():
    private, public = _keys()
    digest = "sha256:" + "a" * 64
    signed = sign_governance_document(_waiver(digest), private, "waiver")
    _schema("waiver-contract-v1.schema.json").validate(signed)
    assert (
        validate_waiver(
            signed,
            public_key=public,
            policy_digest=digest,
            context={"service": "checkout", **_context()},
            at=NOW,
        )["status"]
        == "verified"
    )


@pytest.mark.parametrize(
    "value",
    ["2026-01-01T00:00Z", "20260101T000000Z", "2026-W01-1T00:00:00Z", "2026-01-01 00:00+00:00"],
)
def test_non_rfc3339_time_is_rejected(value):
    with pytest.raises(ValueError, match="RFC 3339"):
        governance_time(value)


def test_lowercase_rfc3339_normalizes_to_utc():
    assert governance_time("2026-08-28t12:00:00z") == NOW


def test_deep_direct_api_input_rejected_before_copying():
    document = {}
    child = document
    for _ in range(1000):
        child["child"] = {}
        child = child["child"]
    with pytest.raises(ValueError, match="structural limits"):
        governance_digest(document)

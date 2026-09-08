"""Contract invariants independent of any external provider SDK."""

import json
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from preflightops.provider_contract import (
    ProviderContractError,
    ProviderEvidence,
    parse_provider_evidence,
)


def test_strict_decoder_and_public_schema_roundtrip():
    value = asdict(observation())
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/provider-evidence-v1.schema.json").read_text()
    )
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(value)
    assert parse_provider_evidence(value).canonical_bytes() == observation().canonical_bytes()
    with pytest.raises(ProviderContractError):
        parse_provider_evidence({**value, "credentials": "forbidden"})
    for field in value:
        incomplete = dict(value)
        del incomplete[field]
        assert not validator.is_valid(incomplete)
        with pytest.raises(ProviderContractError):
            parse_provider_evidence(incomplete)


@pytest.mark.parametrize(
    "field", ["status", "sensitivity", "error_code", "redaction", "schema_version"]
)
def test_non_scalar_discriminators_fail_with_static_contract_error(field):
    with pytest.raises(ProviderContractError):
        observation(**{field: []})


def observation(**overrides):
    return ProviderEvidence(
        **{
            "provider": "fake",
            "provider_version": "1.0.0",
            "control_id": "monitoring",
            "status": "PASS",
            "summary": "Approved monitoring evidence available.",
            "source_reference": "monitor-42",
            "collected_at": "2026-09-08T12:00:00Z",
            "valid_until": "2026-09-08T13:00:00Z",
            "confidence": 90,
            **overrides,
        }
    )


def test_reproducible_immutable_observation():
    left = observation()
    assert left.canonical_bytes() == observation().canonical_bytes()
    assert left.digest == observation().digest
    assert left.digest != replace(left, confidence=89).digest
    with pytest.raises(FrozenInstanceError):
        left.confidence = 100


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        ("2026-09-08T11:59:59Z", "UNKNOWN"),
        ("2026-09-08T12:00:00Z", "PASS"),
        ("2026-09-08T12:59:59Z", "PASS"),
        ("2026-09-08T13:00:00Z", "UNKNOWN"),
    ],
)
def test_freshness_boundaries(instant, expected):
    assert observation().effective_status(instant) == expected


@pytest.mark.parametrize("status", ["ERROR", "UNKNOWN"])
def test_uncertainty_cannot_be_promoted(status):
    item = observation(status=status, error_code="UNAVAILABLE", confidence=0)
    assert item.effective_status("2026-09-08T12:30:00Z") == status
    with pytest.raises(ProviderContractError):
        replace(item, confidence=1)


@pytest.mark.parametrize(
    "overrides",
    [
        {"confidence": True},
        {"confidence": 101},
        {"status": "APPROVED"},
        {"schema_version": "2.0"},
        {"source_reference": "https://example.test/?token=value"},
        {"summary": "token=private-value"},
        {"summary": "x" * 513},
        {"valid_until": "2026-09-08T12:00:00Z"},
        {"collected_at": "2026-09-08T12:00:00+00:00"},
        {"redaction": "raw"},
        {"status": "NOT_APPLICABLE", "confidence": 0},
        {"error_code": "TIMEOUT"},
    ],
)
def test_rejects_invalid_or_sensitive_contract_without_echo(overrides):
    with pytest.raises(ProviderContractError) as exc:
        observation(**overrides)
    assert "private-value" not in str(exc.value)


def test_not_applicable_requires_reason_and_remains_distinct():
    item = observation(
        status="NOT_APPLICABLE",
        confidence=0,
        not_applicable_reason="Control excluded by reviewed applicability rule.",
    )
    assert item.effective_status("2026-09-08T12:30:00Z") == "NOT_APPLICABLE"

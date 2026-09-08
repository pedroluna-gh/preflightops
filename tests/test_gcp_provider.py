"""GCP provider lifecycle, public contract and deterministic offline evidence."""

import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from test_gcp_client import SyntheticCredentials, Transport, config, context
from test_gcp_observations import POLICY, policy, series
from test_gcp_pagination import ASSET, INSTANT, METRIC, response

from preflightops.gcp_client import GcpResponse
from preflightops.gcp_provider import GcpProvider
from preflightops.provider_contract import ProviderContractError, parse_provider_evidence
from preflightops.provider_runtime import ProviderRequest, ProviderRunner

PROJECT = {"name": "projects/123456", "projectId": "sample-project", "state": "ACTIVE"}


def request(provider, **changes):
    return replace(
        ProviderRequest("a" * 64, provider.config.digest, provider.capabilities.controls, INSTANT),
        **changes,
    )


def run(cfg, *responses):
    transport = Transport(*responses)
    provider = GcpProvider(cfg, transport=transport)
    result = ProviderRunner(cache_capacity=0).run(
        provider, request(provider), credentials=SyntheticCredentials
    )
    assert transport.closed
    return result


def test_all_capabilities_public_contract_reproducible_without_raw_data():
    cfg = config(resources=(POLICY,), metrics=(METRIC,), assets=(ASSET,))

    def execute():
        # Sorted control identifiers: asset, identity, metric, policy.
        return run(
            cfg,
            response(PROJECT),
            response(
                {
                    "readTime": INSTANT,
                    "assets": [{"name": ASSET.name, "assetType": ASSET.asset_type}],
                }
            ),
            response({"timeSeries": [series()]}),
            response(policy()),
        )

    left, right = execute(), execute()
    assert left == right
    validator = Draft202012Validator(
        json.loads(
            (Path(__file__).parents[1] / "schemas/provider-evidence-v1.schema.json").read_text()
        ),
        format_checker=FormatChecker(),
    )
    for item in left:
        validator.validate(asdict(item))
        assert parse_provider_evidence(asdict(item)).canonical_bytes() == item.canonical_bytes()
        assert item.source_reference == "project-1.principal-1"
        assert b"sample-project" not in item.canonical_bytes()
        assert b"googleapis" not in item.canonical_bytes()
        if item.control_id.endswith(".identity"):
            assert item.status == "UNKNOWN" and item.confidence == 0
        else:
            assert item.status == "PASS"


@pytest.mark.parametrize(
    "status,expected", [(403, "AUTH"), (404, "MISSING"), (429, "RATE_LIMIT"), (503, "UNAVAILABLE")]
)
def test_project_failure_prevents_other_reads(status, expected):
    evidence = run(config(resources=(POLICY,)), GcpResponse(status, b"private failure"))
    assert all(
        e.status != "PASS" and e.confidence == 0 and e.error_code == expected for e in evidence
    )


def test_cross_project_payload_invalidates_controls():
    evidence = run(
        config(resources=(POLICY,)), response({**PROJECT, "projectId": "outside-project"})
    )
    assert all(e.error_code == "INVALID_RESPONSE" for e in evidence)


def test_disabled_policy_fails_independently_of_unknown_identity():
    evidence = run(config(resources=(POLICY,)), response(PROJECT), response(policy(enabled=False)))
    assert [(e.status, e.error_code) for e in evidence] == [
        ("UNKNOWN", "UNAVAILABLE"),
        ("FAIL", None),
    ]


def test_metric_expiry_is_not_extended_to_provider_ttl():
    evidence = run(
        config(metrics=(METRIC,)),
        response(PROJECT),
        response({"timeSeries": [series("2026-09-08T11:55:01Z")]}),
    )
    metric = next(e for e in evidence if e.control_id.endswith("metric-1"))
    assert metric.valid_until == "2026-09-08T12:00:01Z"
    assert metric.effective_status("2026-09-08T12:00:01Z") == "UNKNOWN"


def test_configuration_mismatch_precedes_credentials():
    provider = GcpProvider(config(), transport=Transport())
    ctx = replace(context(), credential_supplier=lambda: pytest.fail("Credentials forbidden"))
    with pytest.raises(ProviderContractError):
        provider.open(request(provider, configuration_digest="b" * 64), ctx)


def test_single_credential_binding_and_no_repeat_collection():
    provider = GcpProvider(
        config(resources=(POLICY,)), transport=Transport(response(PROJECT), response(policy()))
    )
    calls = []

    def credentials():
        calls.append(1)
        return SyntheticCredentials()

    ctx = replace(context(), credential_supplier=credentials)
    req = request(provider)
    provider.open(req, ctx)
    assert len(tuple(provider.collect(req, ctx))) == 2
    assert len(calls) == 1
    with pytest.raises(ProviderContractError):
        tuple(provider.collect(req, ctx))
    provider.close()
    assert provider._context is None


def test_closed_lifecycle_and_midstream_timeout_cannot_pass():
    provider = GcpProvider(config(), transport=Transport())
    with pytest.raises(ProviderContractError):
        tuple(provider.collect(request(provider), context()))
    evidence = run(config(resources=(POLICY,)), response(PROJECT), TimeoutError("private"))
    assert all(e.status == "ERROR" and e.error_code == "TIMEOUT" for e in evidence)

"""Offline unit, contract and adversarial tests for ServiceNow adapter v2."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import urllib.error
from collections.abc import Callable, Mapping
from pathlib import Path

import jsonschema
import pytest
import yaml
from referencing import Registry, Resource

import preflightops.servicenow_enterprise as enterprise
from preflightops.servicenow import prepare_payload
from preflightops.servicenow_enterprise import (
    HttpRequest,
    HttpResponse,
    NetworkPolicy,
    OAuthClientCredentialsProvider,
    RetryPolicy,
    ServiceNowEnterpriseAdapter,
    ServiceNowPlanV2,
    ServiceNowV2Error,
    UrllibTransport,
    build_servicenow_plan_v2,
    compare_servicenow_previews_v1_v2,
    load_servicenow_mapping_v2,
    system_resolver,
    validate_servicenow_plan_v2,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
REPORT_PATH = ROOT / "tests" / "fixtures" / "reports" / "assessment-report-v1.golden.json"
MAPPING_PATH = ROOT / "examples" / "servicenow-enterprise-mapping-v2.yaml"
CAPABILITY_DIGEST = "9" * 64
INSTANCE_HOST = "dev00000.service-now.com"
INSTANCE_ORIGIN = f"https://{INSTANCE_HOST}"
TARGET = {
    "number": "CHG0000001",
    "sys_id": "1" * 32,
    "sys_mod_count": 7,
}
FIXED_TIME = dt.datetime(2026, 9, 3, 18, 0, tzinfo=dt.UTC)


def _report() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def _mapping(*, create_draft: bool = False) -> dict:
    value = yaml.safe_load(MAPPING_PATH.read_text(encoding="utf-8"))
    value["operations"]["create_draft"] = create_draft
    return value


def _policy(
    *,
    resolver: Callable[[str], tuple[str, ...]] | None = lambda _host: ("93.184.216.34",),
) -> NetworkPolicy:
    return NetworkPolicy(
        allowed_instance_hosts=(INSTANCE_HOST,),
        allowed_evidence_hosts=("artifacts.example.test",),
        resolver=resolver,
    )


def _plan(
    *,
    dry_run: bool = True,
    write_enabled: bool = False,
    operation: str = "enrich_existing",
    create_draft: bool = False,
    feature: bool = False,
    evidence_mode: str = "attachment",
    evidence_url: str | None = None,
    expected_sys_mod_count: int = 7,
    target_number: str | None = "CHG0000001",
    target_sys_id: str | None = None,
) -> ServiceNowPlanV2:
    kwargs = {
        "instance_alias": "enterprise-sandbox",
        "instance_origin": INSTANCE_ORIGIN,
        "network_policy": _policy(),
        "operation": operation,
        "capability_attestation_sha256": CAPABILITY_DIGEST,
        "dry_run": dry_run,
        "write_enabled": write_enabled,
        "evidence_mode": evidence_mode,
        "evidence_url": evidence_url,
        "draft_feature_enabled": feature,
    }
    if operation == "enrich_existing":
        kwargs.update(
            {
                "target_number": target_number,
                "target_sys_id": target_sys_id,
                "expected_sys_mod_count": expected_sys_mod_count,
            }
        )
    else:
        kwargs.update(
            {
                "model_sys_id": "1" * 32,
                "external_authorization_id": "POLICY-DRAFT-TEST-01",
            }
        )
    return build_servicenow_plan_v2(_report(), _mapping(create_draft=create_draft), **kwargs)


def _response(status: int, value: Mapping | list, headers: Mapping[str, str] | None = None):
    return HttpResponse(status, dict(headers or {}), json.dumps(value).encode())


def _capability(plan: ServiceNowPlanV2, *, operations: list[str] | None = None) -> dict:
    return {
        "result": {
            "attestation_sha256": CAPABILITY_DIGEST,
            "mapping_sha256": plan.request["delivery"]["mapping_sha256"],
            "server_compare_and_set": True,
            "unique_delivery": True,
            "delivery_field": "u_preflightops_delivery_id",
            "allowed_operations": operations or [plan.request["operation"]],
            "allowed_model_sys_ids": ["1" * 32]
            if plan.request["operation"] == "create_draft"
            else [],
        }
    }


def _remote(
    plan: ServiceNowPlanV2,
    *,
    outcome: str = "UPDATED",
    target: Mapping | None = None,
) -> dict:
    return {
        "result": {
            "outcome": outcome,
            "target": dict(target or {**TARGET, "sys_mod_count": 8}),
            "idempotency_key": plan.request["delivery"]["idempotency_key"],
            "payload_sha256": plan.request["delivery"]["payload_sha256"],
            "mapping_sha256": plan.request["delivery"]["mapping_sha256"],
            "assessment_id": plan.request["assessment"]["assessment_id"],
            "mapped_fields": dict(plan.mapped_fields),
            "evidence_sha256": plan.evidence["sha256"],
        }
    }


class FakeCredential:
    def __init__(self, value: str = "Bearer test-canary-token") -> None:
        self.value = value
        self.calls = 0

    def authorization_header(self, instance_origin: str) -> str:
        assert instance_origin == INSTANCE_ORIGIN
        self.calls += 1
        return self.value


class RecordingTransport:
    def __init__(self, handler: Callable[[HttpRequest], HttpResponse]) -> None:
        self.handler = handler
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return self.handler(request)


def _successful_transport(
    plan: ServiceNowPlanV2,
    *,
    lookup: Mapping | None = None,
    outcome: str = "UPDATED",
    post: Callable[[HttpRequest], HttpResponse] | None = None,
    reconcile: Callable[[HttpRequest], HttpResponse] | None = None,
) -> RecordingTransport:
    change = dict(lookup or TARGET)

    def handler(request: HttpRequest) -> HttpResponse:
        if "/api/sn_chg_rest/v1/change" in request.url:
            return _response(200, {"result": change})
        if "/api/x_preflightops/v1/capabilities/" in request.url:
            return _response(200, _capability(plan))
        if request.method == "POST" and request.url.endswith("/api/x_preflightops/v1/evidence"):
            if post is not None:
                return post(request)
            return _response(201, _remote(plan, outcome=outcome))
        if request.method == "GET" and "/api/x_preflightops/v1/evidence/snv2-" in request.url:
            if reconcile is not None:
                return reconcile(request)
            return _response(200, _remote(plan, outcome=outcome))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    return RecordingTransport(handler)


def _adapter(
    transport: RecordingTransport | None,
    credential: FakeCredential | None,
    *,
    retry: RetryPolicy | None = None,
    feature: bool = False,
    sleep: Callable[[float], None] | None = None,
    events: list | None = None,
) -> ServiceNowEnterpriseAdapter:
    return ServiceNowEnterpriseAdapter(
        network_policy=_policy(),
        transport=transport,
        credential_provider=credential,
        retry_policy=retry,
        draft_feature_enabled=feature,
        clock=lambda: FIXED_TIME,
        monotonic=lambda: 0.0,
        sleep=sleep,
        event_sink=None if events is None else events.append,
    )


def _validate_with_registry(instance: Mapping, schema_name: str) -> None:
    registry = Registry()
    for path in SCHEMAS.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(
        schema,
        registry=registry,
        format_checker=jsonschema.FormatChecker(),
    ).validate(instance)


def test_preview_is_deterministic_schema_valid_and_preserves_indeterminate():
    first = _plan()
    second = _plan()

    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.request == second.request
    assert first.request["assessment"]["verdict"] == "INDETERMINATE"
    assert first.mapped_fields["u_preflightops_status"] == "INDETERMINATE"
    assert "PASS" not in first.mapped_fields.values()
    assert first.request["delivery"]["idempotency_key"].startswith("snv2-")
    _validate_with_registry(first.to_dict(), "servicenow-adapter-plan-v2.schema.json")


def test_preview_golden_identity_is_stable():
    plan = _plan()

    assert hashlib.sha256(plan.canonical_bytes()).hexdigest() == (
        "d61d8ec46fe7227c1343e642a24ccb20e40e84e1447d9ae6ae9a63c5bca2ddbc"
    )
    assert plan.request["request_id"] == "snreq-eac042d9a29f204aa7164e034c8cff32"
    assert plan.request["delivery"]["idempotency_key"] == (
        "snv2-2dfbe7f9696ea13d955fc53431134cea2a26019c90b6d844475a4002b2c536ae"
    )


def test_gateway_capability_example_matches_contract():
    example = json.loads(
        (ROOT / "examples" / "servicenow-gateway-capability-v1.json").read_text(encoding="utf-8")
    )
    _validate_with_registry(example, "servicenow-gateway-capability-v1.schema.json")


def test_preview_never_resolves_or_acquires_credentials():
    calls = []
    policy = _policy(resolver=lambda host: calls.append(host) or ("93.184.216.34",))
    build_servicenow_plan_v2(
        _report(),
        _mapping(),
        instance_alias="enterprise-sandbox",
        instance_origin=INSTANCE_ORIGIN,
        network_policy=policy,
        target_number="CHG0000001",
        expected_sys_mod_count=7,
        capability_attestation_sha256=CAPABILITY_DIGEST,
    )
    assert calls == []


def test_plan_tampering_is_detected_before_execution():
    plan = _plan()
    plan.mapped_fields["u_preflightops_status"] = "READY_FOR_HUMAN_REVIEW"
    with pytest.raises(ServiceNowV2Error, match="digest") as excinfo:
        validate_servicenow_plan_v2(plan)
    assert excinfo.value.code == "REPLAY_MISMATCH"


def test_plan_mapping_profile_and_field_limits_are_revalidated():
    profile = _plan()
    profile.request["delivery"]["mapping_profile_id"] = "other-profile"
    with pytest.raises(ServiceNowV2Error, match="profile"):
        validate_servicenow_plan_v2(profile)

    oversized = _plan()
    destination = oversized.mapping["fields"]["assessment_status"]["destination"]
    oversized.mapped_fields[destination] = "X" * 33
    oversized.request["delivery"]["payload_sha256"] = hashlib.sha256(
        json.dumps(
            oversized.mapped_fields,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    with pytest.raises(ServiceNowV2Error, match="limit"):
        validate_servicenow_plan_v2(oversized)


def test_mapping_rejects_yaml_aliases(tmp_path):
    path = tmp_path / "mapping.yaml"
    path.write_text("schema_version: &v servicenow-mapping-v2\nprofile_id: *v\n", encoding="utf-8")
    with pytest.raises(ServiceNowV2Error, match="aliases"):
        load_servicenow_mapping_v2(path)


@pytest.mark.parametrize(
    "destination",
    ["state", "approval", "assignment_group", "u_assignment_group", "work_notes"],
)
def test_mapping_rejects_workflow_destinations(destination):
    mapping = _mapping()
    mapping["fields"]["assessment_status"]["destination"] = destination
    with pytest.raises(ServiceNowV2Error) as excinfo:
        load_servicenow_mapping_v2(mapping)
    assert excinfo.value.code == "INVALID_MAPPING"


def test_mapping_rejects_duplicate_and_delivery_destinations():
    duplicate = _mapping()
    duplicate["fields"]["risk"]["destination"] = duplicate["fields"]["confidence"]["destination"]
    with pytest.raises(ServiceNowV2Error, match="unique"):
        load_servicenow_mapping_v2(duplicate)

    delivery = _mapping()
    delivery["fields"]["risk"]["destination"] = "u_preflightops_delivery_id"
    with pytest.raises(ServiceNowV2Error, match="unique"):
        load_servicenow_mapping_v2(delivery)


@pytest.mark.parametrize(
    "origin",
    [
        "http://dev00000.service-now.com",
        "https://user:pass@dev00000.service-now.com",
        "https://dev00000.service-now.com:8443",
        "https://dev00000.service-now.com/path",
        "https://dev00000.service-now.com?token=value",
        "https://dev00000.service-now.com#fragment",
        "https://dev00000.service-now.com.evil.example",
        "https://127.0.0.1",
    ],
)
def test_instance_origin_attacks_fail_offline(origin):
    with pytest.raises(ServiceNowV2Error) as excinfo:
        build_servicenow_plan_v2(
            _report(),
            _mapping(),
            instance_alias="enterprise-sandbox",
            instance_origin=origin,
            network_policy=_policy(),
            target_number="CHG0000001",
            expected_sys_mod_count=7,
            capability_attestation_sha256=CAPABILITY_DIGEST,
        )
    assert excinfo.value.code == "UNTRUSTED_DESTINATION"


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "169.254.169.254", "10.0.0.8", "::1", "224.0.0.1"],
)
def test_private_and_special_resolutions_fail_closed(address):
    policy = _policy(resolver=lambda _host: (address,))
    with pytest.raises(ServiceNowV2Error, match="forbidden|private"):
        policy.validate_resolution(INSTANCE_HOST)


def test_explicit_private_network_can_be_allowlisted_but_not_loopback():
    allowed = NetworkPolicy(
        allowed_instance_hosts=(INSTANCE_HOST,),
        allowed_private_cidrs=("10.20.0.0/16",),
        resolver=lambda _host: ("10.20.1.2",),
    )
    assert allowed.validate_resolution(INSTANCE_HOST) == ("10.20.1.2",)
    with pytest.raises(ServiceNowV2Error):
        NetworkPolicy(
            allowed_instance_hosts=(INSTANCE_HOST,),
            allowed_private_cidrs=("127.0.0.0/8",),
        )
    with pytest.raises(ServiceNowV2Error):
        NetworkPolicy(
            allowed_instance_hosts=(INSTANCE_HOST,),
            allowed_private_cidrs=("0.0.0.0/0",),
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://artifacts.example.test/report",
        "https://user@artifacts.example.test/report",
        "https://artifacts.example.test/report?signature=sensitive",
        "https://artifacts.example.test/report#fragment",
        "https://evil.example.test/report",
        "https://artifacts.example.test//evil.example/report",
    ],
)
def test_evidence_url_attacks_fail_before_network(url):
    with pytest.raises(ServiceNowV2Error) as excinfo:
        _plan(evidence_mode="https_link", evidence_url=url)
    assert excinfo.value.code == "UNTRUSTED_DESTINATION"


def test_draft_is_disabled_by_default_before_any_external_dependency():
    with pytest.raises(ServiceNowV2Error, match="disabled") as excinfo:
        _plan(operation="create_draft")
    assert excinfo.value.code == "MODEL_NOT_ALLOWED"


def test_draft_requires_mapping_feature_model_and_external_authorization():
    with pytest.raises(ServiceNowV2Error, match="disabled"):
        _plan(operation="create_draft", feature=True)

    with pytest.raises(ServiceNowV2Error, match="allowlisted"):
        build_servicenow_plan_v2(
            _report(),
            _mapping(create_draft=True),
            instance_alias="enterprise-sandbox",
            instance_origin=INSTANCE_ORIGIN,
            network_policy=_policy(),
            operation="create_draft",
            model_sys_id="2" * 32,
            external_authorization_id="POLICY-DRAFT-TEST-01",
            draft_feature_enabled=True,
            capability_attestation_sha256=CAPABILITY_DIGEST,
        )


def test_dry_run_and_offline_read_only_make_zero_external_calls():
    for plan, expected in [(_plan(), "DRY_RUN"), (_plan(dry_run=False), "READ_ONLY")]:
        result = _adapter(None, None).execute(plan, confirm_write=True)
        assert result["outcome"] == expected
        assert result["attempts"] == 0
        assert result["verified"] is False


def test_read_only_resolves_exact_change_but_never_writes():
    plan = _plan(dry_run=False)
    transport = _successful_transport(plan)
    credential = FakeCredential()
    result = _adapter(transport, credential).execute(plan)

    assert result["outcome"] == "READ_ONLY"
    assert result["verified"] is True
    assert result["target"] == TARGET
    assert credential.calls == 1
    assert [request.method for request in transport.requests] == ["GET"]


def test_live_write_requires_explicit_confirmation_before_credentials():
    plan = _plan(dry_run=False, write_enabled=True)
    credential = FakeCredential()
    transport = _successful_transport(plan)
    result = _adapter(transport, credential).execute(plan)

    assert result["outcome"] == "FAILED"
    assert result["error"]["code"] == "AUTHORIZATION_DENIED"
    assert credential.calls == 0
    assert transport.requests == []


def test_v2_rejects_basic_auth_even_when_confirmed():
    plan = _plan(dry_run=False, write_enabled=True)
    credential = FakeCredential("Basic dGVzdDp0ZXN0")
    transport = _successful_transport(plan)
    result = _adapter(transport, credential).execute(plan, confirm_write=True)

    assert result["error"]["code"] == "AUTHENTICATION_FAILED"
    assert transport.requests == []


@pytest.mark.parametrize("header", ["Bearer token value", "Bearer token\tvalue", "Bearer "])
def test_v2_rejects_malformed_bearer_from_custom_provider(header):
    plan = _plan(dry_run=False, write_enabled=True)
    transport = _successful_transport(plan)
    result = _adapter(transport, FakeCredential(header)).execute(plan, confirm_write=True)

    assert result["error"]["code"] == "AUTHENTICATION_FAILED"
    assert transport.requests == []


def test_enrich_success_pins_target_uses_gateway_and_redacts_event():
    plan = _plan(dry_run=False, write_enabled=True)
    transport = _successful_transport(plan)
    credential = FakeCredential()
    events: list[dict] = []
    result = _adapter(transport, credential, events=events).execute(plan, confirm_write=True)

    assert result["outcome"] == "UPDATED"
    assert result["verified"] is True
    assert result["target"]["number"] == "CHG0000001"
    assert result["target"]["sys_id"] == "1" * 32
    assert result["target"]["sys_mod_count"] == 8
    assert [request.method for request in transport.requests] == ["GET", "GET", "POST", "GET"]
    post = transport.requests[2]
    assert post.headers["Idempotency-Key"] == plan.request["delivery"]["idempotency_key"]
    assert post.timeout_seconds == 10.0
    event_text = json.dumps(events)
    assert "test-canary-token" not in event_text
    assert "CHG0000001" not in event_text
    assert "1" * 32 not in event_text
    assert events[0]["target_hash"]
    _validate_with_registry(result, "servicenow-adapter-result-v2.schema.json")


def test_wrong_record_identity_is_rejected_without_gateway_write():
    plan = _plan(dry_run=False, write_enabled=True)
    wrong = {**TARGET, "number": "CHG0000002"}
    transport = _successful_transport(plan, lookup=wrong)
    result = _adapter(transport, FakeCredential()).execute(plan, confirm_write=True)

    assert result["outcome"] == "FAILED"
    assert result["error"]["code"] == "TARGET_AMBIGUOUS"
    assert [request.method for request in transport.requests] == ["GET"]


def test_missing_and_ambiguous_targets_fail_without_write():
    plan = _plan(dry_run=False, write_enabled=True)

    for payload, code in [
        ({"result": []}, "TARGET_NOT_FOUND"),
        ({"result": [TARGET, TARGET]}, "TARGET_AMBIGUOUS"),
    ]:
        transport = RecordingTransport(lambda _request, value=payload: _response(200, value))
        result = _adapter(transport, FakeCredential()).execute(plan, confirm_write=True)
        assert result["error"]["code"] == code
        assert all(request.method == "GET" for request in transport.requests)


def test_optimistic_concurrency_conflict_never_reaches_gateway():
    plan = _plan(dry_run=False, write_enabled=True)
    changed = {**TARGET, "sys_mod_count": 8}
    transport = _successful_transport(plan, lookup=changed)
    result = _adapter(transport, FakeCredential()).execute(plan, confirm_write=True)

    assert result["outcome"] == "CONFLICT"
    assert result["error"]["code"] == "CONCURRENCY_CONFLICT"
    assert result["error"]["write_state"] == "NOT_APPLIED"
    assert len(transport.requests) == 1


def test_replay_identical_returns_verified_unchanged_without_duplication():
    plan = _plan(dry_run=False, write_enabled=True)
    transport = _successful_transport(plan, outcome="UNCHANGED")
    result = _adapter(transport, FakeCredential()).execute(plan, confirm_write=True)

    assert result["outcome"] == "UNCHANGED"
    assert result["verified"] is True
    assert sum(request.method == "POST" for request in transport.requests) == 1


def test_replay_mismatch_conflict_is_fail_closed_and_redacted():
    plan = _plan(dry_run=False, write_enabled=True)

    def conflict(_request):
        return _response(
            409,
            {"error": {"code": "REPLAY_MISMATCH", "message": "Bearer sensitive-value"}},
        )

    transport = _successful_transport(plan, post=conflict)
    result = _adapter(transport, FakeCredential()).execute(plan, confirm_write=True)
    serialized = json.dumps(result)

    assert result["outcome"] == "CONFLICT"
    assert result["error"]["code"] == "REPLAY_MISMATCH"
    assert "sensitive-value" not in serialized


def test_capability_must_attest_mapping_cas_unique_delivery_and_operation():
    plan = _plan(dry_run=False, write_enabled=True)

    def handler(request):
        if "/change" in request.url:
            return _response(200, {"result": TARGET})
        capability = _capability(plan)
        capability["result"]["unique_delivery"] = False
        return _response(200, capability)

    transport = RecordingTransport(handler)
    result = _adapter(transport, FakeCredential()).execute(plan, confirm_write=True)

    assert result["error"]["code"] == "CAPABILITY_MISSING"
    assert all(request.method == "GET" for request in transport.requests)


def test_capability_rejects_string_in_place_of_operation_array():
    plan = _plan(dry_run=False, write_enabled=True)

    def handler(request):
        if "/change" in request.url:
            return _response(200, {"result": TARGET})
        capability = _capability(plan)
        capability["result"]["allowed_operations"] = "enrich_existing"
        return _response(200, capability)

    result = _adapter(RecordingTransport(handler), FakeCredential()).execute(
        plan, confirm_write=True
    )
    assert result["error"]["code"] == "CAPABILITY_MISSING"


def test_rate_limit_respects_retry_after_and_retries_with_same_key():
    plan = _plan(dry_run=False, write_enabled=True)
    post_count = 0
    sleeps: list[float] = []

    def post(_request):
        nonlocal post_count
        post_count += 1
        if post_count == 1:
            return _response(429, {}, {"Retry-After": "2"})
        return _response(201, _remote(plan))

    transport = _successful_transport(plan, post=post)
    result = _adapter(transport, FakeCredential(), sleep=sleeps.append).execute(
        plan, confirm_write=True
    )

    assert result["outcome"] == "UPDATED"
    assert result["attempts"] == 2
    assert sleeps == [2.0]
    keys = [
        request.headers["Idempotency-Key"]
        for request in transport.requests
        if request.method == "POST"
    ]
    assert keys == [plan.request["delivery"]["idempotency_key"]] * 2


def test_rate_limit_outside_budget_returns_rate_limited_without_sleep():
    plan = _plan(dry_run=False, write_enabled=True)
    transport = _successful_transport(
        plan,
        post=lambda _request: _response(429, {}, {"Retry-After": "120"}),
    )
    sleeps = []
    result = _adapter(
        transport,
        FakeCredential(),
        retry=RetryPolicy(attempts=3, elapsed_seconds=30),
        sleep=sleeps.append,
    ).execute(plan, confirm_write=True)

    assert result["error"]["code"] == "RATE_LIMITED"
    assert result["attempts"] == 1
    assert sleeps == []


def test_timeout_after_commit_reconciles_without_duplicate_write():
    plan = _plan(dry_run=False, write_enabled=True)

    def timeout(_request):
        raise TimeoutError("contains sensitive transport detail")

    transport = _successful_transport(plan, post=timeout)
    result = _adapter(transport, FakeCredential()).execute(plan, confirm_write=True)

    assert result["outcome"] == "UPDATED"
    assert result["verified"] is True
    assert sum(request.method == "POST" for request in transport.requests) == 1


def test_timeout_with_unverifiable_reconciliation_is_partial_unknown():
    plan = _plan(dry_run=False, write_enabled=True)

    def timeout(_request):
        raise TimeoutError("Bearer should-never-appear")

    transport = _successful_transport(
        plan,
        post=timeout,
        reconcile=lambda _request: _response(503, {"secret": "should-never-appear"}),
    )
    result = _adapter(transport, FakeCredential()).execute(plan, confirm_write=True)

    assert result["outcome"] == "PARTIAL_FAILURE_UNKNOWN"
    assert result["error"]["code"] == "PARTIAL_FAILURE_UNKNOWN"
    assert result["error"]["write_state"] == "UNKNOWN"
    assert "should-never-appear" not in json.dumps(result)
    assert plan.evidence["document"] == _report()


def test_503_retries_only_after_reconcile_proves_not_applied():
    plan = _plan(dry_run=False, write_enabled=True)
    posts = 0
    reconciles = 0

    def post(_request):
        nonlocal posts
        posts += 1
        return _response(503, {}) if posts == 1 else _response(201, _remote(plan))

    def reconcile(_request):
        nonlocal reconciles
        reconciles += 1
        return _response(404, {}) if reconciles == 1 else _response(200, _remote(plan))

    transport = _successful_transport(plan, post=post, reconcile=reconcile)
    sleeps = []
    result = _adapter(transport, FakeCredential(), sleep=sleeps.append).execute(
        plan, confirm_write=True
    )

    assert result["outcome"] == "UPDATED"
    assert result["attempts"] == 2
    assert posts == 2
    assert len(sleeps) == 1


def test_redirect_is_terminal_and_authorization_is_not_exposed():
    plan = _plan(dry_run=False, write_enabled=True)
    transport = RecordingTransport(
        lambda _request: HttpResponse(
            302,
            {"Location": "https://evil.example/steal?authorization=secret"},
            b"Bearer remote-secret",
        )
    )
    events = []
    result = _adapter(transport, FakeCredential(), events=events).execute(plan, confirm_write=True)
    combined = json.dumps([result, events])

    assert result["error"]["code"] == "REDIRECT_REJECTED"
    assert len(transport.requests) == 1
    assert "evil.example" not in combined
    assert "remote-secret" not in combined


def test_gateway_readback_mismatch_never_claims_success():
    plan = _plan(dry_run=False, write_enabled=True)

    def mismatch(_request):
        value = _remote(plan)
        value["result"]["payload_sha256"] = "0" * 64
        return _response(200, value)

    transport = _successful_transport(plan, reconcile=mismatch)
    result = _adapter(transport, FakeCredential()).execute(plan, confirm_write=True)

    assert result["outcome"] == "PARTIAL_FAILURE_UNKNOWN"
    assert result["verified"] is False


def test_create_draft_requires_both_gates_and_never_sends_workflow_fields():
    plan = _plan(
        operation="create_draft",
        create_draft=True,
        feature=True,
        dry_run=False,
        write_enabled=True,
        target_number=None,
    )
    transport = _successful_transport(plan, outcome="CREATED_DRAFT")
    disabled = _adapter(transport, FakeCredential(), feature=False).execute(
        plan, confirm_write=True
    )
    assert disabled["error"]["code"] == "MODEL_NOT_ALLOWED"
    assert transport.requests == []

    transport = _successful_transport(plan, outcome="CREATED_DRAFT")
    result = _adapter(transport, FakeCredential(), feature=True).execute(plan, confirm_write=True)
    assert result["outcome"] == "CREATED_DRAFT"
    post = next(request for request in transport.requests if request.method == "POST")
    body = json.loads(post.body)
    serialized = json.dumps(body)
    for forbidden in ("state", "approval", "assignment_group", "work_notes", "close_code"):
        assert f'"{forbidden}"' not in serialized


def test_oauth_client_credentials_uses_injected_transport_and_rejects_redirect():
    transport = RecordingTransport(
        lambda _request: _response(
            200,
            {"access_token": "oauth-test-canary", "token_type": "Bearer", "expires_in": 60},
        )
    )
    provider = OAuthClientCredentialsProvider(
        client_id="test-application-user",
        client_secret="test-secret-not-real",
        transport=transport,
        network_policy=_policy(),
        scope="x_preflightops.evidence.write",
    )
    header = provider.authorization_header(INSTANCE_ORIGIN)

    assert header == "Bearer oauth-test-canary"
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.url == f"{INSTANCE_ORIGIN}/oauth_token.do"
    assert b"client_secret=test-secret-not-real" in request.body

    redirect = RecordingTransport(
        lambda _request: HttpResponse(302, {"Location": "https://evil.example"}, b"")
    )
    provider = OAuthClientCredentialsProvider(
        client_id="test-application-user",
        client_secret="test-secret-not-real",
        transport=redirect,
        network_policy=_policy(),
        scope="x_preflightops.evidence.write",
    )
    with pytest.raises(ServiceNowV2Error) as excinfo:
        provider.authorization_header(INSTANCE_ORIGIN)
    assert excinfo.value.code == "REDIRECT_REJECTED"

    with pytest.raises(ValueError, match="timeout"):
        OAuthClientCredentialsProvider(
            client_id="test-application-user",
            client_secret="test-secret-not-real",
            transport=transport,
            network_policy=_policy(),
            scope="x_preflightops.evidence.write",
            timeout_seconds=0,
        )


@pytest.mark.parametrize(
    ("status", "payload", "code"),
    [
        (401, {"error": "Bearer secret"}, "AUTHENTICATION_FAILED"),
        (500, {"password": "secret"}, "AUTHENTICATION_FAILED"),
        (200, {"access_token": "short"}, "AUTHENTICATION_FAILED"),
    ],
)
def test_oauth_failures_are_static_and_redacted(status, payload, code):
    provider = OAuthClientCredentialsProvider(
        client_id="test-application-user",
        client_secret="test-secret-not-real",
        transport=RecordingTransport(lambda _request: _response(status, payload)),
        network_policy=_policy(),
        scope="x_preflightops.evidence.write",
    )
    with pytest.raises(ServiceNowV2Error) as excinfo:
        provider.authorization_header(INSTANCE_ORIGIN)
    assert excinfo.value.code == code
    assert "secret" not in excinfo.value.safe_message.lower()


def test_urllib_transport_returns_redirect_without_following(monkeypatch):
    transport = UrllibTransport(network_policy=_policy())

    class FakeHeaders:
        def items(self):
            return [("Location", "https://evil.example")]

    error = urllib.error.HTTPError(
        f"{INSTANCE_ORIGIN}/api/test",
        302,
        "redirect",
        FakeHeaders(),
        None,
    )
    error.read = lambda _limit: b""
    monkeypatch.setattr(
        transport._opener, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(error)
    )
    response = transport.send(HttpRequest("GET", f"{INSTANCE_ORIGIN}/api/test", {}))
    assert response.status == 302


def test_urllib_transport_revalidates_url_and_proxy_resolution_before_send(monkeypatch):
    resolved = []
    policy = NetworkPolicy(
        allowed_instance_hosts=(INSTANCE_HOST,),
        allowed_proxy_hosts=("proxy.example.test",),
        resolver=lambda host: resolved.append(host) or ("93.184.216.34",),
    )
    transport = UrllibTransport(
        network_policy=policy,
        proxy_origin="https://proxy.example.test",
    )

    class FakeResponse:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return b"{}"

    monkeypatch.setattr(transport._opener, "open", lambda *_args, **_kwargs: FakeResponse())
    response = transport.send(HttpRequest("GET", f"{INSTANCE_ORIGIN}/api/test", {}))
    assert response.status == 200
    assert resolved == [INSTANCE_HOST, "proxy.example.test"]

    with pytest.raises(ServiceNowV2Error):
        transport.send(HttpRequest("GET", "https://evil.example.test/api/test", {}))


def test_dual_preview_is_content_free_offline_and_keeps_v1_available():
    result = {
        "service": "checkout-api",
        "environment": "production",
        "risk_level": "HIGH",
        "risk_score": 75,
        "business_impact": "internal",
    }
    change = {
        "change": {
            "id": "CHG-2026-0808",
            "title": "Deploy checkout",
            "description": "bounded",
            "rollback_plan": "Rollback release",
            "validation_plan": "Run checks",
        }
    }
    legacy = prepare_payload(result, change, env={})
    plan = _plan()
    comparison = compare_servicenow_previews_v1_v2(legacy, plan)

    assert comparison["network_calls"] == 0
    assert comparison["legacy"]["mapping_version"] == "1"
    assert comparison["enterprise"]["request_id"] == plan.request["request_id"]
    serialized = json.dumps(comparison)
    assert "Deploy checkout" not in serialized
    assert "Rollback release" not in serialized


def test_retry_policy_cannot_exceed_mapping_budget():
    plan = _plan(dry_run=False)
    result = _adapter(
        None,
        None,
        retry=RetryPolicy(attempts=4, elapsed_seconds=90),
    ).execute(plan)
    assert result["error"]["code"] == "INVALID_MAPPING"


def test_result_timestamp_comes_from_injected_clock():
    result = _adapter(None, None).execute(_plan())
    assert result["audit"]["completed_at"] == "2026-09-03T18:00:00Z"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"attempts": 0},
        {"attempts": 6},
        {"elapsed_seconds": 0},
        {"elapsed_seconds": 301},
        {"request_timeout_seconds": 0},
        {"request_timeout_seconds": 121},
        {"base_delay_seconds": -1},
        {"base_delay_seconds": 31},
    ],
)
def test_retry_policy_rejects_unbounded_values(kwargs):
    with pytest.raises(ServiceNowV2Error) as excinfo:
        RetryPolicy(**kwargs)
    assert excinfo.value.code == "INVALID_MAPPING"


def test_system_resolver_returns_sorted_unique_addresses(monkeypatch):
    monkeypatch.setattr(
        enterprise.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (2, 1, 6, "", ("93.184.216.35", 443)),
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("93.184.216.35", 443)),
        ],
    )
    assert system_resolver(INSTANCE_HOST) == ("93.184.216.34", "93.184.216.35")


def test_network_policy_rejects_invalid_configuration_and_resolution():
    with pytest.raises(ServiceNowV2Error, match="Too many instance"):
        NetworkPolicy(
            allowed_instance_hosts=tuple(f"host-{index}.example.test" for index in range(65))
        )
    with pytest.raises(ServiceNowV2Error, match="invalid CIDR"):
        NetworkPolicy(allowed_instance_hosts=(INSTANCE_HOST,), allowed_private_cidrs=("bad",))
    with pytest.raises(ServiceNowV2Error, match="Too many private"):
        NetworkPolicy(
            allowed_instance_hosts=(INSTANCE_HOST,),
            allowed_private_cidrs=tuple(f"10.{index}.0.0/16" for index in range(65)),
        )
    with pytest.raises(ServiceNowV2Error, match="explicit DNS"):
        NetworkPolicy(allowed_instance_hosts=(INSTANCE_HOST,)).validate_resolution(INSTANCE_HOST)
    with pytest.raises(ServiceNowV2Error, match="failed closed"):
        _policy(
            resolver=lambda _host: (_ for _ in ()).throw(OSError("secret"))
        ).validate_resolution(INSTANCE_HOST)
    with pytest.raises(ServiceNowV2Error, match="no addresses"):
        _policy(resolver=lambda _host: ()).validate_resolution(INSTANCE_HOST)
    with pytest.raises(ServiceNowV2Error, match="invalid address"):
        _policy(resolver=lambda _host: ("not-an-address",)).validate_resolution(INSTANCE_HOST)


def test_mapping_loader_fails_closed_for_filesystem_and_parser_errors(tmp_path):
    with pytest.raises(ServiceNowV2Error, match="Unable to read"):
        load_servicenow_mapping_v2(tmp_path / "missing.yaml")

    oversized = tmp_path / "oversized.yaml"
    oversized.write_bytes(b"x" * (256 * 1024 + 1))
    with pytest.raises(ServiceNowV2Error, match="too large"):
        load_servicenow_mapping_v2(oversized)

    invalid_utf8 = tmp_path / "invalid.yaml"
    invalid_utf8.write_bytes(b"\xff")
    with pytest.raises(ServiceNowV2Error, match="invalid"):
        load_servicenow_mapping_v2(invalid_utf8)

    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("value", encoding="utf-8")
    with pytest.raises(ServiceNowV2Error, match="object"):
        load_servicenow_mapping_v2(scalar)

    with pytest.raises(ServiceNowV2Error, match="local data"):
        load_servicenow_mapping_v2(42)


def test_plan_builder_rejects_invalid_modes_targets_and_evidence():
    common = {
        "instance_alias": "enterprise-sandbox",
        "instance_origin": INSTANCE_ORIGIN,
        "network_policy": _policy(),
        "target_number": "CHG0000001",
        "expected_sys_mod_count": 7,
        "capability_attestation_sha256": CAPABILITY_DIGEST,
    }
    cases = [
        {"instance_alias": "INVALID"},
        {"capability_attestation_sha256": "bad"},
        {"dry_run": 1},
        {"dry_run": True, "write_enabled": True},
        {"transport_profile": "table_api_v1"},
        {"target_number": None, "target_sys_id": None},
        {"target_sys_id": "1" * 32},
        {"target_number": "bad"},
        {"target_number": None, "target_sys_id": "bad"},
        {"expected_sys_mod_count": -1},
        {"operation": "delete"},
        {"evidence_mode": "inline"},
        {"evidence_mode": "attachment", "evidence_url": "https://artifacts.example.test/x"},
    ]
    for overrides in cases:
        kwargs = {**common, **overrides}
        with pytest.raises(ServiceNowV2Error):
            build_servicenow_plan_v2(_report(), _mapping(), **kwargs)

    invalid_report = _report()
    invalid_report["decision"]["verdict"] = "PASS"
    with pytest.raises(ServiceNowV2Error, match="Report"):
        build_servicenow_plan_v2(invalid_report, _mapping(), **common)

    attachment_only = _mapping()
    attachment_only["evidence"]["mode"] = "attachment"
    with pytest.raises(ServiceNowV2Error, match="disabled"):
        build_servicenow_plan_v2(
            _report(),
            attachment_only,
            **common,
            evidence_mode="https_link",
            evidence_url="https://artifacts.example.test/report.json",
        )


def test_draft_builder_rejects_missing_external_authorization():
    with pytest.raises(ServiceNowV2Error, match="external authorization"):
        build_servicenow_plan_v2(
            _report(),
            _mapping(create_draft=True),
            instance_alias="enterprise-sandbox",
            instance_origin=INSTANCE_ORIGIN,
            network_policy=_policy(),
            operation="create_draft",
            model_sys_id="1" * 32,
            external_authorization_id=None,
            draft_feature_enabled=True,
            capability_attestation_sha256=CAPABILITY_DIGEST,
        )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("assessment", "risk_level"), "UNKNOWN"),
        (("assessment", "confidence_level"), "UNKNOWN"),
        (("assessment", "policy_name"), ""),
        (("assessment", "policy_version"), "x" * 65),
        (("assessment", "commit"), "bad"),
        (("assessment", "assessed_at"), "2026-09-03T18:00:00+00:00"),
        (("delivery", "evidence_mode"), "inline"),
    ],
)
def test_plan_request_semantics_are_revalidated(path, value):
    plan = _plan()
    plan.request[path[0]][path[1]] = value
    with pytest.raises(ServiceNowV2Error):
        validate_servicenow_plan_v2(plan)


def test_transport_rejects_unbounded_response_and_maps_network_failure(monkeypatch):
    with pytest.raises(ValueError, match="between"):
        UrllibTransport(network_policy=_policy(), max_response_bytes=1)

    transport = UrllibTransport(network_policy=_policy(), max_response_bytes=1024)

    class OversizedResponse:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return b"x" * 1025

    monkeypatch.setattr(transport._opener, "open", lambda *_args, **_kwargs: OversizedResponse())
    with pytest.raises(ServiceNowV2Error, match="exceeded"):
        transport.send(HttpRequest("GET", f"{INSTANCE_ORIGIN}/api/test", {}))

    monkeypatch.setattr(
        transport._opener,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    with pytest.raises(OSError, match="failed"):
        transport.send(HttpRequest("GET", f"{INSTANCE_ORIGIN}/api/test", {}))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"client_id": ""},
        {"client_secret": ""},
        {"scope": ""},
        {"scope": "x" * 257},
    ],
)
def test_oauth_configuration_is_strict(kwargs):
    values = {
        "client_id": "test-application-user",
        "client_secret": "test-secret-not-real",
        "transport": RecordingTransport(lambda _request: _response(200, {})),
        "network_policy": _policy(),
        "scope": "x_preflightops.evidence.write",
        **kwargs,
    }
    with pytest.raises(ValueError):
        OAuthClientCredentialsProvider(**values)

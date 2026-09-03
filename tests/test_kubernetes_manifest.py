"""Contract, adversarial, privacy, and determinism tests for Kubernetes manifests."""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import pytest

from preflightops import (
    DEFAULT_KUBERNETES_MANIFEST_LIMITS,
    KubernetesManifestError,
    KubernetesManifestLimits,
    parse_kubernetes_manifests,
    scan_kubernetes,
    scan_kubernetes_legacy,
)

FIXTURE = Path(__file__).parent / "fixtures" / "kubernetes" / "structural-multidoc-v1.yaml"
SECRET_MARKER = "SECRET_MARKER_MUST_NOT_LEAK"


def _manifest(kind: str = "ConfigMap", name: str = "example", spec: str = "") -> str:
    suffix = f"\nspec:\n{spec}" if spec else ""
    return f"apiVersion: v1\nkind: {kind}\nmetadata:\n  name: {name}{suffix}\n"


def _error(raw: str | bytes, code: str, **limits: int) -> KubernetesManifestError:
    configured = (
        KubernetesManifestLimits(**limits) if limits else DEFAULT_KUBERNETES_MANIFEST_LIMITS
    )
    with pytest.raises(KubernetesManifestError) as captured:
        parse_kubernetes_manifests(raw, limits=configured)
    assert captured.value.code == code
    return captured.value


def test_fixture_is_evaluated_per_object_and_field() -> None:
    findings = scan_kubernetes(FIXTURE.read_text(encoding="utf-8"))
    risky = [item for item in findings if item["object_ref"]["name"] == "incomplete-worker"]
    complete = [item for item in findings if item["object_ref"]["name"] == "complete-api"]

    assert "kubernetes-missing-readiness-probe" in {item["id"] for item in risky}
    assert "kubernetes-missing-readiness-probe" not in {item["id"] for item in complete}
    assert all(item["object_ref"]["namespace"] == "payments" for item in findings)
    assert all(set(item["evidence"]) >= {"field", "predicate"} for item in findings)


def test_comments_and_empty_documents_are_not_evidence() -> None:
    raw = "# kind: Secret\n---\n\n---\n" + _manifest()
    assert scan_kubernetes(raw) == []


def test_secret_body_and_outputs_are_sanitized() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    objects = parse_kubernetes_manifests(raw)
    secret = next(item for item in objects if item.kind == "Secret")
    findings = scan_kubernetes(raw)

    assert set(secret.body) == {"apiVersion", "kind", "metadata"}
    assert SECRET_MARKER not in repr(secret)
    assert SECRET_MARKER not in json.dumps(findings, sort_keys=True)
    assert "U0VDUkVUX01BUktFUl9NVVNUX05PVF9MRUFL" not in repr(secret)


def test_secret_followed_by_invalid_list_item_returns_no_partial_result() -> None:
    raw = """
apiVersion: v1
kind: List
items:
  - apiVersion: v1
    kind: Secret
    metadata: {name: credential}
    stringData: {token: SECRET_MARKER_MUST_NOT_LEAK}
  - definitely-not-an-object
"""
    error = _error(raw, "invalid_object")
    assert SECRET_MARKER not in str(error)


def test_object_body_is_deeply_immutable() -> None:
    obj = parse_kubernetes_manifests(
        _manifest("ConfigMap", spec="  nested:\n    values: [one, two]")
    )[0]
    assert isinstance(obj.body, MappingProxyType)
    assert obj.body["spec"]["nested"]["values"] == ("one", "two")
    with pytest.raises(TypeError):
        obj.body["spec"]["nested"]["new"] = "value"


def test_list_expansion_and_default_namespace() -> None:
    raw = """
apiVersion: v1
kind: List
items:
  - apiVersion: v1
    kind: ConfigMap
    metadata: {name: first}
  - apiVersion: v1
    kind: ConfigMap
    metadata: {name: second, namespace: tools}
"""
    objects = parse_kubernetes_manifests(raw)
    assert [(item.name, item.namespace) for item in objects] == [
        ("first", "default"),
        ("second", "tools"),
    ]


def test_homonymous_objects_keep_distinct_namespace_identity() -> None:
    first = _manifest().replace("name: example", "name: api\n  namespace: blue")
    second = _manifest().replace("name: example", "name: api\n  namespace: green")
    objects = parse_kubernetes_manifests(first + "---\n" + second)
    assert {item.namespace for item in objects} == {"blue", "green"}


def test_duplicate_object_identity_fails_closed() -> None:
    raw = _manifest() + "---\n" + _manifest()
    _error(raw, "duplicate_object")


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("apiVersion: v1\nkind: ConfigMap\nmetadata: [bad]", "missing_metadata"),
        ("kind: ConfigMap\nmetadata: {name: example}", "missing_api_version"),
        ("apiVersion: v1\nmetadata: {name: example}", "missing_kind"),
        ("apiVersion: v1\nkind: ConfigMap\nmetadata: {}", "missing_name"),
        (
            "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: x, namespace: ''}",
            "invalid_namespace",
        ),
        ("apiVersion: v1\nkind: List\nitems: wrong", "invalid_list_items"),
        ("apiVersion: v1\nkind: ConfigMap\nmetadata: {name: x}\na: 1\na: 2", "duplicate_key"),
        ("apiVersion: v1\nkind: ConfigMap\nmetadata: {name: x}\n1: value", "non_string_key"),
        (
            "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: x}\nvalue: !unsafe tag",
            "invalid_yaml",
        ),
        ("apiVersion: v1\nkind: ConfigMap\nmetadata: [", "invalid_yaml"),
        ("apiVersion: v1\nkind: ConfigMap\nmetadata: {name: x}\nvalue: .nan", "non_finite_number"),
        (
            "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: x}\nvalue: 2026-09-03",
            "unsupported_scalar",
        ),
    ],
)
def test_invalid_or_ambiguous_input_has_stable_safe_error(raw: str, code: str) -> None:
    error = _error(raw, code)
    assert error.path.startswith("$") or error.path.startswith("configmap/")
    assert raw not in str(error)


def test_yaml_merge_key_is_rejected() -> None:
    raw = """
apiVersion: v1
kind: ConfigMap
metadata: {name: merged}
base: &base {one: 1}
merged: {<<: *base, two: 2}
"""
    _error(raw, "merge_key_not_allowed")


def test_non_recursive_alias_is_bounded_and_deterministic() -> None:
    raw = """
apiVersion: v1
kind: ConfigMap
metadata: {name: aliases}
data:
  first: &shared [one, two]
  second: *shared
"""
    forward = parse_kubernetes_manifests(raw)[0]
    assert forward.body["data"]["first"] == forward.body["data"]["second"]
    assert parse_kubernetes_manifests(raw) == (forward,)


def test_recursive_alias_is_rejected() -> None:
    raw = """
apiVersion: v1
kind: ConfigMap
metadata: {name: recursive}
data: &cycle
  self: *cycle
"""
    _error(raw, "recursive_alias")


def test_alias_limit_is_enforced() -> None:
    raw = """
apiVersion: v1
kind: ConfigMap
metadata: {name: aliases}
data:
  first: &shared value
  second: *shared
  third: *shared
"""
    _error(raw, "too_many_aliases", max_aliases=1)


@pytest.mark.parametrize(
    ("raw", "code", "limits"),
    [
        (_manifest(), "input_too_large", {"max_input_bytes": 8}),
        (
            _manifest() + "---\n" + _manifest("ConfigMap", "second"),
            "too_many_documents",
            {"max_documents": 1},
        ),
        (_manifest(), "max_nodes_exceeded", {"max_nodes": 2}),
        (
            _manifest("ConfigMap", spec="  a:\n    b:\n      c: value"),
            "max_depth_exceeded",
            {"max_depth": 3},
        ),
        (_manifest("ConfigMap", "long-name"), "string_too_large", {"max_string_length": 4}),
        (
            _manifest() + "---\n" + _manifest("ConfigMap", "second"),
            "too_many_objects",
            {"max_objects": 1},
        ),
    ],
)
def test_defensive_limits(raw: str, code: str, limits: dict[str, int]) -> None:
    _error(raw, code, **limits)


def test_container_limit_and_shape_are_enforced() -> None:
    two_containers = _manifest(
        "Deployment",
        spec="  template:\n    spec:\n      containers: [{name: one}, {name: two}]",
    )
    _error(two_containers, "too_many_containers", max_containers=1)
    _error(
        _manifest("Deployment", spec="  template:\n    spec:\n      containers: wrong"),
        "invalid_container_list",
    )
    _error(
        _manifest("Deployment", spec="  template:\n    spec:\n      containers: [wrong]"),
        "invalid_container",
    )
    _error(
        _manifest("Deployment", spec="  template:\n    spec:\n      containers: [{}]"),
        "missing_container_name",
    )


def test_input_type_encoding_and_limit_configuration_are_validated() -> None:
    assert parse_kubernetes_manifests(_manifest().encode())
    _error(b"\xff", "invalid_encoding")
    with pytest.raises(KubernetesManifestError, match="invalid_input_type"):
        parse_kubernetes_manifests(42)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="max_documents"):
        KubernetesManifestLimits(max_documents=0)
    with pytest.raises(ValueError, match="max_aliases"):
        KubernetesManifestLimits(max_aliases=True)  # type: ignore[arg-type]


def test_findings_are_byte_stable_when_documents_are_reordered() -> None:
    first = _manifest("Secret", "credential")
    second = _manifest("Service", "public", "  type: NodePort")
    forward = json.dumps(scan_kubernetes(first + "---\n" + second), sort_keys=True)
    reverse = json.dumps(scan_kubernetes(second + "---\n" + first), sort_keys=True)
    assert forward == reverse


def test_workload_kinds_and_field_rules_are_structural() -> None:
    raw = """
apiVersion: apps/v1
kind: DaemonSet
metadata: {name: agent}
spec:
  updateStrategy: {type: OnDelete}
  template:
    spec:
      hostPID: true
      containers:
        - name: agent
          readinessProbe: {}
          livenessProbe: {}
          resources: {requests: {cpu: 1m}, limits: {cpu: 1m}}
---
apiVersion: batch/v1
kind: Job
metadata: {name: batch}
spec:
  suspend: true
  parallelism: 0
  template:
    spec:
      containers: [{name: batch}]
---
apiVersion: batch/v1
kind: CronJob
metadata: {name: scheduled}
spec:
  suspend: true
  jobTemplate:
    spec:
      template:
        spec:
          hostIPC: true
          containers: [{name: scheduled}]
"""
    findings = scan_kubernetes(raw)
    ids = {item["id"] for item in findings}
    assert {
        "kubernetes-daemonset-change",
        "kubernetes-job-change",
        "kubernetes-cronjob-change",
        "kubernetes-ondelete-strategy",
        "kubernetes-workload-suspended",
        "kubernetes-parallelism-zero",
        "kubernetes-host-pid",
        "kubernetes-host-ipc",
    } <= ids
    job_probe_findings = [
        item
        for item in findings
        if item["object_ref"]["kind"] in {"Job", "CronJob"} and "probe" in item["id"]
    ]
    assert job_probe_findings == []


def test_service_exposure_strategy_and_pdb_rules_reference_exact_fields() -> None:
    raw = """
apiVersion: v1
kind: Service
metadata: {name: public}
spec: {type: NodePort, externalIPs: [203.0.113.1]}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: rollout}
spec:
  strategy: {rollingUpdate: {maxUnavailable: 100%}}
  template: {spec: {containers: [{name: api}]}}
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: {name: no-protection}
spec: {minAvailable: 0, maxUnavailable: 100%}
"""
    findings = scan_kubernetes(raw)
    evidence = {(item["id"], item["evidence"]["field"]) for item in findings}
    assert {
        ("kubernetes-nodeport-exposure", "spec.type"),
        ("kubernetes-service-external-ips", "spec.externalIPs"),
        ("kubernetes-max-unavailable-all", "spec.strategy.rollingUpdate.maxUnavailable"),
        ("kubernetes-pdb-no-protection", "spec.minAvailable"),
        ("kubernetes-pdb-no-protection", "spec.maxUnavailable"),
    } <= evidence


def test_boolean_false_is_not_interpreted_as_numeric_zero() -> None:
    raw = _manifest("Deployment", spec="  replicas: false\n  template: {spec: {containers: []}}")
    ids = {item["id"] for item in scan_kubernetes(raw)}
    assert "kubernetes-replicas-zero" not in ids


def test_legacy_scanner_is_explicit_and_no_structural_fallback_occurs() -> None:
    invalid = "kind: Secret"
    with pytest.raises(KubernetesManifestError, match="missing_api_version"):
        scan_kubernetes(invalid)
    assert {item["id"] for item in scan_kubernetes_legacy(invalid)} == {"kubernetes-secret-change"}


def test_structural_analysis_never_uses_network(monkeypatch) -> None:
    def forbidden_socket(*args, **kwargs):
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr("socket.socket", forbidden_socket)
    findings = scan_kubernetes(_manifest("Secret", "offline"))
    assert [item["id"] for item in findings] == ["kubernetes-secret-change"]

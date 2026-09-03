"""Bounded structural Kubernetes manifest parsing and risk findings.

The module is deliberately offline.  It validates YAML as a bounded JSON-like
graph, normalizes each Kubernetes object independently, strips Secret payloads,
and emits deterministic field-level evidence.  Text matching is available only
through the explicit legacy adapter at the bottom of the module.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Any, NoReturn

import yaml
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken

SOURCE_KUBERNETES = "Kubernetes"

# Retained as a public compatibility contract for legacy callers.
KUBERNETES_SIGNALS = [
    (
        "kind: deployment",
        "kubernetes-deployment-change",
        10,
        "medium",
        "Kubernetes Deployment change detected",
    ),
    (
        "kind: statefulset",
        "kubernetes-statefulset-change",
        20,
        "high",
        "Kubernetes StatefulSet change detected",
    ),
    (
        "kind: ingress",
        "kubernetes-ingress-change",
        25,
        "high",
        "Kubernetes Ingress change detected",
    ),
    (
        "kind: networkpolicy",
        "kubernetes-networkpolicy-change",
        25,
        "high",
        "Kubernetes NetworkPolicy change detected",
    ),
    ("kind: secret", "kubernetes-secret-change", 25, "high", "Kubernetes Secret change detected"),
    (
        "type: loadbalancer",
        "kubernetes-loadbalancer-exposure",
        25,
        "high",
        "LoadBalancer exposure detected",
    ),
    ("replicas: 0", "kubernetes-replicas-zero", 30, "high", "Replicas set to zero detected"),
]


class KubernetesManifestError(ValueError):
    """A fail-closed, content-safe Kubernetes input error."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


class _LoaderViolation(yaml.YAMLError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.safe_message = message
        super().__init__(message)


class _StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects ambiguous or non-JSON mapping keys."""

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        if not isinstance(node, MappingNode):
            raise _LoaderViolation("invalid_mapping", "mapping node is invalid")
        seen: set[str] = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise _LoaderViolation("merge_key_not_allowed", "YAML merge keys are not supported")
            key = self.construct_object(key_node, deep=False)
            if not isinstance(key, str):
                raise _LoaderViolation("non_string_key", "mapping keys must be strings")
            if key in seen:
                raise _LoaderViolation("duplicate_key", "duplicate mapping key is not allowed")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


@dataclass(frozen=True)
class KubernetesManifestLimits:
    """Defensive limits applied before any finding is emitted."""

    max_input_bytes: int = 4 * 1024 * 1024
    max_documents: int = 256
    max_aliases: int = 128
    max_depth: int = 64
    max_nodes: int = 100_000
    max_objects: int = 2_048
    max_containers: int = 8_192
    max_string_length: int = 1024 * 1024

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{item.name} must be a positive integer")


DEFAULT_KUBERNETES_MANIFEST_LIMITS = KubernetesManifestLimits()


@dataclass(frozen=True)
class KubernetesObject:
    """Normalized immutable identity and sanitized object body."""

    api_version: str
    kind: str
    namespace: str
    name: str
    document_index: int
    body: Mapping[str, Any]

    @property
    def resource(self) -> str:
        return f"{self.kind.casefold()}/{self.name}"

    @property
    def object_ref(self) -> dict[str, str]:
        return {
            "api_version": self.api_version,
            "kind": self.kind,
            "namespace": self.namespace,
            "name": self.name,
        }


def _raise(code: str, path: str, message: str) -> NoReturn:
    raise KubernetesManifestError(code, path, message)


def _input_text(value: str | bytes, limits: KubernetesManifestLimits) -> str:
    if isinstance(value, bytes):
        if len(value) > limits.max_input_bytes:
            _raise("input_too_large", "$", "manifest exceeds the configured byte limit")
        try:
            return value.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            _raise("invalid_encoding", "$", "manifest must be valid UTF-8")
    if not isinstance(value, str):
        _raise("invalid_input_type", "$", "manifest input must be text or bytes")
    if len(value.encode("utf-8")) > limits.max_input_bytes:
        _raise("input_too_large", "$", "manifest exceeds the configured byte limit")
    return value


def _count_aliases(raw: str, limits: KubernetesManifestLimits) -> None:
    aliases = 0
    try:
        for token in yaml.scan(raw):
            if isinstance(token, AliasToken):
                aliases += 1
                if aliases > limits.max_aliases:
                    _raise("too_many_aliases", "$", "manifest exceeds the configured alias limit")
    except KubernetesManifestError:
        raise
    except yaml.YAMLError:
        _raise("invalid_yaml", "$", "manifest is not valid YAML")


def _validate_graph(root: Any, limits: KubernetesManifestLimits, document_index: int) -> None:
    """Validate a JSON-like graph without expanding shared alias subgraphs."""

    base_path = f"$documents[{document_index}]"
    stack: list[tuple[Any, str, int, bool]] = [(root, base_path, 1, False)]
    active: set[int] = set()
    seen: set[int] = set()
    node_count = 0

    while stack:
        value, path, depth, exiting = stack.pop()
        is_container = isinstance(value, (Mapping, list, tuple))
        identity = id(value) if is_container else 0

        if exiting:
            active.discard(identity)
            continue
        if depth > limits.max_depth:
            _raise("max_depth_exceeded", path, "manifest exceeds the configured depth limit")

        if is_container:
            if identity in active:
                _raise("recursive_alias", path, "recursive YAML aliases are not allowed")
            if identity in seen:
                continue
            seen.add(identity)
            active.add(identity)
            stack.append((value, path, depth, True))

        node_count += 1
        if node_count > limits.max_nodes:
            _raise("max_nodes_exceeded", base_path, "manifest exceeds the configured node limit")

        if isinstance(value, Mapping):
            entries = list(value.items())
            for index, (key, child) in reversed(list(enumerate(entries))):
                if not isinstance(key, str):
                    _raise(
                        "non_string_key", f"{path}.keys[{index}]", "mapping keys must be strings"
                    )
                if len(key) > limits.max_string_length:
                    _raise("string_too_large", f"{path}.keys[{index}]", "mapping key is too long")
                stack.append((child, f"{path}.values[{index}]", depth + 1, False))
        elif isinstance(value, (list, tuple)):
            for index in range(len(value) - 1, -1, -1):
                stack.append((value[index], f"{path}[{index}]", depth + 1, False))
        elif isinstance(value, str):
            if len(value) > limits.max_string_length:
                _raise("string_too_large", path, "scalar string is too long")
        elif isinstance(value, float):
            if not math.isfinite(value):
                _raise("non_finite_number", path, "non-finite numbers are not supported")
        elif value is not None and not isinstance(value, (bool, int)):
            _raise("unsupported_scalar", path, "manifest contains a non-JSON scalar")


def _freeze(value: Any, memo: dict[int, Any] | None = None) -> Any:
    if memo is None:
        memo = {}
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in memo:
            return memo[identity]
        frozen_values: dict[str, Any] = {}
        proxy = MappingProxyType(frozen_values)
        memo[identity] = proxy
        for key, child in value.items():
            frozen_values[key] = _freeze(child, memo)
        return proxy
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in memo:
            return memo[identity]
        frozen = tuple(_freeze(child, memo) for child in value)
        memo[identity] = frozen
        return frozen
    return value


def _identity(mapping: Mapping[str, Any], path: str) -> tuple[str, str, str, str]:
    api_version = mapping.get("apiVersion")
    kind = mapping.get("kind")
    metadata = mapping.get("metadata")
    if not isinstance(api_version, str) or not api_version.strip():
        _raise("missing_api_version", f"{path}.apiVersion", "object requires apiVersion")
    if not isinstance(kind, str) or not kind.strip():
        _raise("missing_kind", f"{path}.kind", "object requires kind")
    if not isinstance(metadata, Mapping):
        _raise("missing_metadata", f"{path}.metadata", "object requires metadata")
    name = metadata.get("name")
    namespace = metadata.get("namespace", "default")
    if not isinstance(name, str) or not name.strip():
        _raise("missing_name", f"{path}.metadata.name", "object requires metadata.name")
    if not isinstance(namespace, str) or not namespace.strip():
        _raise("invalid_namespace", f"{path}.metadata.namespace", "namespace must be text")
    return api_version.strip(), kind.strip(), namespace.strip(), name.strip()


def _secret_body(api_version: str, kind: str, namespace: str, name: str) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            "apiVersion": api_version,
            "kind": kind,
            "metadata": MappingProxyType({"namespace": namespace, "name": name}),
        }
    )


def _expand_object(
    value: Any,
    *,
    document_index: int,
    path: str,
    limits: KubernetesManifestLimits,
    objects: list[KubernetesObject],
) -> None:
    if not isinstance(value, Mapping):
        _raise("invalid_object", path, "Kubernetes object must be a mapping")
    kind_value = value.get("kind")
    if isinstance(kind_value, str) and kind_value.casefold() == "list":
        items = value.get("items")
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
            _raise("invalid_list_items", f"{path}.items", "List items must be an array")
        for index, item in enumerate(items):
            _expand_object(
                item,
                document_index=document_index,
                path=f"{path}.items[{index}]",
                limits=limits,
                objects=objects,
            )
        return

    api_version, kind, namespace, name = _identity(value, path)
    if len(objects) >= limits.max_objects:
        _raise("too_many_objects", path, "manifest exceeds the configured object limit")
    if kind.casefold() == "secret":
        body = _secret_body(api_version, kind, namespace, name)
    else:
        body = _freeze(value)
    objects.append(
        KubernetesObject(
            api_version=api_version,
            kind=kind,
            namespace=namespace,
            name=name,
            document_index=document_index,
            body=body,
        )
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else MappingProxyType({})


def _pod_spec(obj: KubernetesObject) -> Mapping[str, Any]:
    spec = _mapping(obj.body.get("spec"))
    if obj.kind.casefold() == "cronjob":
        job_template = _mapping(spec.get("jobTemplate"))
        spec = _mapping(job_template.get("spec"))
    template = _mapping(spec.get("template"))
    return _mapping(template.get("spec"))


def _count_containers(
    objects: Sequence[KubernetesObject], limits: KubernetesManifestLimits
) -> None:
    total = 0
    for obj in objects:
        if obj.kind.casefold() not in {"deployment", "statefulset", "daemonset", "job", "cronjob"}:
            continue
        pod_spec = _pod_spec(obj)
        for field in ("containers", "initContainers"):
            value = pod_spec.get(field)
            if value is None:
                continue
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                _raise(
                    "invalid_container_list",
                    f"{obj.resource}.spec.{field}",
                    "container collection must be an array",
                )
            for index, container in enumerate(value):
                if not isinstance(container, Mapping):
                    _raise(
                        "invalid_container",
                        f"{obj.resource}.spec.{field}[{index}]",
                        "container must be a mapping",
                    )
                name = container.get("name")
                if not isinstance(name, str) or not name.strip():
                    _raise(
                        "missing_container_name",
                        f"{obj.resource}.spec.{field}[{index}].name",
                        "container requires a name",
                    )
            total += len(value)
            if total > limits.max_containers:
                _raise(
                    "too_many_containers",
                    "$objects",
                    "manifest exceeds the configured container limit",
                )


def parse_kubernetes_manifests(
    value: str | bytes,
    *,
    limits: KubernetesManifestLimits = DEFAULT_KUBERNETES_MANIFEST_LIMITS,
) -> tuple[KubernetesObject, ...]:
    """Parse and normalize Kubernetes YAML without emitting partial results."""

    raw = _input_text(value, limits)
    if not raw.strip():
        return ()
    _count_aliases(raw, limits)

    documents: list[Any] = []
    try:
        for index, document in enumerate(yaml.load_all(raw, Loader=_StrictSafeLoader)):
            if index >= limits.max_documents:
                _raise("too_many_documents", "$", "manifest exceeds the configured document limit")
            _validate_graph(document, limits, index)
            documents.append(document)
    except KubernetesManifestError:
        raise
    except _LoaderViolation as exc:
        _raise(exc.code, "$", exc.safe_message)
    except yaml.YAMLError:
        _raise("invalid_yaml", "$", "manifest is not valid YAML")

    objects: list[KubernetesObject] = []
    for index, document in enumerate(documents):
        if document is None:
            continue
        _expand_object(
            document,
            document_index=index,
            path=f"$documents[{index}]",
            limits=limits,
            objects=objects,
        )

    identities: set[tuple[str, str, str, str]] = set()
    for obj in objects:
        identity = (obj.api_version, obj.kind.casefold(), obj.namespace, obj.name)
        if identity in identities:
            _raise("duplicate_object", obj.resource, "duplicate Kubernetes object identity")
        identities.add(identity)
    _count_containers(objects, limits)
    return tuple(
        sorted(
            objects,
            key=lambda obj: (
                obj.kind.casefold(),
                obj.namespace,
                obj.name,
                obj.api_version,
                obj.document_index,
            ),
        )
    )


def _finding(
    obj: KubernetesObject,
    rule_id: str,
    description: str,
    severity: str,
    score: int,
    field: str,
    predicate: str,
    *,
    container: str | None = None,
) -> dict[str, Any]:
    evidence: dict[str, str] = {"field": field, "predicate": predicate}
    finding: dict[str, Any] = {
        "id": rule_id,
        "description": description,
        "severity": severity,
        "score": score,
        "source": SOURCE_KUBERNETES,
        "resource": obj.resource,
        "object_ref": obj.object_ref,
        "evidence": evidence,
    }
    if container:
        finding["container"] = container
        evidence["container"] = container
    return finding


def _is_all_unavailable(value: Any) -> bool:
    return isinstance(value, str) and value.strip() == "100%"


def _is_integer_zero(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def _is_zero_available(value: Any) -> bool:
    return _is_integer_zero(value) or (isinstance(value, str) and value.strip() in {"0", "0%"})


def _containers(obj: KubernetesObject) -> Iterable[tuple[str, str, Mapping[str, Any]]]:
    pod_spec = _pod_spec(obj)
    for collection_name in ("containers", "initContainers"):
        values = pod_spec.get(collection_name, ())
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            continue
        for index, value in enumerate(values):
            container = _mapping(value)
            name = container.get("name")
            label = name if isinstance(name, str) and name else f"{collection_name}[{index}]"
            yield collection_name, label, container


def _workload_findings(obj: KubernetesObject) -> list[dict[str, Any]]:
    kind = obj.kind.casefold()
    if kind not in {"deployment", "statefulset", "daemonset", "job", "cronjob"}:
        return []
    findings: list[dict[str, Any]] = []
    pod_spec = _pod_spec(obj)
    container_rows = list(_containers(obj))
    app_containers = [row for row in container_rows if row[0] == "containers"]
    if not app_containers:
        findings.append(
            _finding(
                obj,
                "kubernetes-missing-containers",
                f"{obj.resource} does not define application containers",
                "high",
                20,
                "spec.template.spec.containers",
                "missing_or_empty",
            )
        )

    for collection, container_name, container in container_rows:
        base_field = (
            "spec.jobTemplate.spec.template.spec" if kind == "cronjob" else "spec.template.spec"
        )
        base_field = f"{base_field}.{collection}[name={container_name}]"
        if collection == "containers" and kind in {"deployment", "statefulset", "daemonset"}:
            if "readinessProbe" not in container:
                findings.append(
                    _finding(
                        obj,
                        "kubernetes-missing-readiness-probe",
                        f"{obj.resource} container {container_name} does not define readinessProbe",
                        "medium",
                        15,
                        f"{base_field}.readinessProbe",
                        "missing",
                        container=container_name,
                    )
                )
            if "livenessProbe" not in container:
                findings.append(
                    _finding(
                        obj,
                        "kubernetes-missing-liveness-probe",
                        f"{obj.resource} container {container_name} does not define livenessProbe",
                        "medium",
                        15,
                        f"{base_field}.livenessProbe",
                        "missing",
                        container=container_name,
                    )
                )
        resources = _mapping(container.get("resources"))
        requests = resources.get("requests")
        limits = resources.get("limits")
        if not isinstance(requests, Mapping) or not requests:
            findings.append(
                _finding(
                    obj,
                    "kubernetes-missing-resource-requests",
                    f"{obj.resource} container {container_name} has no resource requests",
                    "medium",
                    10,
                    f"{base_field}.resources.requests",
                    "missing_or_empty",
                    container=container_name,
                )
            )
        if not isinstance(limits, Mapping) or not limits:
            findings.append(
                _finding(
                    obj,
                    "kubernetes-missing-resource-limits",
                    f"{obj.resource} container {container_name} has no resource limits",
                    "medium",
                    10,
                    f"{base_field}.resources.limits",
                    "missing_or_empty",
                    container=container_name,
                )
            )
        security_context = _mapping(container.get("securityContext"))
        if security_context.get("privileged") is True:
            findings.append(
                _finding(
                    obj,
                    "kubernetes-privileged-container",
                    f"{obj.resource} container {container_name} is privileged",
                    "critical",
                    40,
                    f"{base_field}.securityContext.privileged",
                    "equals_true",
                    container=container_name,
                )
            )
        if security_context.get("allowPrivilegeEscalation") is True:
            findings.append(
                _finding(
                    obj,
                    "kubernetes-privilege-escalation",
                    f"{obj.resource} container {container_name} allows privilege escalation",
                    "high",
                    25,
                    f"{base_field}.securityContext.allowPrivilegeEscalation",
                    "equals_true",
                    container=container_name,
                )
            )

    for field_name, rule_id, label in (
        ("hostNetwork", "kubernetes-host-network", "host networking"),
        ("hostPID", "kubernetes-host-pid", "host PID namespace"),
        ("hostIPC", "kubernetes-host-ipc", "host IPC namespace"),
    ):
        if pod_spec.get(field_name) is True:
            base_field = (
                "spec.jobTemplate.spec.template.spec" if kind == "cronjob" else "spec.template.spec"
            )
            findings.append(
                _finding(
                    obj,
                    rule_id,
                    f"{obj.resource} uses {label}",
                    "high",
                    25,
                    f"{base_field}.{field_name}",
                    "equals_true",
                )
            )
    return findings


_KIND_RULES: dict[str, tuple[str, int, str, str]] = {
    "deployment": (
        "kubernetes-deployment-change",
        10,
        "medium",
        "Kubernetes Deployment change detected",
    ),
    "statefulset": (
        "kubernetes-statefulset-change",
        20,
        "high",
        "Kubernetes StatefulSet change detected",
    ),
    "daemonset": (
        "kubernetes-daemonset-change",
        20,
        "high",
        "Kubernetes DaemonSet change detected",
    ),
    "job": ("kubernetes-job-change", 10, "medium", "Kubernetes Job change detected"),
    "cronjob": (
        "kubernetes-cronjob-change",
        10,
        "medium",
        "Kubernetes CronJob change detected",
    ),
    "ingress": (
        "kubernetes-ingress-change",
        25,
        "high",
        "Kubernetes Ingress change detected",
    ),
    "networkpolicy": (
        "kubernetes-networkpolicy-change",
        25,
        "high",
        "Kubernetes NetworkPolicy change detected",
    ),
    "secret": (
        "kubernetes-secret-change",
        25,
        "high",
        "Kubernetes Secret change detected",
    ),
}


def _object_findings(obj: KubernetesObject) -> list[dict[str, Any]]:
    kind = obj.kind.casefold()
    findings: list[dict[str, Any]] = []
    spec = _mapping(obj.body.get("spec"))

    if kind in _KIND_RULES:
        rule_id, score, severity, description = _KIND_RULES[kind]
        findings.append(
            _finding(obj, rule_id, description, severity, score, "kind", f"equals_{kind}")
        )

    if kind == "service":
        service_type = spec.get("type")
        if service_type == "LoadBalancer":
            findings.append(
                _finding(
                    obj,
                    "kubernetes-loadbalancer-exposure",
                    f"LoadBalancer exposure detected: {obj.resource}",
                    "high",
                    25,
                    "spec.type",
                    "equals_LoadBalancer",
                )
            )
        elif service_type == "NodePort":
            findings.append(
                _finding(
                    obj,
                    "kubernetes-nodeport-exposure",
                    f"NodePort exposure detected: {obj.resource}",
                    "high",
                    25,
                    "spec.type",
                    "equals_NodePort",
                )
            )
        external_ips = spec.get("externalIPs")
        if isinstance(external_ips, Sequence) and not isinstance(external_ips, (str, bytes)):
            if external_ips:
                findings.append(
                    _finding(
                        obj,
                        "kubernetes-service-external-ips",
                        f"External IP routing is configured: {obj.resource}",
                        "high",
                        25,
                        "spec.externalIPs",
                        "non_empty",
                    )
                )

    if kind in {"deployment", "statefulset", "replicaset"} and _is_integer_zero(
        spec.get("replicas")
    ):
        findings.append(
            _finding(
                obj,
                "kubernetes-replicas-zero",
                f"Replicas set to zero: {obj.resource}",
                "high",
                30,
                "spec.replicas",
                "equals_zero",
            )
        )

    if kind == "deployment":
        strategy = _mapping(spec.get("strategy"))
        if strategy.get("type") == "Recreate":
            findings.append(
                _finding(
                    obj,
                    "kubernetes-recreate-strategy",
                    f"Recreate strategy configured: {obj.resource}",
                    "high",
                    20,
                    "spec.strategy.type",
                    "equals_Recreate",
                )
            )
        rolling = _mapping(strategy.get("rollingUpdate"))
        if _is_all_unavailable(rolling.get("maxUnavailable")):
            findings.append(
                _finding(
                    obj,
                    "kubernetes-max-unavailable-all",
                    f"Rolling update permits all replicas unavailable: {obj.resource}",
                    "high",
                    30,
                    "spec.strategy.rollingUpdate.maxUnavailable",
                    "equals_100_percent",
                )
            )

    if kind in {"statefulset", "daemonset"}:
        update_strategy = _mapping(spec.get("updateStrategy"))
        if update_strategy.get("type") == "OnDelete":
            findings.append(
                _finding(
                    obj,
                    "kubernetes-ondelete-strategy",
                    f"OnDelete update strategy configured: {obj.resource}",
                    "medium",
                    15,
                    "spec.updateStrategy.type",
                    "equals_OnDelete",
                )
            )

    if kind in {"job", "cronjob"} and spec.get("suspend") is True:
        findings.append(
            _finding(
                obj,
                "kubernetes-workload-suspended",
                f"Workload is suspended: {obj.resource}",
                "high",
                20,
                "spec.suspend",
                "equals_true",
            )
        )
    if kind == "job" and _is_integer_zero(spec.get("parallelism")):
        findings.append(
            _finding(
                obj,
                "kubernetes-parallelism-zero",
                f"Job parallelism is zero: {obj.resource}",
                "high",
                20,
                "spec.parallelism",
                "equals_zero",
            )
        )

    if kind == "poddisruptionbudget":
        if _is_all_unavailable(spec.get("maxUnavailable")):
            findings.append(
                _finding(
                    obj,
                    "kubernetes-pdb-no-protection",
                    f"PodDisruptionBudget permits all pods unavailable: {obj.resource}",
                    "high",
                    25,
                    "spec.maxUnavailable",
                    "equals_100_percent",
                )
            )
        if _is_zero_available(spec.get("minAvailable")):
            findings.append(
                _finding(
                    obj,
                    "kubernetes-pdb-no-protection",
                    f"PodDisruptionBudget requires no pods available: {obj.resource}",
                    "high",
                    25,
                    "spec.minAvailable",
                    "equals_zero",
                )
            )

    findings.extend(_workload_findings(obj))
    return findings


def scan_kubernetes(
    value: str | bytes | None,
    *,
    limits: KubernetesManifestLimits = DEFAULT_KUBERNETES_MANIFEST_LIMITS,
) -> list[dict[str, Any]]:
    """Return deterministic structural findings for Kubernetes YAML.

    Invalid or incomplete input raises :class:`KubernetesManifestError`; it is
    never reinterpreted as text.
    """

    if value is None or value == "" or value == b"":
        return []
    objects = parse_kubernetes_manifests(value, limits=limits)
    findings = [finding for obj in objects for finding in _object_findings(obj)]
    return sorted(
        findings,
        key=lambda finding: (
            finding["object_ref"]["kind"].casefold(),
            finding["object_ref"]["namespace"],
            finding["object_ref"]["name"],
            finding["id"],
            finding["evidence"]["field"],
            finding.get("container", ""),
        ),
    )


def scan_kubernetes_legacy(value: Any) -> list[dict[str, Any]]:
    """Run the deprecated global keyword scanner by explicit request only."""

    if not value:
        return []
    text = str(value)
    lowered = text.lower()
    findings: list[dict[str, Any]] = []
    for keyword, rule_id, score, severity, description in KUBERNETES_SIGNALS:
        if keyword in lowered:
            findings.append(
                {
                    "id": rule_id,
                    "description": description,
                    "severity": severity,
                    "score": score,
                    "source": SOURCE_KUBERNETES,
                }
            )
    if "kind: deployment" in lowered:
        if "readinessprobe" not in lowered:
            findings.append(
                {
                    "id": "kubernetes-missing-readiness-probe",
                    "description": "Deployment does not define readinessProbe",
                    "severity": "medium",
                    "score": 15,
                    "source": SOURCE_KUBERNETES,
                }
            )
        if "livenessprobe" not in lowered:
            findings.append(
                {
                    "id": "kubernetes-missing-liveness-probe",
                    "description": "Deployment does not define livenessProbe",
                    "severity": "medium",
                    "score": 15,
                    "source": SOURCE_KUBERNETES,
                }
            )
    return findings


__all__ = [
    "DEFAULT_KUBERNETES_MANIFEST_LIMITS",
    "KUBERNETES_SIGNALS",
    "KubernetesManifestError",
    "KubernetesManifestLimits",
    "KubernetesObject",
    "parse_kubernetes_manifests",
    "scan_kubernetes",
    "scan_kubernetes_legacy",
]

"""Structured and legacy infrastructure risk scanners.

Terraform JSON plans and Kubernetes YAML are parsed into objects whenever
possible. The text scanners remain as a compatibility fallback for existing
callers and for human-readable plan output.
"""

from collections.abc import Iterable
from typing import Any

import yaml

from .terraform_plan import scan_terraform_json as scan_terraform_json

# (keyword, rule_id, score, severity, description)
TERRAFORM_SIGNALS = [
    ("aws_iam_policy", "terraform-iam-policy-change", 30, "high", "IAM policy change detected"),
    ("aws_iam_role", "terraform-iam-role-change", 30, "high", "IAM role change detected"),
    (
        "google_project_iam_member",
        "terraform-gcp-iam-member-change",
        30,
        "high",
        "GCP IAM member change detected",
    ),
    (
        "security_group",
        "terraform-security-group-change",
        25,
        "high",
        "Security group change detected",
    ),
    ("firewall", "terraform-firewall-change", 25, "high", "Firewall rule change detected"),
    (
        "db_instance",
        "terraform-db-instance-change",
        25,
        "high",
        "Database instance change detected",
    ),
    (
        "database",
        "terraform-database-change",
        25,
        "high",
        "Database-related infrastructure change detected",
    ),
    ("delete", "terraform-delete-action", 30, "high", "Delete action detected"),
    ("destroy", "terraform-destroy-action", 40, "critical", "Destroy action detected"),
    ("public_ip", "terraform-public-ip-exposure", 25, "high", "Public IP exposure detected"),
    ("bucket", "terraform-bucket-change", 20, "medium", "Storage bucket change detected"),
    ("kms", "terraform-kms-change", 25, "high", "KMS/security key change detected"),
    ("dns", "terraform-dns-change", 25, "high", "DNS change detected"),
]

# Retained as a public compatibility contract for callers that import it.
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

SOURCE_TERRAFORM = "Terraform"
SOURCE_KUBERNETES = "Kubernetes"


def _finding(rule_id, description, severity, score, source, **evidence):
    finding = {
        "id": rule_id,
        "description": description,
        "severity": severity,
        "score": score,
        "source": source,
    }
    finding.update({key: value for key, value in evidence.items() if value not in (None, "")})
    return finding


def scan_terraform(text) -> list:
    """Scan human-readable Terraform plan/diff text for risky signals."""
    findings: list[dict] = []
    if not text:
        return findings
    lowered = str(text).lower()
    for keyword, rule_id, score, severity, description in TERRAFORM_SIGNALS:
        if keyword in lowered:
            findings.append(_finding(rule_id, description, severity, score, SOURCE_TERRAFORM))
    return findings


def _legacy_kubernetes_scan(text: str) -> list:
    lowered = text.lower()
    findings = []
    for keyword, rule_id, score, severity, description in KUBERNETES_SIGNALS:
        if keyword in lowered:
            findings.append(_finding(rule_id, description, severity, score, SOURCE_KUBERNETES))
    if "kind: deployment" in lowered:
        if "readinessprobe" not in lowered:
            findings.append(
                _finding(
                    "kubernetes-missing-readiness-probe",
                    "Deployment does not define readinessProbe",
                    "medium",
                    15,
                    SOURCE_KUBERNETES,
                )
            )
        if "livenessprobe" not in lowered:
            findings.append(
                _finding(
                    "kubernetes-missing-liveness-probe",
                    "Deployment does not define livenessProbe",
                    "medium",
                    15,
                    SOURCE_KUBERNETES,
                )
            )
    return findings


def _k8s_objects(documents: Iterable[Any]) -> Iterable[dict]:
    for document in documents:
        if not isinstance(document, dict):
            continue
        if str(document.get("kind", "")).lower() == "list":
            yield from _k8s_objects(document.get("items", []))
        else:
            yield document


def _pod_spec(obj: dict) -> dict:
    spec = obj.get("spec") or {}
    template = spec.get("template") or {} if isinstance(spec, dict) else {}
    pod_spec = template.get("spec") or {} if isinstance(template, dict) else {}
    return pod_spec if isinstance(pod_spec, dict) else {}


def scan_kubernetes(text) -> list:
    """Parse Kubernetes YAML and detect risks independently per object."""
    if not text:
        return []
    raw = str(text)
    try:
        objects = list(_k8s_objects(yaml.safe_load_all(raw)))
    except yaml.YAMLError:
        return _legacy_kubernetes_scan(raw)
    if not objects or not any("kind" in obj for obj in objects):
        return _legacy_kubernetes_scan(raw)

    findings: list[dict] = []
    kind_rules = {
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
        "ingress": ("kubernetes-ingress-change", 25, "high", "Kubernetes Ingress change detected"),
        "networkpolicy": (
            "kubernetes-networkpolicy-change",
            25,
            "high",
            "Kubernetes NetworkPolicy change detected",
        ),
        "secret": ("kubernetes-secret-change", 25, "high", "Kubernetes Secret change detected"),
    }
    for obj in objects:
        kind = str(obj.get("kind") or "").lower()
        metadata = obj.get("metadata") or {}
        name = str(metadata.get("name") or "unnamed") if isinstance(metadata, dict) else "unnamed"
        resource = f"{kind or 'object'}/{name}"
        spec = obj.get("spec") or {}
        if not isinstance(spec, dict):
            spec = {}
        if kind in kind_rules:
            rule_id, score, severity, description = kind_rules[kind]
            findings.append(
                _finding(
                    rule_id, description, severity, score, SOURCE_KUBERNETES, resource=resource
                )
            )
        if kind == "service" and str(spec.get("type", "")).lower() == "loadbalancer":
            findings.append(
                _finding(
                    "kubernetes-loadbalancer-exposure",
                    f"LoadBalancer exposure detected: {resource}",
                    "high",
                    25,
                    SOURCE_KUBERNETES,
                    resource=resource,
                )
            )
        if spec.get("replicas") == 0 and kind in {"deployment", "statefulset", "replicaset"}:
            findings.append(
                _finding(
                    "kubernetes-replicas-zero",
                    f"Replicas set to zero: {resource}",
                    "high",
                    30,
                    SOURCE_KUBERNETES,
                    resource=resource,
                )
            )
        if kind in {"deployment", "statefulset", "daemonset"}:
            containers = _pod_spec(obj).get("containers", [])
            if not isinstance(containers, list) or not containers:
                # Compatibility for the MVP's historical manifest snippets,
                # which placed probe keys directly on the document.
                containers = [obj] if ("readinessProbe" in obj or "livenessProbe" in obj) else [{}]
            for index, container in enumerate(containers):
                if not isinstance(container, dict):
                    container = {}
                container_name = str(container.get("name") or f"container-{index + 1}")
                evidence = {"resource": resource, "container": container_name}
                if "readinessProbe" not in container:
                    findings.append(
                        _finding(
                            "kubernetes-missing-readiness-probe",
                            f"{resource} container {container_name} does not define readinessProbe",
                            "medium",
                            15,
                            SOURCE_KUBERNETES,
                            **evidence,
                        )
                    )
                if "livenessProbe" not in container:
                    findings.append(
                        _finding(
                            "kubernetes-missing-liveness-probe",
                            f"{resource} container {container_name} does not define livenessProbe",
                            "medium",
                            15,
                            SOURCE_KUBERNETES,
                            **evidence,
                        )
                    )
                resources = container.get("resources") or {}
                requests = resources.get("requests") if isinstance(resources, dict) else None
                limits = resources.get("limits") if isinstance(resources, dict) else None
                if not requests:
                    findings.append(
                        _finding(
                            "kubernetes-missing-resource-requests",
                            f"{resource} container {container_name} has no resource requests",
                            "medium",
                            10,
                            SOURCE_KUBERNETES,
                            **evidence,
                        )
                    )
                if not limits:
                    findings.append(
                        _finding(
                            "kubernetes-missing-resource-limits",
                            f"{resource} container {container_name} has no resource limits",
                            "medium",
                            10,
                            SOURCE_KUBERNETES,
                            **evidence,
                        )
                    )
    return findings

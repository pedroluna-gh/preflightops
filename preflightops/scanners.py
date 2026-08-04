"""Keyword-based risk scanners for Terraform plans and Kubernetes manifests.

These are intentionally simple for the MVP: they look for known risky
keywords in pasted text rather than parsing real Terraform JSON or Kubernetes
objects. Each finding is returned in the same shape as a risk-engine rule so it
can be merged into the overall assessment.
"""

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

# (keyword, rule_id, score, severity, description) — keyword matched case-insensitively
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


def _finding(rule_id, description, severity, score, source):
    return {
        "id": rule_id,
        "description": description,
        "severity": severity,
        "score": score,
        "source": source,
    }


def scan_terraform(text) -> list:
    """Scan pasted Terraform plan/diff text for risky keywords."""
    findings: list[dict] = []
    if not text:
        return findings

    lowered = str(text).lower()
    for keyword, rule_id, score, severity, description in TERRAFORM_SIGNALS:
        if keyword in lowered:
            findings.append(_finding(rule_id, description, severity, score, SOURCE_TERRAFORM))

    return findings


def scan_kubernetes(text) -> list:
    """Scan pasted Kubernetes manifest text for risky keywords."""
    findings: list[dict] = []
    if not text:
        return findings

    lowered = str(text).lower()

    for keyword, rule_id, score, severity, description in KUBERNETES_SIGNALS:
        if keyword in lowered:
            findings.append(_finding(rule_id, description, severity, score, SOURCE_KUBERNETES))

    # Special validation: a Deployment with no health probes is risky.
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

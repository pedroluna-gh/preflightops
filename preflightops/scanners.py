"""Structured and legacy infrastructure risk scanners."""

from .kubernetes_manifest import (
    KUBERNETES_SIGNALS as KUBERNETES_SIGNALS,
)
from .kubernetes_manifest import (
    scan_kubernetes as scan_kubernetes,
)
from .kubernetes_manifest import (
    scan_kubernetes_legacy as scan_kubernetes_legacy,
)
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

SOURCE_TERRAFORM = "Terraform"


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

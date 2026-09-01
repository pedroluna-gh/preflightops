"""PreflightOps: pre-deployment risk assessment for SRE and Platform teams."""

from ._version import __version__ as __version__
from .assessment import (
    AssessmentContext,
    AssessmentContractError,
    ControlObservation,
    HumanDecision,
    InputDigest,
    PolicyIdentity,
    TrustKernel,
    WaiverReference,
    adapt_legacy_assessment,
    serialize_assessment_v1,
    validate_assessment_v1,
)
from .changed_files import classify_changed_files, load_changed_files
from .evidence import (
    EvidenceError,
    build_statement_v2,
    generate_evidence_v2,
    verify_evidence_v2,
)
from .integrations import (
    IntegrationError,
    build_servicenow_evidence,
    correlation_id,
    load_servicenow_mapping,
    prepare_servicenow_payload,
    push_to_jira,
    push_to_servicenow,
    validate_servicenow_instance_url,
)
from .monitoring import validate_monitoring_evidence
from .policy import load_policy_pack
from .report import (
    generate_github_comment,
    generate_html_report,
    generate_json_report,
    generate_markdown_report,
)
from .risk_engine import (
    RECOMMENDATIONS,
    RISK_LEVELS,
    assess_risk,
    find_service,
    score_to_level,
)
from .scanners import scan_kubernetes, scan_terraform, scan_terraform_json
from .ticket import generate_ticket_markdown
from .validators import (
    is_bad_rollback_plan,
    is_monitoring_plan_incomplete,
    is_validation_plan_valid,
)

__all__ = [
    "AssessmentContext",
    "AssessmentContractError",
    "ControlObservation",
    "HumanDecision",
    "InputDigest",
    "PolicyIdentity",
    "TrustKernel",
    "WaiverReference",
    "adapt_legacy_assessment",
    "serialize_assessment_v1",
    "validate_assessment_v1",
    "assess_risk",
    "find_service",
    "RISK_LEVELS",
    "RECOMMENDATIONS",
    "score_to_level",
    "is_bad_rollback_plan",
    "is_monitoring_plan_incomplete",
    "is_validation_plan_valid",
    "scan_terraform",
    "scan_terraform_json",
    "scan_kubernetes",
    "load_policy_pack",
    "validate_monitoring_evidence",
    "generate_markdown_report",
    "generate_json_report",
    "generate_github_comment",
    "generate_html_report",
    "classify_changed_files",
    "load_changed_files",
    "generate_ticket_markdown",
    "push_to_servicenow",
    "prepare_servicenow_payload",
    "build_servicenow_evidence",
    "load_servicenow_mapping",
    "validate_servicenow_instance_url",
    "push_to_jira",
    "correlation_id",
    "IntegrationError",
    "EvidenceError",
    "build_statement_v2",
    "generate_evidence_v2",
    "verify_evidence_v2",
]


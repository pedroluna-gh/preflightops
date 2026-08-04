"""PreflightOps: pre-deployment risk assessment for SRE and Platform teams."""

from ._version import __version__

from .risk_engine import (
    assess_risk,
    find_service,
    RISK_LEVELS,
    RECOMMENDATIONS,
    score_to_level,
)
from .validators import (
    is_bad_rollback_plan,
    is_monitoring_plan_incomplete,
    is_validation_plan_valid,
)
from .scanners import scan_terraform, scan_kubernetes
from .report import generate_markdown_report, generate_json_report
from .ticket import generate_ticket_markdown
from .integrations import (
    push_to_servicenow,
    push_to_jira,
    correlation_id,
    IntegrationError,
)

__all__ = [
    "assess_risk",
    "find_service",
    "RISK_LEVELS",
    "RECOMMENDATIONS",
    "score_to_level",
    "is_bad_rollback_plan",
    "is_monitoring_plan_incomplete",
    "is_validation_plan_valid",
    "scan_terraform",
    "scan_kubernetes",
    "generate_markdown_report",
    "generate_json_report",
    "generate_ticket_markdown",
    "push_to_servicenow",
    "push_to_jira",
    "correlation_id",
    "IntegrationError",
]

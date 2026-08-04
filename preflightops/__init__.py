"""PreflightOps: pre-deployment risk assessment for SRE and Platform teams."""

from ._version import __version__ as __version__
from .integrations import (
    IntegrationError,
    correlation_id,
    push_to_jira,
    push_to_servicenow,
)
from .report import generate_json_report, generate_markdown_report
from .risk_engine import (
    RECOMMENDATIONS,
    RISK_LEVELS,
    assess_risk,
    find_service,
    score_to_level,
)
from .scanners import scan_kubernetes, scan_terraform
from .ticket import generate_ticket_markdown
from .validators import (
    is_bad_rollback_plan,
    is_monitoring_plan_incomplete,
    is_validation_plan_valid,
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

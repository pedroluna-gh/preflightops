"""Core risk assessment engine for PreflightOps.

The engine combines:
  * declarative rules over the service catalog and change request, and
  * findings from the Terraform and Kubernetes scanners,
into a single 0-100 risk score with a level, recommendation, triggered rules,
and a list of missing operational controls.
"""

from typing import Optional

from .monitoring import validate_monitoring_evidence
from .policy import load_policy_pack, resolve_policy
from .scanners import scan_kubernetes, scan_terraform, scan_terraform_json
from .validators import (
    is_bad_rollback_plan,
    is_monitoring_plan_incomplete,
    is_validation_plan_valid,
)

MAX_SCORE = 100

# Categories used to group triggered findings by where they came from.
SOURCE_SERVICE_CONTROLS = "Service Controls"
SOURCE_CHANGE_TYPE = "Change Type"
SOURCE_TERRAFORM = "Terraform"
SOURCE_KUBERNETES = "Kubernetes"
SOURCE_OBSERVABILITY = "Observability"

# Display order for grouped breakdowns.
SOURCE_ORDER = [
    SOURCE_SERVICE_CONTROLS,
    SOURCE_CHANGE_TYPE,
    SOURCE_TERRAFORM,
    SOURCE_KUBERNETES,
    SOURCE_OBSERVABILITY,
]
# Risk level thresholds (inclusive upper bounds except CRITICAL).
RISK_LEVELS = [
    (30, "LOW"),
    (60, "MEDIUM"),
    (80, "HIGH"),
    (100, "CRITICAL"),
]

RECOMMENDATIONS = {
    "LOW": "Change appears low risk. Proceed with normal deployment process.",
    "MEDIUM": "Proceed with caution. Ensure service owner review and post-deploy validation.",
    "HIGH": "Senior review recommended before deployment. Address missing controls before proceeding.",
    "CRITICAL": "Deployment should be blocked until rollback, monitoring, ownership, or validation gaps are resolved.",
}


def score_to_level(score: int, thresholds: Optional[dict] = None) -> str:
    """Map a numeric score to a risk level label."""
    if thresholds:
        if score <= thresholds["low"]:
            return "LOW"
        if score <= thresholds["medium"]:
            return "MEDIUM"
        if score <= thresholds["high"]:
            return "HIGH"
        return "CRITICAL"
    for upper_bound, level in RISK_LEVELS:
        if score <= upper_bound:
            return level
    return "CRITICAL"


def find_service(services, service_name):
    """Return the service dict matching ``service_name`` from a catalog.

    ``services`` is the parsed service-catalog document, expected to contain a
    top-level ``services`` list. Raises ``ValueError`` with a clear message when
    the catalog is malformed or the service cannot be found.
    """
    if not isinstance(services, dict) or "services" not in services:
        raise ValueError(
            "Service catalog must be a YAML document with a top-level 'services' list."
        )

    service_list = services.get("services")
    if not isinstance(service_list, list):
        raise ValueError("'services' must be a list of service definitions.")

    for service in service_list:
        if isinstance(service, dict) and service.get("name") == service_name:
            return service

    raise ValueError(f"Service '{service_name}' was not found in the service catalog.")


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def _rule(triggered, rule_id, description, severity, score, source):
    triggered.append(
        {
            "id": rule_id,
            "description": description,
            "severity": severity,
            "score": score,
            "source": source,
        }
    )


def assess_risk(
    services,
    change_doc,
    terraform_text="",
    k8s_text="",
    *,
    terraform_json=None,
    policy=None,
    monitor_inventory=None,
):
    """Run the full risk assessment.

    Parameters
    ----------
    services : dict
        Parsed service catalog (``{"services": [...]}``).
    change_doc : dict
        Parsed change request (``{"change": {...}}``).
    terraform_text : str
        Optional pasted Terraform plan / diff text.
    k8s_text : str
        Optional pasted Kubernetes manifest text.

    Returns
    -------
    dict
        The risk result object.
    """
    if not isinstance(change_doc, dict) or "change" not in change_doc:
        raise ValueError("Change request must be a YAML document with a top-level 'change' object.")

    change = change_doc.get("change") or {}
    if not isinstance(change, dict):
        raise ValueError("'change' must be a mapping of change request fields.")

    service_name = change.get("service")
    if not service_name:
        raise ValueError("Change request is missing a 'service' field.")

    # Raises a clear error if the service is unknown.
    service = find_service(services, service_name)

    environment = change.get("environment", "")
    change_type = change.get("change_type", "")

    triggered: list[dict] = []
    missing_controls: list[str] = []

    # 1. production-change
    if environment == "production":
        _rule(
            triggered,
            "production-change",
            "Change targets production environment",
            "medium",
            20,
            SOURCE_SERVICE_CONTROLS,
        )

    # 2. critical-service
    criticality = (service.get("criticality") or "").lower()
    if criticality in ("high", "critical"):
        _rule(
            triggered,
            "critical-service",
            "Service is marked as high or critical",
            "high",
            25,
            SOURCE_SERVICE_CONTROLS,
        )

    # 3. missing-owner
    if _is_empty(service.get("owner")):
        _rule(
            triggered,
            "missing-owner",
            "Service owner is missing",
            "high",
            25,
            SOURCE_SERVICE_CONTROLS,
        )
        missing_controls.append("service_owner")

    # 4. missing-runbook
    if _is_empty(service.get("runbook")):
        _rule(
            triggered,
            "missing-runbook",
            "Service runbook is missing",
            "medium",
            15,
            SOURCE_SERVICE_CONTROLS,
        )
        missing_controls.append("runbook")

    # 5. missing-business-impact
    if _is_empty(service.get("business_impact")):
        _rule(
            triggered,
            "missing-business-impact",
            "Business impact statement is missing",
            "medium",
            10,
            SOURCE_SERVICE_CONTROLS,
        )
        missing_controls.append("business_impact")

    # 6. missing-rollback-plan (production only)
    if environment == "production" and is_bad_rollback_plan(change.get("rollback_plan")):
        _rule(
            triggered,
            "missing-rollback-plan",
            "Production change has no valid rollback plan",
            "high",
            30,
            SOURCE_SERVICE_CONTROLS,
        )
        missing_controls.append("rollback_plan")

    # 7. missing-monitoring-plan
    if is_monitoring_plan_incomplete(change.get("monitoring_plan")):
        _rule(
            triggered,
            "missing-monitoring-plan",
            "No monitoring plan defined",
            "medium",
            20,
            SOURCE_SERVICE_CONTROLS,
        )
        missing_controls.append("monitoring_plan")

    # 8. missing-validation-plan
    if not is_validation_plan_valid(change.get("validation_plan")):
        _rule(
            triggered,
            "missing-validation-plan",
            "Post-deploy validation plan is missing",
            "medium",
            15,
            SOURCE_SERVICE_CONTROLS,
        )
        missing_controls.append("validation_plan")

    # 9-12. change-type rules
    if change_type == "database":
        _rule(
            triggered, "database-change", "Database change detected", "high", 25, SOURCE_CHANGE_TYPE
        )
    elif change_type == "security":
        _rule(
            triggered,
            "security-change",
            "Security-related change detected",
            "high",
            25,
            SOURCE_CHANGE_TYPE,
        )
    elif change_type == "network":
        _rule(
            triggered,
            "network-change",
            "Network-related change detected",
            "high",
            25,
            SOURCE_CHANGE_TYPE,
        )
    elif change_type == "infrastructure":
        _rule(
            triggered,
            "infrastructure-change",
            "Infrastructure change detected",
            "medium",
            20,
            SOURCE_CHANGE_TYPE,
        )

    # Scanner and evidence-provider findings.
    triggered.extend(scan_terraform(terraform_text))
    triggered.extend(scan_terraform_json(terraform_json))
    triggered.extend(scan_kubernetes(k8s_text))

    policy_context = {
        "environment": str(environment or ""),
        "tier": str(service.get("tier") or service.get("criticality") or ""),
        "change_class": str(change.get("change_class") or change.get("classification") or "normal"),
        "change_type": str(change_type or ""),
    }
    active_policy = resolve_policy(policy or load_policy_pack(), policy_context)
    monitor_findings, monitor_validation = validate_monitoring_evidence(
        change,
        monitor_inventory,
        active_policy,
    )
    triggered.extend(monitor_findings)

    # Policy weights are applied only after every source has emitted stable rule
    # ids. The default policy has no overrides, preserving historical scoring.
    weights = active_policy.get("risk_weights", {})
    for rule in triggered:
        if rule["id"] in weights:
            rule["default_score"] = rule["score"]
            rule["score"] = weights[rule["id"]]

    raw_score = sum(rule["score"] for rule in triggered)
    risk_score = min(raw_score, MAX_SCORE)
    risk_level = score_to_level(risk_score, active_policy.get("risk_level_thresholds"))

    business_impact = service.get("business_impact") or ""

    return {
        "service": service_name,
        "environment": environment,
        "change_type": change_type,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "recommendation": RECOMMENDATIONS[risk_level],
        "triggered_rules": triggered,
        "missing_controls": missing_controls,
        "business_impact": business_impact,
        "policy_pack": {
            "version": active_policy["version"],
            "name": active_policy["name"],
            "owner": active_policy.get("owner"),
            "digest": active_policy.get("digest"),
            "lineage": active_policy.get("lineage", []),
            "failure_modes": active_policy.get("failure_modes", {}),
            "context": active_policy.get("context", policy_context),
            "effective_from": active_policy.get("effective_from"),
            "expires_at": active_policy.get("expires_at"),
            "verified_key_id": active_policy.get("verified_key_id"),
        },
        "monitor_validation": monitor_validation,
        "decision_record": {
            "technical_recommendation": {
                "risk_score": risk_score,
                "risk_level": risk_level,
                "recommendation": RECOMMENDATIONS[risk_level],
            },
            "verified_exception_count": 0,
            "human_decision": {
                "status": "not_recorded",
                "authority": "external_cab_or_change_management",
            },
            "automatic_approval": False,
        },
    }

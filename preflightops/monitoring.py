"""Offline observability evidence validation.

The validator deliberately uses configuration only. It never calls provider
APIs or requires secrets, making it safe for pull requests from forks.
"""

from typing import Any, Optional
from urllib.parse import urlparse

SUPPORTED_PROVIDERS = {
    "datadog",
    "grafana",
    "prometheus",
    "zabbix",
    "gcp-cloud-monitoring",
    "other",
}


def _valid_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _finding(rule_id: str, description: str, score: int, severity: str = "medium") -> dict:
    return {
        "id": rule_id,
        "description": description,
        "severity": severity,
        "score": score,
        "source": "Observability",
    }


def validate_monitoring_evidence(
    change: dict, inventory: Any = None, policy: Optional[dict] = None
) -> tuple[list[dict], dict]:
    """Validate dashboard links and optional monitor inventory references."""
    plan = change.get("monitoring_plan") or {}
    if not isinstance(plan, dict):
        plan = {}
    findings: list[dict] = []
    dashboards = plan.get("dashboards", [])
    if not isinstance(dashboards, list):
        dashboards = []
    monitoring_policy = (policy or {}).get("monitoring", {})
    minimum = monitoring_policy.get("minimum_enabled_monitors", 0)
    required_providers = monitoring_policy.get("required_providers", [])
    referenced = plan.get("monitor_ids", [])
    if referenced is None:
        referenced = []
    if not isinstance(referenced, list) or not all(isinstance(item, str) for item in referenced):
        raise ValueError("monitoring_plan.monitor_ids must be a list of strings.")

    validation_enabled = (
        inventory is not None or minimum > 0 or bool(required_providers) or bool(referenced)
    )
    invalid_urls = [url for url in dashboards if validation_enabled and not _valid_url(url)]
    for url in invalid_urls:
        findings.append(
            _finding(
                "monitoring-invalid-dashboard-url",
                f"Monitoring dashboard URL is invalid: {url}",
                15,
            )
        )

    monitors = []
    if inventory is not None:
        if not isinstance(inventory, dict) or not isinstance(inventory.get("monitors"), list):
            raise ValueError("Monitor inventory must contain a top-level 'monitors' list.")
        for item in inventory["monitors"]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ValueError("Every monitor inventory entry requires a string 'id'.")
            provider = str(item.get("provider") or "other").lower()
            if provider not in SUPPORTED_PROVIDERS:
                raise ValueError(f"Unsupported monitor provider '{provider}' for '{item['id']}'.")
            normalized = dict(item)
            normalized["provider"] = provider
            normalized["enabled"] = item.get("enabled", True) is True
            monitors.append(normalized)

    by_id = {item["id"]: item for item in monitors}
    for monitor_id in referenced:
        monitor = by_id.get(monitor_id)
        if not monitor:
            findings.append(
                _finding(
                    "monitoring-reference-not-found",
                    f"Referenced monitor '{monitor_id}' is not present in the inventory",
                    20,
                    "high",
                )
            )
        elif not monitor["enabled"]:
            findings.append(
                _finding(
                    "monitoring-reference-disabled",
                    f"Referenced monitor '{monitor_id}' is disabled",
                    20,
                    "high",
                )
            )

    enabled = [item for item in monitors if item["enabled"]]
    if len(enabled) < minimum:
        findings.append(
            _finding(
                "monitoring-insufficient-coverage",
                f"Policy requires at least {minimum} enabled monitors; found {len(enabled)}",
                25,
                "high",
            )
        )
    enabled_providers = {item["provider"] for item in enabled}
    for provider in required_providers:
        if provider not in enabled_providers:
            findings.append(
                _finding(
                    "monitoring-required-provider-missing",
                    f"Policy requires an enabled {provider} monitor",
                    25,
                    "high",
                )
            )

    return findings, {
        "status": "pass" if not findings else "fail",
        "dashboard_count": len(dashboards),
        "valid_dashboard_count": len(dashboards) - len(invalid_urls),
        "inventory_monitor_count": len(monitors),
        "enabled_monitor_count": len(enabled),
        "referenced_monitor_ids": referenced,
        "providers": sorted(enabled_providers),
    }

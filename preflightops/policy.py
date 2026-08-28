"""Versioned policy-pack loading and validation."""

from copy import deepcopy
from pathlib import Path
from typing import Any, Optional, cast

import yaml

POLICY_FORMAT_VERSION = "1"

BUILTIN_POLICY_PACKS = {
    "default": {
        "version": POLICY_FORMAT_VERSION,
        "name": "default",
        "description": "Backward-compatible PreflightOps scoring defaults.",
        "risk_weights": {},
        "risk_level_thresholds": {"low": 30, "medium": 60, "high": 80},
        "monitoring": {"minimum_enabled_monitors": 0, "required_providers": []},
    },
    "saas": {
        "version": POLICY_FORMAT_VERSION,
        "name": "saas",
        "description": "Availability and safe rollout controls for multi-tenant SaaS.",
        "risk_weights": {
            "missing-monitoring-plan": 30,
            "kubernetes-missing-readiness-probe": 20,
            "terraform-public-exposure": 40,
        },
        "monitoring": {"minimum_enabled_monitors": 1, "required_providers": []},
    },
    "fintech": {
        "version": POLICY_FORMAT_VERSION,
        "name": "fintech",
        "description": "Strict rollback, auditability, IAM, encryption, and monitoring controls.",
        "risk_weights": {
            "missing-rollback-plan": 45,
            "missing-monitoring-plan": 35,
            "terraform-iam-policy-change": 40,
            "terraform-cloud-iam-change": 40,
            "terraform-kms-change": 35,
            "database-change": 35,
        },
        "monitoring": {"minimum_enabled_monitors": 2, "required_providers": []},
    },
    "ecommerce": {
        "version": POLICY_FORMAT_VERSION,
        "name": "ecommerce",
        "description": "Checkout availability, database safety, and customer-impact controls.",
        "risk_weights": {
            "missing-monitoring-plan": 30,
            "database-change": 35,
            "kubernetes-replicas-zero": 40,
            "critical-service": 30,
        },
        "monitoring": {"minimum_enabled_monitors": 1, "required_providers": []},
    },
    "healthcare": {
        "version": POLICY_FORMAT_VERSION,
        "name": "healthcare",
        "description": "Patient-impact, access, encryption, and recovery-focused controls.",
        "risk_weights": {
            "missing-business-impact": 25,
            "missing-rollback-plan": 40,
            "terraform-cloud-iam-change": 40,
            "terraform-kms-change": 40,
        },
        "monitoring": {"minimum_enabled_monitors": 2, "required_providers": []},
    },
    "critical-platform": {
        "version": POLICY_FORMAT_VERSION,
        "name": "critical-platform",
        "description": "Tier-0 platform policy for broad blast radius and rapid detection.",
        "risk_weights": {
            "critical-service": 35,
            "missing-runbook": 25,
            "missing-rollback-plan": 45,
            "missing-monitoring-plan": 40,
            "terraform-destroy-action": 50,
            "kubernetes-loadbalancer-exposure": 35,
        },
        "monitoring": {"minimum_enabled_monitors": 2, "required_providers": []},
    },
    "travel": {
        "version": POLICY_FORMAT_VERSION,
        "name": "travel",
        "description": "Booking-path availability, recovery, and customer-impact controls.",
        "risk_weights": {
            "critical-service": 35,
            "missing-business-impact": 25,
            "missing-rollback-plan": 45,
            "missing-monitoring-plan": 40,
            "database-change": 35,
            "kubernetes-loadbalancer-exposure": 35,
        },
        "monitoring": {"minimum_enabled_monitors": 2, "required_providers": []},
    },
    "startup": {
        "version": POLICY_FORMAT_VERSION,
        "name": "startup",
        "description": "Lightweight governance while preserving rollback and observability basics.",
        "risk_weights": {
            "missing-runbook": 10,
            "missing-business-impact": 5,
            "missing-validation-plan": 10,
        },
        "monitoring": {"minimum_enabled_monitors": 1, "required_providers": []},
    },
}


def _validate_policy(policy: Any) -> dict:
    if not isinstance(policy, dict):
        raise ValueError("Policy pack must be a YAML mapping.")
    if str(policy.get("version", "")) != POLICY_FORMAT_VERSION:
        raise ValueError(f"Policy pack version must be {POLICY_FORMAT_VERSION}.")
    name = policy.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Policy pack requires a non-empty 'name'.")
    weights = policy.get("risk_weights", {})
    if not isinstance(weights, dict):
        raise ValueError("Policy pack 'risk_weights' must be a mapping.")
    for rule_id, weight in weights.items():
        if not isinstance(rule_id, str) or not isinstance(weight, int) or isinstance(weight, bool):
            raise ValueError("Each risk weight must map a rule id to an integer.")
        if not 0 <= weight <= 100:
            raise ValueError(f"Risk weight for '{rule_id}' must be between 0 and 100.")
    thresholds = policy.get("risk_level_thresholds", {"low": 30, "medium": 60, "high": 80})
    if not isinstance(thresholds, dict):
        raise ValueError("Policy pack 'risk_level_thresholds' must be a mapping.")
    values = [thresholds.get(level) for level in ("low", "medium", "high")]
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        raise ValueError("Risk thresholds low, medium, and high must be integers.")
    low, medium, high = cast(tuple[int, int, int], tuple(values))
    if not (0 <= low < medium < high < 100):
        raise ValueError("Risk thresholds must be ordered: 0 <= low < medium < high < 100.")
    monitoring = policy.get("monitoring", {})
    if not isinstance(monitoring, dict):
        raise ValueError("Policy pack 'monitoring' must be a mapping.")
    minimum = monitoring.get("minimum_enabled_monitors", 0)
    providers = monitoring.get("required_providers", [])
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
        raise ValueError("minimum_enabled_monitors must be a non-negative integer.")
    if not isinstance(providers, list) or not all(isinstance(item, str) for item in providers):
        raise ValueError("required_providers must be a list of provider names.")
    normalized = deepcopy(policy)
    normalized["risk_weights"] = dict(weights)
    normalized["risk_level_thresholds"] = {"low": low, "medium": medium, "high": high}
    normalized["monitoring"] = {
        "minimum_enabled_monitors": minimum,
        "required_providers": [provider.lower() for provider in providers],
    }
    return normalized


def load_policy_pack(value: Optional[str] = None) -> dict:
    """Load a built-in policy by name or a versioned YAML file."""
    if not value:
        return _validate_policy(deepcopy(BUILTIN_POLICY_PACKS["default"]))
    key = value.strip().lower()
    if key in BUILTIN_POLICY_PACKS:
        return _validate_policy(deepcopy(BUILTIN_POLICY_PACKS[key]))
    path = Path(value)
    if not path.is_file():
        available = ", ".join(sorted(name for name in BUILTIN_POLICY_PACKS if name != "default"))
        raise ValueError(
            f"Unknown policy pack '{value}'. Built-ins: {available}; or provide a YAML file."
        )
    try:
        with path.open(encoding="utf-8") as handle:
            policy = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not load policy pack: {exc}") from exc
    return _validate_policy(policy)

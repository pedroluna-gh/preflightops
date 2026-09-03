"""Tests for the core risk engine: the 12 rules, scoring, and helpers."""

import copy

import pytest

from preflightops.risk_engine import (
    assess_risk,
    find_service,
    score_to_level,
)

GOOD_ROLLBACK_PLAN = (
    "Redeploy previous container image svc:1.4.2 via the pipeline if the error "
    "rate exceeds 2% within the validation window. Owner: team."
)

COMPLETE_MONITORING_PLAN = {
    "dashboards": ["https://grafana.example.com/d/svc"],
    "alerts": ["svc-error-rate"],
}


def baseline_services():
    """A service catalog whose single service triggers no rules."""
    return {
        "services": [
            {
                "name": "svc",
                "owner": "team",
                "criticality": "low",
                "runbook": "runbooks/svc.md",
                "business_impact": "Some internal impact",
            }
        ]
    }


def baseline_change():
    """A change request that, against ``baseline_services``, triggers no rules."""
    return {
        "change": {
            "service": "svc",
            "environment": "staging",
            "change_type": "deployment",
            "rollback_plan": GOOD_ROLLBACK_PLAN,
            "monitoring_plan": dict(COMPLETE_MONITORING_PLAN),
            "validation_plan": ["Confirm smoke tests pass"],
        }
    }


def triggered_ids(result):
    return {rule["id"] for rule in result["triggered_rules"]}


def rule_by_id(result, rule_id):
    for rule in result["triggered_rules"]:
        if rule["id"] == rule_id:
            return rule
    return None


# ---------------------------------------------------------------------------
# Baseline: nothing should trigger
# ---------------------------------------------------------------------------
def test_baseline_triggers_nothing():
    result = assess_risk(baseline_services(), baseline_change())
    assert result["triggered_rules"] == []
    assert result["missing_controls"] == []
    assert result["risk_score"] == 0
    assert result["risk_level"] == "LOW"


# ---------------------------------------------------------------------------
# The 12 risk-engine rules, isolated where possible
# ---------------------------------------------------------------------------
class TestRiskRules:
    def test_1_production_change(self):
        change = baseline_change()
        change["change"]["environment"] = "production"
        result = assess_risk(baseline_services(), change)
        rule = rule_by_id(result, "production-change")
        assert rule is not None
        assert rule["score"] == 20
        assert rule["severity"] == "medium"

    def test_2_critical_service_high(self):
        services = baseline_services()
        services["services"][0]["criticality"] = "high"
        result = assess_risk(services, baseline_change())
        rule = rule_by_id(result, "critical-service")
        assert rule is not None
        assert rule["score"] == 25
        assert rule["severity"] == "high"

    def test_2_critical_service_critical(self):
        services = baseline_services()
        services["services"][0]["criticality"] = "critical"
        result = assess_risk(services, baseline_change())
        assert rule_by_id(result, "critical-service") is not None

    def test_2_medium_criticality_does_not_trigger(self):
        services = baseline_services()
        services["services"][0]["criticality"] = "medium"
        result = assess_risk(services, baseline_change())
        assert rule_by_id(result, "critical-service") is None

    def test_3_missing_owner(self):
        services = baseline_services()
        services["services"][0]["owner"] = ""
        result = assess_risk(services, baseline_change())
        rule = rule_by_id(result, "missing-owner")
        assert rule is not None
        assert rule["score"] == 25
        assert "service_owner" in result["missing_controls"]

    def test_4_missing_runbook(self):
        services = baseline_services()
        services["services"][0]["runbook"] = ""
        result = assess_risk(services, baseline_change())
        rule = rule_by_id(result, "missing-runbook")
        assert rule is not None
        assert rule["score"] == 15
        assert "runbook" in result["missing_controls"]

    def test_5_missing_business_impact(self):
        services = baseline_services()
        services["services"][0]["business_impact"] = ""
        result = assess_risk(services, baseline_change())
        rule = rule_by_id(result, "missing-business-impact")
        assert rule is not None
        assert rule["score"] == 10
        assert "business_impact" in result["missing_controls"]

    def test_6_missing_rollback_plan_in_production(self):
        change = baseline_change()
        change["change"]["environment"] = "production"
        change["change"]["rollback_plan"] = ""
        result = assess_risk(baseline_services(), change)
        rule = rule_by_id(result, "missing-rollback-plan")
        assert rule is not None
        assert rule["score"] == 30
        assert "rollback_plan" in result["missing_controls"]

    def test_6_bad_rollback_plan_in_staging_does_not_trigger(self):
        # The rollback rule only applies to production changes.
        change = baseline_change()
        change["change"]["environment"] = "staging"
        change["change"]["rollback_plan"] = ""
        result = assess_risk(baseline_services(), change)
        assert rule_by_id(result, "missing-rollback-plan") is None

    def test_7_missing_monitoring_plan(self):
        change = baseline_change()
        change["change"]["monitoring_plan"] = {}
        result = assess_risk(baseline_services(), change)
        rule = rule_by_id(result, "missing-monitoring-plan")
        assert rule is not None
        assert rule["score"] == 20
        assert "monitoring_plan" in result["missing_controls"]

    def test_8_missing_validation_plan(self):
        change = baseline_change()
        change["change"]["validation_plan"] = []
        result = assess_risk(baseline_services(), change)
        rule = rule_by_id(result, "missing-validation-plan")
        assert rule is not None
        assert rule["score"] == 15
        assert "validation_plan" in result["missing_controls"]

    def test_9_database_change(self):
        change = baseline_change()
        change["change"]["change_type"] = "database"
        result = assess_risk(baseline_services(), change)
        rule = rule_by_id(result, "database-change")
        assert rule is not None
        assert rule["score"] == 25

    def test_10_security_change(self):
        change = baseline_change()
        change["change"]["change_type"] = "security"
        result = assess_risk(baseline_services(), change)
        rule = rule_by_id(result, "security-change")
        assert rule is not None
        assert rule["score"] == 25

    def test_11_network_change(self):
        change = baseline_change()
        change["change"]["change_type"] = "network"
        result = assess_risk(baseline_services(), change)
        rule = rule_by_id(result, "network-change")
        assert rule is not None
        assert rule["score"] == 25

    def test_12_infrastructure_change(self):
        change = baseline_change()
        change["change"]["change_type"] = "infrastructure"
        result = assess_risk(baseline_services(), change)
        rule = rule_by_id(result, "infrastructure-change")
        assert rule is not None
        assert rule["score"] == 20

    def test_change_type_rules_are_mutually_exclusive(self):
        change = baseline_change()
        change["change"]["change_type"] = "database"
        result = assess_risk(baseline_services(), change)
        ids = triggered_ids(result)
        assert "database-change" in ids
        for other in ("security-change", "network-change", "infrastructure-change"):
            assert other not in ids


# ---------------------------------------------------------------------------
# Scanner findings are merged into the assessment
# ---------------------------------------------------------------------------
def test_scanner_findings_merged():
    result = assess_risk(
        baseline_services(),
        baseline_change(),
        terraform_text="aws_iam_policy.admin will be created",
        k8s_text="apiVersion: v1\nkind: Secret\nmetadata: {name: credential}",
    )
    ids = triggered_ids(result)
    assert "terraform-iam-policy-change" in ids
    assert "kubernetes-secret-change" in ids


# ---------------------------------------------------------------------------
# score_to_level boundaries
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "score, level",
    [
        (0, "LOW"),
        (30, "LOW"),
        (31, "MEDIUM"),
        (60, "MEDIUM"),
        (61, "HIGH"),
        (80, "HIGH"),
        (81, "CRITICAL"),
        (100, "CRITICAL"),
        (150, "CRITICAL"),
    ],
)
def test_score_to_level(score, level):
    assert score_to_level(score) == level


def test_score_is_capped_at_100():
    # A change that triggers many rules plus risky scanners exceeds 100 raw.
    services = baseline_services()
    services["services"][0]["criticality"] = "critical"
    services["services"][0]["owner"] = ""
    services["services"][0]["runbook"] = ""
    services["services"][0]["business_impact"] = ""
    change = baseline_change()
    change["change"]["environment"] = "production"
    change["change"]["change_type"] = "infrastructure"
    change["change"]["rollback_plan"] = ""
    change["change"]["monitoring_plan"] = {}
    change["change"]["validation_plan"] = []
    result = assess_risk(
        services,
        change,
        terraform_text="aws_iam_policy destroy aws_db_instance",
        k8s_text=(
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata: {name: api}\n"
            "spec:\n  template:\n    spec:\n      containers: [{name: api}]"
        ),
    )
    assert result["risk_score"] == 100
    assert result["risk_level"] == "CRITICAL"


# ---------------------------------------------------------------------------
# find_service
# ---------------------------------------------------------------------------
class TestFindService:
    def test_finds_existing_service(self):
        service = find_service(baseline_services(), "svc")
        assert service["name"] == "svc"

    def test_unknown_service_raises(self):
        with pytest.raises(ValueError, match="was not found"):
            find_service(baseline_services(), "nope")

    def test_malformed_catalog_raises(self):
        with pytest.raises(ValueError, match="top-level 'services' list"):
            find_service({"not_services": []}, "svc")

    def test_services_not_a_list_raises(self):
        with pytest.raises(ValueError, match="must be a list"):
            find_service({"services": "svc"}, "svc")


# ---------------------------------------------------------------------------
# assess_risk input validation
# ---------------------------------------------------------------------------
class TestAssessRiskValidation:
    def test_missing_change_key_raises(self):
        with pytest.raises(ValueError, match="top-level 'change' object"):
            assess_risk(baseline_services(), {"not_change": {}})

    def test_change_not_a_mapping_raises(self):
        with pytest.raises(ValueError, match="mapping of change request"):
            assess_risk(baseline_services(), {"change": "deploy"})

    def test_missing_service_field_raises(self):
        with pytest.raises(ValueError, match="missing a 'service' field"):
            assess_risk(baseline_services(), {"change": {"environment": "staging"}})

    def test_unknown_service_raises(self):
        change = baseline_change()
        change["change"]["service"] = "ghost"
        with pytest.raises(ValueError, match="was not found"):
            assess_risk(baseline_services(), change)


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------
def test_result_contains_expected_keys():
    result = assess_risk(baseline_services(), baseline_change())
    expected = {
        "service",
        "environment",
        "change_type",
        "risk_score",
        "risk_level",
        "recommendation",
        "triggered_rules",
        "missing_controls",
        "business_impact",
    }
    assert expected <= set(result.keys())


def test_inputs_are_not_mutated():
    services = baseline_services()
    change = baseline_change()
    services_copy = copy.deepcopy(services)
    change_copy = copy.deepcopy(change)
    assess_risk(services, change)
    assert services == services_copy
    assert change == change_copy

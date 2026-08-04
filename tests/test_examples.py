"""Tests that the documented example scenarios produce the expected results.

These lock in the LOW / HIGH / CRITICAL scenarios described in the README and
shipped under ``examples/`` and in ``preflightops.sample_data``.
"""

import os

import yaml

from preflightops import sample_data
from preflightops.risk_engine import assess_risk

EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")


def _load_yaml(filename):
    with open(os.path.join(EXAMPLES_DIR, filename), encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _load_text(filename):
    with open(os.path.join(EXAMPLES_DIR, filename), encoding="utf-8") as handle:
        return handle.read()


# ---------------------------------------------------------------------------
# Scenarios backed by the example YAML/text files in examples/
# ---------------------------------------------------------------------------
class TestExampleFiles:
    def test_low_risk_scenario(self):
        services = _load_yaml("services-low-risk.yaml")
        change = _load_yaml("change-low-risk.yaml")
        result = assess_risk(services, change)
        assert result["risk_score"] == 0
        assert result["risk_level"] == "LOW"
        assert result["triggered_rules"] == []

    def test_high_risk_scenario(self):
        services = _load_yaml("services-high-risk.yaml")
        change = _load_yaml("change-high-risk.yaml")
        result = assess_risk(services, change)
        assert result["risk_score"] == 80
        assert result["risk_level"] == "HIGH"

    def test_critical_risk_scenario(self):
        services = _load_yaml("services-critical-risk.yaml")
        change = _load_yaml("change-critical-risk.yaml")
        terraform = _load_text("terraform-critical.txt")
        k8s = _load_text("k8s-risk.yaml")
        result = assess_risk(services, change, terraform, k8s)
        assert result["risk_score"] == 100
        assert result["risk_level"] == "CRITICAL"


# ---------------------------------------------------------------------------
# Same scenarios backed by the in-code sample data used by the Streamlit app
# ---------------------------------------------------------------------------
class TestSampleData:
    def test_low_risk_sample(self):
        result = assess_risk(sample_data.LOW_RISK_SERVICES, sample_data.LOW_RISK_CHANGE)
        assert result["risk_score"] == 0
        assert result["risk_level"] == "LOW"

    def test_high_risk_sample(self):
        result = assess_risk(sample_data.HIGH_RISK_SERVICES, sample_data.HIGH_RISK_CHANGE)
        assert result["risk_score"] == 80
        assert result["risk_level"] == "HIGH"

    def test_critical_risk_sample(self):
        result = assess_risk(
            sample_data.CRITICAL_RISK_SERVICES,
            sample_data.CRITICAL_RISK_CHANGE,
            sample_data.CRITICAL_TERRAFORM_TEXT,
            sample_data.RISKY_K8S_TEXT,
        )
        assert result["risk_score"] == 100
        assert result["risk_level"] == "CRITICAL"


# ---------------------------------------------------------------------------
# Expected high-risk score breakdown (documents how 80 is reached)
# ---------------------------------------------------------------------------
def test_high_risk_breakdown():
    result = assess_risk(sample_data.HIGH_RISK_SERVICES, sample_data.HIGH_RISK_CHANGE)
    triggered = {rule["id"]: rule["score"] for rule in result["triggered_rules"]}
    assert triggered == {
        "production-change": 20,
        "critical-service": 25,
        "missing-monitoring-plan": 20,
        "missing-validation-plan": 15,
    }
    assert sum(triggered.values()) == 80

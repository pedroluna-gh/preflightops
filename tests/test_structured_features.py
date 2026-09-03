"""Contracts for structured scanners, policies, and observability evidence."""

import json

import pytest
import yaml

from preflightops import cli
from preflightops.monitoring import validate_monitoring_evidence
from preflightops.policy import BUILTIN_POLICY_PACKS, load_policy_pack
from preflightops.risk_engine import assess_risk
from preflightops.scanners import scan_kubernetes, scan_terraform_json


def _ids(findings):
    return {finding["id"] for finding in findings}


def _services():
    return {
        "services": [
            {
                "name": "api",
                "owner": "sre",
                "criticality": "low",
                "runbook": "runbook",
                "business_impact": "impact",
            }
        ]
    }


def _change():
    return {
        "change": {
            "service": "api",
            "environment": "staging",
            "change_type": "deployment",
            "rollback_plan": "Redeploy api:1.2.3 if error rate rises; owner sre; within 10 minutes.",
            "monitoring_plan": {
                "dashboards": ["https://grafana.example.com/d/api"],
                "alerts": ["api-errors"],
            },
            "validation_plan": ["smoke test"],
        }
    }


class TestTerraformJson:
    def test_resource_actions_and_types_are_structured(self):
        plan = {
            "resource_changes": [
                {
                    "address": "aws_iam_role.release",
                    "type": "aws_iam_role",
                    "change": {"actions": ["update"], "after": {}},
                },
                {
                    "address": "google_sql_database_instance.prod",
                    "type": "google_sql_database_instance",
                    "change": {"actions": ["delete"], "after": None},
                },
                {
                    "address": "google_compute_firewall.public",
                    "type": "google_compute_firewall",
                    "change": {"actions": ["update"], "after": {"source_ranges": ["0.0.0.0/0"]}},
                },
            ]
        }
        findings = scan_terraform_json(plan)
        ids = _ids(findings)
        assert {
            "terraform-iam-role-change",
            "terraform-db-instance-change",
            "terraform-destroy-action",
            "terraform-firewall-change",
            "terraform-public-exposure",
        } <= ids
        assert all("resource" in finding for finding in findings)

    def test_replacement_is_not_reported_as_irreversible_destroy(self):
        findings = scan_terraform_json(
            {
                "resource_changes": [
                    {
                        "address": "aws_instance.web",
                        "type": "aws_instance",
                        "change": {"actions": ["delete", "create"], "after": {}},
                    }
                ]
            }
        )
        assert "terraform-replace-action" in _ids(findings)
        assert "terraform-destroy-action" not in _ids(findings)

    def test_invalid_json_fails_closed(self):
        with pytest.raises(ValueError, match="invalid"):
            scan_terraform_json("{")


class TestKubernetesObjects:
    def test_each_workload_is_evaluated_independently(self):
        manifest = """
apiVersion: apps/v1
kind: Deployment
metadata: {name: safe}
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: api
          readinessProbe: {httpGet: {path: /ready, port: 8080}}
          livenessProbe: {httpGet: {path: /health, port: 8080}}
          resources:
            requests: {cpu: 100m, memory: 128Mi}
            limits: {cpu: 500m, memory: 512Mi}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: risky}
spec:
  replicas: 0
  template:
    spec:
      containers:
        - name: api
"""
        findings = scan_kubernetes(manifest)
        ids = _ids(findings)
        assert {
            "kubernetes-replicas-zero",
            "kubernetes-missing-readiness-probe",
            "kubernetes-missing-liveness-probe",
            "kubernetes-missing-resource-requests",
            "kubernetes-missing-resource-limits",
        } <= ids
        missing = [item for item in findings if item["id"] == "kubernetes-missing-readiness-probe"]
        assert len(missing) == 1
        assert missing[0]["resource"] == "deployment/risky"

    @pytest.mark.parametrize(
        "kind,rule",
        [
            ("Ingress", "kubernetes-ingress-change"),
            ("NetworkPolicy", "kubernetes-networkpolicy-change"),
            ("Secret", "kubernetes-secret-change"),
            ("StatefulSet", "kubernetes-statefulset-change"),
        ],
    )
    def test_supported_kinds(self, kind, rule):
        assert rule in _ids(scan_kubernetes(f"kind: {kind}\nmetadata:\n  name: example"))

    def test_load_balancer_service(self):
        manifest = "kind: Service\nmetadata: {name: public}\nspec: {type: LoadBalancer}"
        assert "kubernetes-loadbalancer-exposure" in _ids(scan_kubernetes(manifest))


class TestPolicyPacks:
    def test_all_expected_builtins_are_available(self):
        assert {
            "saas",
            "fintech",
            "ecommerce",
            "healthcare",
            "critical-platform",
            "travel",
            "startup",
        } <= set(BUILTIN_POLICY_PACKS)
        for name in BUILTIN_POLICY_PACKS:
            assert load_policy_pack(name)["name"] == name

    def test_custom_file_and_weight_override(self, tmp_path):
        path = tmp_path / "policy.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "version": "1",
                    "name": "custom",
                    "risk_weights": {"production-change": 55},
                    "risk_level_thresholds": {"low": 20, "medium": 40, "high": 70},
                    "monitoring": {"minimum_enabled_monitors": 0, "required_providers": []},
                }
            ),
            encoding="utf-8",
        )
        policy = load_policy_pack(str(path))
        change = _change()
        change["change"]["environment"] = "production"
        result = assess_risk(_services(), change, policy=policy)
        production = next(
            rule for rule in result["triggered_rules"] if rule["id"] == "production-change"
        )
        assert production["default_score"] == 20
        assert production["score"] == 55
        assert result["risk_level"] == "HIGH"

    @pytest.mark.parametrize("weight", [-1, 101, "30", True])
    def test_invalid_weight_fails_closed(self, tmp_path, weight):
        path = tmp_path / "bad.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "version": "1",
                    "name": "bad",
                    "risk_weights": {"x": weight},
                    "risk_level_thresholds": {"low": 30, "medium": 60, "high": 80},
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="weight"):
            load_policy_pack(str(path))


class TestMonitoringEvidence:
    def test_default_policy_without_inventory_preserves_legacy_scoring(self):
        change = _change()["change"]
        change["monitoring_plan"]["dashboards"] = ["not-a-url"]
        findings, evidence = validate_monitoring_evidence(
            change, inventory=None, policy=load_policy_pack("default")
        )
        assert findings == []
        assert evidence["status"] == "pass"

    def test_policy_minimum_fails_closed_without_inventory(self):
        findings, evidence = validate_monitoring_evidence(
            _change()["change"], inventory=None, policy=load_policy_pack("saas")
        )
        assert "monitoring-insufficient-coverage" in _ids(findings)
        assert evidence["status"] == "fail"

    def test_inventory_references_and_providers_pass(self):
        change = _change()["change"]
        change["monitoring_plan"]["monitor_ids"] = ["errors", "hosts"]
        inventory = {
            "monitors": [
                {"id": "errors", "provider": "prometheus", "enabled": True},
                {"id": "hosts", "provider": "zabbix", "enabled": True},
            ]
        }
        policy = load_policy_pack("default")
        policy["monitoring"] = {
            "minimum_enabled_monitors": 2,
            "required_providers": ["prometheus", "zabbix"],
        }
        findings, evidence = validate_monitoring_evidence(change, inventory, policy)
        assert findings == []
        assert evidence["status"] == "pass"
        assert evidence["providers"] == ["prometheus", "zabbix"]

    def test_missing_disabled_and_invalid_evidence_fail(self):
        change = _change()["change"]
        change["monitoring_plan"] = {
            "dashboards": ["javascript:alert(1)"],
            "monitor_ids": ["missing", "off"],
        }
        findings, evidence = validate_monitoring_evidence(
            change,
            {"monitors": [{"id": "off", "provider": "datadog", "enabled": False}]},
            load_policy_pack("saas"),
        )
        ids = _ids(findings)
        assert {
            "monitoring-invalid-dashboard-url",
            "monitoring-reference-not-found",
            "monitoring-reference-disabled",
            "monitoring-insufficient-coverage",
        } <= ids
        assert evidence["status"] == "fail"


def test_cli_structured_inputs_end_to_end(tmp_path):
    services = tmp_path / "services.yaml"
    change = tmp_path / "change.yaml"
    plan = tmp_path / "plan.json"
    monitors = tmp_path / "monitors.yaml"
    report = tmp_path / "report.md"
    services.write_text(yaml.safe_dump(_services()), encoding="utf-8")
    change_doc = _change()
    change_doc["change"]["monitoring_plan"]["monitor_ids"] = ["api-errors"]
    change.write_text(yaml.safe_dump(change_doc), encoding="utf-8")
    plan.write_text(json.dumps({"format_version": "1.0", "resource_changes": []}), encoding="utf-8")
    monitors.write_text(
        yaml.safe_dump(
            {"monitors": [{"id": "api-errors", "provider": "grafana", "enabled": True}]}
        ),
        encoding="utf-8",
    )
    code = cli.main(
        [
            "--services",
            str(services),
            "--change",
            str(change),
            "--terraform-json",
            str(plan),
            "--policy",
            "saas",
            "--monitors",
            str(monitors),
            "--output",
            str(report),
        ]
    )
    assert code == 0
    assert "Policy Pack: saas" in report.read_text(encoding="utf-8")

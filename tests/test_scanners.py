"""Tests for the Terraform and Kubernetes keyword scanners."""

import pytest

from preflightops.scanners import (
    KUBERNETES_SIGNALS,
    TERRAFORM_SIGNALS,
    scan_kubernetes,
    scan_kubernetes_legacy,
    scan_terraform,
)


def _ids(findings):
    return {f["id"] for f in findings}


def _by_id(findings, rule_id):
    for finding in findings:
        if finding["id"] == rule_id:
            return finding
    return None


# ---------------------------------------------------------------------------
# scan_terraform
# ---------------------------------------------------------------------------
class TestScanTerraform:
    def test_empty_text_returns_no_findings(self):
        assert scan_terraform("") == []
        assert scan_terraform(None) == []

    @pytest.mark.parametrize("keyword, rule_id, score, severity, description", TERRAFORM_SIGNALS)
    def test_each_signal_triggers(self, keyword, rule_id, score, severity, description):
        findings = scan_terraform(f"resource block with {keyword} inside")
        finding = _by_id(findings, rule_id)
        assert finding is not None
        assert finding["score"] == score
        assert finding["severity"] == severity
        assert finding["description"] == description

    def test_case_insensitive_match(self):
        findings = scan_terraform("AWS_IAM_POLICY.admin will be created")
        assert "terraform-iam-policy-change" in _ids(findings)

    def test_destroy_is_critical_and_high_score(self):
        finding = _by_id(scan_terraform("1 to destroy"), "terraform-destroy-action")
        assert finding["severity"] == "critical"
        assert finding["score"] == 40

    def test_multiple_signals_in_one_plan(self):
        text = 'resource "aws_iam_role" "r" {}\naws_db_instance.payments will be destroyed'
        ids = _ids(scan_terraform(text))
        assert "terraform-iam-role-change" in ids
        assert "terraform-db-instance-change" in ids
        assert "terraform-destroy-action" in ids

    def test_unrelated_text_has_no_findings(self):
        assert scan_terraform("# no risky resources here, just a comment") == []


# ---------------------------------------------------------------------------
# scan_kubernetes
# ---------------------------------------------------------------------------
class TestScanKubernetes:
    def test_empty_text_returns_no_findings(self):
        assert scan_kubernetes("") == []
        assert scan_kubernetes(None) == []

    @pytest.mark.parametrize("keyword, rule_id, score, severity, description", KUBERNETES_SIGNALS)
    def test_legacy_signal_contract(self, keyword, rule_id, score, severity, description):
        findings = scan_kubernetes_legacy(keyword)
        finding = _by_id(findings, rule_id)
        assert finding is not None
        assert finding["score"] == score
        assert finding["severity"] == severity
        assert finding["description"] == description

    def test_legacy_case_insensitive_match(self):
        findings = scan_kubernetes_legacy("KIND: Secret\nmetadata: {}")
        assert "kubernetes-secret-change" in _ids(findings)

    def test_deployment_without_probes_flags_both(self):
        text = """
apiVersion: apps/v1
kind: Deployment
metadata: {name: api}
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: api
          resources:
            requests: {cpu: 100m}
            limits: {cpu: 500m}
"""
        ids = _ids(scan_kubernetes(text))
        assert "kubernetes-missing-readiness-probe" in ids
        assert "kubernetes-missing-liveness-probe" in ids

    def test_missing_probe_scores(self):
        findings = scan_kubernetes(
            """
apiVersion: apps/v1
kind: Deployment
metadata: {name: api}
spec:
  template:
    spec:
      containers: [{name: api}]
"""
        )
        readiness = _by_id(findings, "kubernetes-missing-readiness-probe")
        liveness = _by_id(findings, "kubernetes-missing-liveness-probe")
        assert readiness["score"] == 15
        assert liveness["score"] == 15

    def test_deployment_with_both_probes_not_flagged(self):
        text = """
apiVersion: apps/v1
kind: Deployment
metadata: {name: api}
spec:
  template:
    spec:
      containers:
        - name: api
          readinessProbe: {httpGet: {path: /ready, port: 8080}}
          livenessProbe: {httpGet: {path: /health, port: 8080}}
"""
        ids = _ids(scan_kubernetes(text))
        assert "kubernetes-missing-readiness-probe" not in ids
        assert "kubernetes-missing-liveness-probe" not in ids

    def test_deployment_missing_only_liveness(self):
        text = """
apiVersion: apps/v1
kind: Deployment
metadata: {name: api}
spec:
  template:
    spec:
      containers:
        - name: api
          readinessProbe: {httpGet: {path: /ready, port: 8080}}
"""
        ids = _ids(scan_kubernetes(text))
        assert "kubernetes-missing-readiness-probe" not in ids
        assert "kubernetes-missing-liveness-probe" in ids

    def test_probe_checks_only_apply_to_long_running_workloads(self):
        ids = _ids(scan_kubernetes("apiVersion: v1\nkind: Secret\nmetadata: {name: credential}"))
        assert "kubernetes-missing-readiness-probe" not in ids
        assert "kubernetes-missing-liveness-probe" not in ids

    def test_legacy_probe_contract_is_preserved(self):
        ids = _ids(scan_kubernetes_legacy("kind: Deployment"))
        assert "kubernetes-missing-readiness-probe" in ids
        assert "kubernetes-missing-liveness-probe" in ids

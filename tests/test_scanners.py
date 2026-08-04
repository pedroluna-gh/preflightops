"""Tests for the Terraform and Kubernetes keyword scanners."""

import pytest

from preflightops.scanners import (
    KUBERNETES_SIGNALS,
    TERRAFORM_SIGNALS,
    scan_kubernetes,
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
    def test_each_signal_triggers(self, keyword, rule_id, score, severity, description):
        # Avoid the special Deployment probe checks by not using a Deployment
        # for non-deployment signals; for the deployment signal include probes.
        text = keyword
        if keyword == "kind: deployment":
            text += "\nreadinessProbe: {}\nlivenessProbe: {}"
        findings = scan_kubernetes(text)
        finding = _by_id(findings, rule_id)
        assert finding is not None
        assert finding["score"] == score
        assert finding["severity"] == severity
        assert finding["description"] == description

    def test_case_insensitive_match(self):
        findings = scan_kubernetes("KIND: Secret\nmetadata: {}")
        assert "kubernetes-secret-change" in _ids(findings)

    def test_deployment_without_probes_flags_both(self):
        text = "kind: Deployment\nspec:\n  replicas: 3"
        ids = _ids(scan_kubernetes(text))
        assert "kubernetes-missing-readiness-probe" in ids
        assert "kubernetes-missing-liveness-probe" in ids

    def test_missing_probe_scores(self):
        findings = scan_kubernetes("kind: Deployment")
        readiness = _by_id(findings, "kubernetes-missing-readiness-probe")
        liveness = _by_id(findings, "kubernetes-missing-liveness-probe")
        assert readiness["score"] == 15
        assert liveness["score"] == 15

    def test_deployment_with_both_probes_not_flagged(self):
        text = (
            "kind: Deployment\n"
            "        readinessProbe:\n          httpGet: {}\n"
            "        livenessProbe:\n          httpGet: {}\n"
        )
        ids = _ids(scan_kubernetes(text))
        assert "kubernetes-missing-readiness-probe" not in ids
        assert "kubernetes-missing-liveness-probe" not in ids

    def test_deployment_missing_only_liveness(self):
        text = "kind: Deployment\nreadinessProbe: {}"
        ids = _ids(scan_kubernetes(text))
        assert "kubernetes-missing-readiness-probe" not in ids
        assert "kubernetes-missing-liveness-probe" in ids

    def test_probe_checks_only_apply_to_deployments(self):
        # A Secret manifest should not trigger probe findings.
        ids = _ids(scan_kubernetes("kind: Secret"))
        assert "kubernetes-missing-readiness-probe" not in ids
        assert "kubernetes-missing-liveness-probe" not in ids

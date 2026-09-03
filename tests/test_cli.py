"""Tests for the command-line entry point (``preflightops.cli``).

The CLI is what a CI pipeline runs: its exit code (1 on CRITICAL risk, 0
otherwise) gates the build, and it writes the Markdown report reviewers read.
These tests lock in the exit codes, the error codes for bad/missing input, and
the report-writing + summary behaviour.
"""

import json
import os

import pytest
import yaml

from preflightops import cli, sample_data

EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")


def _write_yaml(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle)
    return str(path)


# ---------------------------------------------------------------------------
# Exit codes driven by risk level
# ---------------------------------------------------------------------------
class TestExitCodes:
    def test_low_risk_returns_zero(self, tmp_path, capsys):
        services = _write_yaml(tmp_path / "services.yaml", sample_data.LOW_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.LOW_RISK_CHANGE)
        output = tmp_path / "report.md"
        code = cli.main(["--services", services, "--change", change, "--output", str(output)])
        assert code == 0

    def test_high_risk_returns_zero(self, tmp_path):
        # HIGH is not CRITICAL, so the build is not failed.
        services = _write_yaml(tmp_path / "services.yaml", sample_data.HIGH_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.HIGH_RISK_CHANGE)
        output = tmp_path / "report.md"
        code = cli.main(["--services", services, "--change", change, "--output", str(output)])
        assert code == 0

    def test_critical_risk_returns_one(self, tmp_path):
        services = _write_yaml(tmp_path / "services.yaml", sample_data.CRITICAL_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.CRITICAL_RISK_CHANGE)
        terraform = tmp_path / "tf.txt"
        terraform.write_text(sample_data.CRITICAL_TERRAFORM_TEXT, encoding="utf-8")
        k8s = tmp_path / "k8s.yaml"
        k8s.write_text(sample_data.RISKY_K8S_TEXT, encoding="utf-8")
        output = tmp_path / "report.md"
        code = cli.main(
            [
                "--services",
                services,
                "--change",
                change,
                "--terraform",
                str(terraform),
                "--k8s",
                str(k8s),
                "--output",
                str(output),
            ]
        )
        assert code == 1


# ---------------------------------------------------------------------------
# Report writing and console summary
# ---------------------------------------------------------------------------
class TestOutput:
    def test_writes_report_file(self, tmp_path):
        services = _write_yaml(tmp_path / "services.yaml", sample_data.HIGH_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.HIGH_RISK_CHANGE)
        output = tmp_path / "report.md"
        cli.main(["--services", services, "--change", change, "--output", str(output)])
        assert output.exists()
        contents = output.read_text(encoding="utf-8")
        assert "# PreflightOps Risk Report" in contents
        assert "Risk Level: HIGH" in contents

    def test_prints_score_and_level_summary(self, tmp_path, capsys):
        services = _write_yaml(tmp_path / "services.yaml", sample_data.HIGH_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.HIGH_RISK_CHANGE)
        output = tmp_path / "report.md"
        cli.main(["--services", services, "--change", change, "--output", str(output)])
        out = capsys.readouterr().out
        assert "Service:     checkout-api" in out
        assert "Environment: production" in out
        assert "Risk Score:  80/100" in out
        assert "Risk Level:  HIGH" in out
        assert f"Report written to: {output}" in out

    def test_default_output_path(self, tmp_path, monkeypatch):
        # When --output is omitted, the report is written to report.md in cwd.
        services = _write_yaml(tmp_path / "services.yaml", sample_data.LOW_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.LOW_RISK_CHANGE)
        monkeypatch.chdir(tmp_path)
        code = cli.main(["--services", services, "--change", change])
        assert code == 0
        assert (tmp_path / "report.md").exists()

    def test_writes_html_and_github_comment_outputs(self, tmp_path):
        services = _write_yaml(tmp_path / "services.yaml", sample_data.HIGH_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.HIGH_RISK_CHANGE)
        markdown = tmp_path / "report.md"
        html = tmp_path / "report.html"
        comment = tmp_path / "comment.md"

        code = cli.main(
            [
                "--services",
                services,
                "--change",
                change,
                "--output",
                str(markdown),
                "--html-output",
                str(html),
                "--github-comment-output",
                str(comment),
                "--full-report-url",
                "https://github.com/acme/api/actions/runs/42",
            ]
        )

        assert code == 0
        assert "<!doctype html>" in html.read_text(encoding="utf-8")
        assert "<!-- preflightops-report -->" in comment.read_text(encoding="utf-8")

    def test_changed_files_auto_loads_kubernetes_and_records_scope(self, tmp_path):
        services = _write_yaml(tmp_path / "services.yaml", sample_data.LOW_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.LOW_RISK_CHANGE)
        k8s = tmp_path / "k8s"
        k8s.mkdir()
        (k8s / "secret.yaml").write_text(
            "apiVersion: v1\nkind: Secret\nmetadata:\n  name: api-secret\n", encoding="utf-8"
        )
        changed = tmp_path / "changed.json"
        changed.write_text(json.dumps(["k8s/secret.yaml"]), encoding="utf-8")
        json_output = tmp_path / "report.json"

        code = cli.main(
            [
                "--services",
                services,
                "--change",
                change,
                "--changed-files",
                str(changed),
                "--repository-root",
                str(tmp_path),
                "--output",
                str(tmp_path / "report.md"),
                "--json-output",
                str(json_output),
            ]
        )

        assert code in {0, 1}
        result = json.loads(json_output.read_text(encoding="utf-8"))
        assert result["change_scope"]["scanners"] == ["kubernetes"]
        assert result["change_scope"]["selected_inputs"]["kubernetes"] == ["k8s/secret.yaml"]
        assert any(rule["id"] == "kubernetes-secret-change" for rule in result["triggered_rules"])


# ---------------------------------------------------------------------------
# Error handling: bad and missing input files
# ---------------------------------------------------------------------------
class TestErrorCodes:
    def test_missing_services_file_returns_two(self, tmp_path, capsys):
        change = _write_yaml(tmp_path / "change.yaml", sample_data.LOW_RISK_CHANGE)
        output = tmp_path / "report.md"
        code = cli.main(
            [
                "--services",
                str(tmp_path / "does-not-exist.yaml"),
                "--change",
                change,
                "--output",
                str(output),
            ]
        )
        assert code == 2
        assert "Error loading input files" in capsys.readouterr().err
        assert not output.exists()

    def test_missing_change_file_returns_two(self, tmp_path, capsys):
        services = _write_yaml(tmp_path / "services.yaml", sample_data.LOW_RISK_SERVICES)
        code = cli.main(
            [
                "--services",
                services,
                "--change",
                str(tmp_path / "nope.yaml"),
                "--output",
                str(tmp_path / "report.md"),
            ]
        )
        assert code == 2
        assert "Error loading input files" in capsys.readouterr().err

    def test_malformed_yaml_returns_two(self, tmp_path, capsys):
        services = tmp_path / "services.yaml"
        services.write_text("this: : : not valid yaml\n  - [", encoding="utf-8")
        change = _write_yaml(tmp_path / "change.yaml", sample_data.LOW_RISK_CHANGE)
        code = cli.main(
            ["--services", str(services), "--change", change, "--output", str(tmp_path / "r.md")]
        )
        assert code == 2
        assert "Error loading input files" in capsys.readouterr().err

    def test_unknown_service_returns_two(self, tmp_path, capsys):
        # File loads fine, but assess_risk raises ValueError for an unknown service.
        services = _write_yaml(tmp_path / "services.yaml", sample_data.LOW_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", {"change": {"service": "ghost-service"}})
        code = cli.main(
            ["--services", services, "--change", change, "--output", str(tmp_path / "r.md")]
        )
        assert code == 2
        assert "Error:" in capsys.readouterr().err

    def test_terraform_json_without_format_version_fails_closed(self, tmp_path, capsys):
        services = _write_yaml(tmp_path / "services.yaml", sample_data.LOW_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.LOW_RISK_CHANGE)
        plan = tmp_path / "tfplan.json"
        plan.write_text(json.dumps({"resource_changes": []}), encoding="utf-8")

        code = cli.main(
            [
                "--services",
                services,
                "--change",
                change,
                "--terraform-json",
                str(plan),
                "--output",
                str(tmp_path / "report.md"),
            ]
        )

        assert code == 2
        assert "TF_PLAN_FORMAT_VERSION" in capsys.readouterr().err
        assert not (tmp_path / "report.md").exists()

    def test_missing_required_arg_exits(self, capsys):
        # argparse exits with code 2 when a required argument is absent.
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["--services", "only-services.yaml"])
        assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# Live integration pushes require an explicit confirmation
# ---------------------------------------------------------------------------
class TestLivePushConfirmation:
    def _base_args(self, tmp_path):
        services = _write_yaml(tmp_path / "services.yaml", sample_data.HIGH_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.HIGH_RISK_CHANGE)
        output = tmp_path / "report.md"
        return [
            "--services",
            services,
            "--change",
            change,
            "--output",
            str(output),
        ]

    def test_declining_makes_no_api_call(self, tmp_path, capsys, monkeypatch):
        calls = []
        monkeypatch.setattr(
            cli,
            "push_to_servicenow",
            lambda *a, **k: calls.append(a) or {},
        )
        # Interactive terminal that answers "no".
        monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda *a: "n")

        code = cli.main(self._base_args(tmp_path) + ["--servicenow", "https://dev.service-now.com"])

        assert code == 0  # HIGH risk is not CRITICAL; clean exit
        assert calls == []  # no network call made
        out = capsys.readouterr().out
        assert "About to push a change record to ServiceNow" in out
        assert "Skipping ServiceNow push" in out

    def test_confirming_makes_the_api_call(self, tmp_path, capsys, monkeypatch):
        calls = []

        def fake_push(instance_url, result, change_doc, ticket_markdown):
            calls.append(instance_url)
            return {
                "system": "servicenow",
                "action": "created",
                "number": "CHG0012345",
                "sys_id": "abc",
                "url": "https://dev.service-now.com/x",
            }

        monkeypatch.setattr(cli, "push_to_servicenow", fake_push)
        monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda *a: "y")

        code = cli.main(self._base_args(tmp_path) + ["--servicenow", "https://dev.service-now.com"])

        assert code == 0
        assert calls == ["https://dev.service-now.com"]
        out = capsys.readouterr().out
        assert "ServiceNow change record created: CHG0012345" in out

    def test_yes_flag_skips_prompt(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(
            cli,
            "push_to_jira",
            lambda *a, **k: (
                calls.append(a[0])
                or {
                    "system": "jira",
                    "action": "created",
                    "key": "OPS-1",
                    "url": "https://x/browse/OPS-1",
                }
            ),
        )

        def _no_input(*a):
            raise AssertionError("input() should not be called with --yes")

        monkeypatch.setattr("builtins.input", _no_input)

        code = cli.main(
            self._base_args(tmp_path) + ["--jira", "https://org.atlassian.net", "--yes"]
        )

        assert code == 0
        assert calls == ["https://org.atlassian.net"]

    def test_no_tty_without_yes_skips_push(self, tmp_path, capsys, monkeypatch):
        calls = []
        monkeypatch.setattr(
            cli,
            "push_to_servicenow",
            lambda *a, **k: calls.append(a) or {},
        )
        # Non-interactive: no terminal attached and --yes not given.
        monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)

        def _no_input(*a):
            raise AssertionError("input() should not be called without a TTY")

        monkeypatch.setattr("builtins.input", _no_input)

        code = cli.main(self._base_args(tmp_path) + ["--servicenow", "https://dev.service-now.com"])

        assert code == 0  # clean exit, offline path unaffected
        assert calls == []
        err = capsys.readouterr().err
        assert "no interactive terminal" in err

    def test_offline_path_does_not_prompt(self, tmp_path, monkeypatch):
        # Without --servicenow / --jira there is no prompt and no push.
        def _no_input(*a):
            raise AssertionError("input() should not be called on the offline path")

        monkeypatch.setattr("builtins.input", _no_input)
        ticket_output = tmp_path / "ticket.md"
        code = cli.main(self._base_args(tmp_path) + ["--ticket-output", str(ticket_output)])
        assert code == 0
        assert ticket_output.exists()

    def test_preview_shows_target_and_correlation_id(self, tmp_path, capsys, monkeypatch):

        monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda *a: "n")

        services = _write_yaml(tmp_path / "services.yaml", sample_data.HIGH_RISK_SERVICES)
        change_doc = sample_data.HIGH_RISK_CHANGE
        change = _write_yaml(tmp_path / "change.yaml", change_doc)
        output = tmp_path / "report.md"

        cli.main(
            [
                "--services",
                services,
                "--change",
                change,
                "--output",
                str(output),
                "--jira",
                "https://org.atlassian.net",
            ]
        )

        out = capsys.readouterr().out
        assert any(
            line == "  Target:         https://org.atlassian.net" for line in out.splitlines()
        )
        # The deterministic correlation id is shown in the preview.
        assert "Correlation id:" in out
        assert "updated if it exists" in out


# ---------------------------------------------------------------------------
# The CLI also works against the shipped example files end to end
# ---------------------------------------------------------------------------
def test_cli_with_example_files(tmp_path):
    services = os.path.join(EXAMPLES_DIR, "services-critical-risk.yaml")
    change = os.path.join(EXAMPLES_DIR, "change-critical-risk.yaml")
    terraform = os.path.join(EXAMPLES_DIR, "terraform-critical.txt")
    k8s = os.path.join(EXAMPLES_DIR, "k8s-risk.yaml")
    output = tmp_path / "report.md"
    code = cli.main(
        [
            "--services",
            services,
            "--change",
            change,
            "--terraform",
            terraform,
            "--k8s",
            k8s,
            "--output",
            str(output),
        ]
    )
    assert code == 1
    assert output.exists()
    assert "Risk Level: CRITICAL" in output.read_text(encoding="utf-8")

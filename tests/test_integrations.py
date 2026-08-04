"""Tests for the opt-in ServiceNow / Jira API integrations.

These lock in the *opt-in* contract: nothing touches the network unless a
ServiceNow instance URL or Jira base URL is supplied, credentials are read from
the environment only, the same change is updated rather than duplicated on a
second run, and a misconfiguration surfaces as a clean ``IntegrationError`` /
exit code instead of crashing the offline paths.

All HTTP is intercepted by patching ``integrations._http_request`` so no real
network call is made.
"""

import pytest
import yaml

from preflightops import cli, integrations, sample_data
from preflightops.integrations import (
    IntegrationError,
    correlation_id,
    push_to_jira,
    push_to_servicenow,
)


def _result():
    return {
        "service": "payments-core",
        "environment": "production",
        "risk_score": 100,
        "risk_level": "CRITICAL",
        "recommendation": "Block until gaps resolved.",
        "triggered_rules": [],
        "missing_controls": ["rollback_plan"],
        "business_impact": "Revenue stops immediately",
    }


def _change():
    return {"change": {"title": "Migrate payments-core to new IAM roles"}}


SERVICENOW_ENV = {
    "SERVICENOW_USER": "svc",
    "SERVICENOW_PASSWORD": "secret",
}

JIRA_ENV = {
    "JIRA_EMAIL": "ops@example.com",
    "JIRA_API_TOKEN": "token",
    "JIRA_PROJECT_KEY": "OPS",
}


class _FakeHttp:
    """Record HTTP calls and return canned responses keyed by (method, url-substr)."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url, method, headers, body=None, timeout=30):
        self.calls.append({"url": url, "method": method, "headers": headers, "body": body})
        for (m, needle), response in self.responses.items():
            if m == method and needle in url:
                return response
        raise AssertionError(f"unexpected request: {method} {url}")


# ---------------------------------------------------------------------------
# correlation_id
# ---------------------------------------------------------------------------
class TestCorrelationId:
    def test_deterministic_and_prefixed(self):
        a = correlation_id(_result(), _change())
        b = correlation_id(_result(), _change())
        assert a == b
        assert a.startswith("preflightops-")

    def test_changes_with_inputs(self):
        other = _change()
        other["change"]["title"] = "A different change"
        assert correlation_id(_result(), _change()) != correlation_id(_result(), other)


# ---------------------------------------------------------------------------
# ServiceNow
# ---------------------------------------------------------------------------
class TestServiceNow:
    def test_creates_when_no_existing_record(self, monkeypatch):
        fake = _FakeHttp(
            {
                ("GET", "sysparm_query"): (200, {"result": []}),
                ("POST", "change_request"): (
                    201,
                    {"result": {"number": "CHG0030001", "sys_id": "sys123"}},
                ),
            }
        )
        monkeypatch.setattr(integrations, "_http_request", fake)
        info = push_to_servicenow(
            "https://dev123.service-now.com/", _result(), _change(), env=SERVICENOW_ENV
        )
        assert info["action"] == "created"
        assert info["number"] == "CHG0030001"
        assert "sys123" in info["url"]
        methods = [c["method"] for c in fake.calls]
        assert methods == ["GET", "POST"]
        # The correlation id is sent so re-runs can find this record.
        assert "correlation_id" in fake.calls[1]["body"]

    def test_updates_when_record_exists(self, monkeypatch):
        fake = _FakeHttp(
            {
                ("GET", "sysparm_query"): (
                    200,
                    {"result": [{"sys_id": "existing1", "number": "CHG0030009"}]},
                ),
                ("PATCH", "change_request/existing1"): (
                    200,
                    {"result": {"number": "CHG0030009", "sys_id": "existing1"}},
                ),
            }
        )
        monkeypatch.setattr(integrations, "_http_request", fake)
        info = push_to_servicenow(
            "https://dev123.service-now.com", _result(), _change(), env=SERVICENOW_ENV
        )
        assert info["action"] == "updated"
        assert [c["method"] for c in fake.calls] == ["GET", "PATCH"]

    def test_missing_credentials_raise(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("must not make a request without credentials")

        monkeypatch.setattr(integrations, "_http_request", _boom)
        with pytest.raises(IntegrationError):
            push_to_servicenow("https://dev123.service-now.com", _result(), _change(), env={})

    def test_missing_instance_url_raises(self):
        with pytest.raises(IntegrationError):
            push_to_servicenow("", _result(), _change(), env=SERVICENOW_ENV)


# ---------------------------------------------------------------------------
# Jira
# ---------------------------------------------------------------------------
class TestJira:
    def test_creates_when_no_existing_issue(self, monkeypatch):
        fake = _FakeHttp(
            {
                ("GET", "/rest/api/2/search"): (200, {"issues": []}),
                ("POST", "/rest/api/2/issue"): (201, {"key": "OPS-42"}),
            }
        )
        monkeypatch.setattr(integrations, "_http_request", fake)
        info = push_to_jira("https://acme.atlassian.net/", _result(), _change(), env=JIRA_ENV)
        assert info["action"] == "created"
        assert info["key"] == "OPS-42"
        assert info["url"].endswith("/browse/OPS-42")
        create = fake.calls[1]["body"]["fields"]
        assert create["project"] == {"key": "OPS"}
        assert correlation_id(_result(), _change()) in create["labels"]

    def test_updates_when_issue_exists(self, monkeypatch):
        fake = _FakeHttp(
            {
                ("GET", "/rest/api/2/search"): (200, {"issues": [{"key": "OPS-7"}]}),
                ("PUT", "/rest/api/2/issue/OPS-7"): (204, {}),
            }
        )
        monkeypatch.setattr(integrations, "_http_request", fake)
        info = push_to_jira("https://acme.atlassian.net", _result(), _change(), env=JIRA_ENV)
        assert info["action"] == "updated"
        assert info["key"] == "OPS-7"
        assert [c["method"] for c in fake.calls] == ["GET", "PUT"]

    def test_missing_credentials_raise(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("must not make a request without credentials")

        monkeypatch.setattr(integrations, "_http_request", _boom)
        with pytest.raises(IntegrationError):
            push_to_jira("https://acme.atlassian.net", _result(), _change(), env={})

    def test_missing_project_raises(self):
        env = {"JIRA_EMAIL": "ops@example.com", "JIRA_API_TOKEN": "token"}
        with pytest.raises(IntegrationError):
            push_to_jira("https://acme.atlassian.net", _result(), _change(), env=env)


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------
def _write_yaml(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle)
    return str(path)


class TestCliIntegration:
    def test_no_flags_makes_no_network_call(self, tmp_path, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("network call made without an opt-in flag")

        monkeypatch.setattr(cli, "push_to_servicenow", _boom)
        monkeypatch.setattr(cli, "push_to_jira", _boom)
        services = _write_yaml(tmp_path / "services.yaml", sample_data.LOW_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.LOW_RISK_CHANGE)
        code = cli.main(
            ["--services", services, "--change", change, "--output", str(tmp_path / "r.md")]
        )
        assert code == 0

    def test_servicenow_flag_invokes_push_and_prints(self, tmp_path, monkeypatch, capsys):
        captured = {}

        def _fake_push(instance_url, result, change_doc=None, ticket_markdown=None):
            captured["instance_url"] = instance_url
            captured["ticket_markdown"] = ticket_markdown
            return {
                "system": "servicenow",
                "action": "created",
                "number": "CHG0030001",
                "sys_id": "sys1",
                "url": "https://dev123.service-now.com/x",
            }

        monkeypatch.setattr(cli, "push_to_servicenow", _fake_push)
        services = _write_yaml(tmp_path / "services.yaml", sample_data.HIGH_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.HIGH_RISK_CHANGE)
        code = cli.main(
            [
                "--services",
                services,
                "--change",
                change,
                "--output",
                str(tmp_path / "r.md"),
                "--servicenow",
                "https://dev123.service-now.com",
                "--yes",
            ]
        )
        assert code == 0
        assert captured["instance_url"] == "https://dev123.service-now.com"
        # The summary is generated and handed to the integration.
        assert (
            captured["ticket_markdown"]
            and "# Production Change Summary" in captured["ticket_markdown"]
        )
        out = capsys.readouterr().out
        assert "ServiceNow change record created: CHG0030001" in out

    def test_jira_flag_invokes_push_and_prints(self, tmp_path, monkeypatch, capsys):
        def _fake_push(base_url, result, change_doc=None, ticket_markdown=None):
            return {
                "system": "jira",
                "action": "updated",
                "key": "OPS-7",
                "url": "https://acme.atlassian.net/browse/OPS-7",
            }

        monkeypatch.setattr(cli, "push_to_jira", _fake_push)
        services = _write_yaml(tmp_path / "services.yaml", sample_data.HIGH_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.HIGH_RISK_CHANGE)
        code = cli.main(
            [
                "--services",
                services,
                "--change",
                change,
                "--output",
                str(tmp_path / "r.md"),
                "--jira",
                "https://acme.atlassian.net",
                "--yes",
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "Jira change record updated: OPS-7" in out

    def test_integration_error_returns_two(self, tmp_path, monkeypatch, capsys):
        def _fail(*a, **k):
            raise IntegrationError("bad credentials")

        monkeypatch.setattr(cli, "push_to_servicenow", _fail)
        services = _write_yaml(tmp_path / "services.yaml", sample_data.LOW_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.LOW_RISK_CHANGE)
        code = cli.main(
            [
                "--services",
                services,
                "--change",
                change,
                "--output",
                str(tmp_path / "r.md"),
                "--servicenow",
                "https://dev123.service-now.com",
                "--yes",
            ]
        )
        assert code == 2
        assert "ServiceNow integration error: bad credentials" in capsys.readouterr().err

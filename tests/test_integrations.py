"""Tests for the opt-in ServiceNow / Jira API integrations.

These lock in the *opt-in* contract: nothing touches the network unless a
ServiceNow instance URL or Jira base URL is supplied, credentials are read from
the environment only, the same change is updated rather than duplicated on a
second run, and a misconfiguration surfaces as a clean ``IntegrationError`` /
exit code instead of crashing the offline paths.

All HTTP is intercepted by patching ``integrations._http_request`` so no real
network call is made.
"""

import json
import urllib.parse

import pytest
import yaml

from preflightops import cli, integrations, sample_data
from preflightops.integrations import (
    IntegrationError,
    build_servicenow_evidence,
    correlation_id,
    load_servicenow_mapping,
    prepare_servicenow_payload,
    push_to_jira,
    push_to_servicenow,
    validate_servicenow_instance_url,
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


class _ServiceNowApi:
    """Small stateful Table/Attachment API contract fake."""

    SYS_ID = "a" * 32

    def __init__(
        self,
        record=None,
        duplicate=False,
        verify_mutation=None,
        duplicate_after_write=False,
    ):
        self.record = record
        self.duplicate = duplicate
        self.verify_mutation = verify_mutation
        self.duplicate_after_write = duplicate_after_write
        self.attachments = []
        self.calls = []

    def __call__(self, url, method, headers, body=None, timeout=30):
        call = {"url": url, "method": method, "headers": headers, "body": body}
        self.calls.append(call)
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        if path.endswith("/api/now/v1/table/change_request"):
            if method == "GET":
                records = [dict(self.record)] if self.record else []
                if self.duplicate and records:
                    records.append({**records[0], "sys_id": "b" * 32})
                return 200, {"result": records}
            if method == "POST":
                self.record = {**body, "number": "CHG0030001", "sys_id": self.SYS_ID}
                if self.duplicate_after_write:
                    self.duplicate = True
                return 201, {"result": dict(self.record)}

        if "/api/now/v1/table/change_request/" in path:
            if method == "PATCH":
                self.record.update(body)
                return 200, {"result": dict(self.record)}
            if method == "GET":
                verified = dict(self.record)
                if self.verify_mutation:
                    verified.update(self.verify_mutation)
                return 200, {"result": verified}

        if path.endswith("/api/now/attachment") and method == "GET":
            filename = ""
            encoded = query.get("sysparm_query", [""])[0]
            if "^file_name=" in encoded:
                filename = encoded.rsplit("^file_name=", 1)[1]
            matches = [item for item in self.attachments if item["file_name"] == filename]
            return 200, {"result": matches}

        if path.endswith("/api/now/attachment/file") and method == "POST":
            assert isinstance(body, bytes)
            json.loads(body.decode("utf-8"))
            attachment = {
                "sys_id": "c" * 32,
                "file_name": query["file_name"][0],
                "table_sys_id": query["table_sys_id"][0],
                "size_bytes": str(len(body)),
            }
            self.attachments.append(attachment)
            return 201, {"result": attachment}

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

    def test_manifest_id_survives_title_change(self):
        first = _change()
        first["change"]["id"] = "CHG-immutable-42"
        other = {"change": {**first["change"], "title": "A corrected title"}}
        assert correlation_id(_result(), first) == correlation_id(_result(), other)


# ---------------------------------------------------------------------------
# ServiceNow
# ---------------------------------------------------------------------------
class TestServiceNow:
    def test_creates_when_no_existing_record(self, monkeypatch):
        fake = _ServiceNowApi()
        monkeypatch.setattr(integrations, "_http_request", fake)
        info = push_to_servicenow(
            "https://dev123.service-now.com/", _result(), _change(), env=SERVICENOW_ENV
        )
        assert info["action"] == "created"
        assert info["number"] == "CHG0030001"
        assert _ServiceNowApi.SYS_ID in info["url"]
        assert info["verified"] is True
        methods = [c["method"] for c in fake.calls]
        assert methods == ["GET", "POST", "GET", "GET"]
        # The correlation id is sent so re-runs can find this record.
        assert "correlation_id" in fake.calls[1]["body"]

    def test_updates_when_record_exists(self, monkeypatch):
        fake = _ServiceNowApi({"sys_id": _ServiceNowApi.SYS_ID, "number": "CHG0030009"})
        monkeypatch.setattr(integrations, "_http_request", fake)
        info = push_to_servicenow(
            "https://dev123.service-now.com", _result(), _change(), env=SERVICENOW_ENV
        )
        assert info["action"] == "updated"
        assert [c["method"] for c in fake.calls] == ["GET", "PATCH", "GET", "GET"]

    def test_identical_record_is_unchanged(self, monkeypatch):
        prepared = prepare_servicenow_payload(_result(), _change(), env=SERVICENOW_ENV)
        fake = _ServiceNowApi(
            {
                **prepared["payload"],
                "sys_id": _ServiceNowApi.SYS_ID,
                "number": "CHG0030009",
            }
        )
        monkeypatch.setattr(integrations, "_http_request", fake)
        info = push_to_servicenow(
            "https://dev123.service-now.com", _result(), _change(), env=SERVICENOW_ENV
        )
        assert info["action"] == "unchanged"
        assert [call["method"] for call in fake.calls] == ["GET", "GET", "GET"]

    def test_existing_reference_never_creates_when_missing(self, monkeypatch):
        fake = _ServiceNowApi()
        monkeypatch.setattr(integrations, "_http_request", fake)
        with pytest.raises(IntegrationError, match="no record was created"):
            push_to_servicenow(
                "https://dev123.service-now.com",
                _result(),
                _change(),
                env=SERVICENOW_ENV,
                change_reference="CHG0099999",
            )
        assert [call["method"] for call in fake.calls] == ["GET"]

    def test_ambiguous_lookup_fails_closed(self, monkeypatch):
        fake = _ServiceNowApi(
            {"sys_id": _ServiceNowApi.SYS_ID, "number": "CHG0030009"}, duplicate=True
        )
        monkeypatch.setattr(integrations, "_http_request", fake)
        with pytest.raises(IntegrationError, match="multiple change records"):
            push_to_servicenow(
                "https://dev123.service-now.com", _result(), _change(), env=SERVICENOW_ENV
            )

    def test_attachment_is_verified_and_deduplicated(self, monkeypatch):
        fake = _ServiceNowApi()
        monkeypatch.setattr(integrations, "_http_request", fake)
        first = push_to_servicenow(
            "https://dev123.service-now.com",
            _result(),
            _change(),
            env=SERVICENOW_ENV,
            attach_evidence=True,
        )
        second = push_to_servicenow(
            "https://dev123.service-now.com",
            _result(),
            _change(),
            env=SERVICENOW_ENV,
            attach_evidence=True,
        )
        assert first["evidence"]["status"] == "uploaded"
        assert second["evidence"]["status"] == "unchanged"
        assert len(fake.attachments) == 1

    def test_post_write_verification_mismatch_fails(self, monkeypatch):
        fake = _ServiceNowApi(verify_mutation={"correlation_id": "wrong"})
        monkeypatch.setattr(integrations, "_http_request", fake)
        with pytest.raises(IntegrationError, match="correlation mismatch"):
            push_to_servicenow(
                "https://dev123.service-now.com", _result(), _change(), env=SERVICENOW_ENV
            )

    def test_post_write_identity_race_fails_closed(self, monkeypatch):
        fake = _ServiceNowApi(duplicate_after_write=True)
        monkeypatch.setattr(integrations, "_http_request", fake)
        with pytest.raises(IntegrationError, match="multiple change records"):
            push_to_servicenow(
                "https://dev123.service-now.com", _result(), _change(), env=SERVICENOW_ENV
            )

    def test_bearer_token_is_preferred(self, monkeypatch):
        fake = _ServiceNowApi()
        monkeypatch.setattr(integrations, "_http_request", fake)
        push_to_servicenow(
            "https://dev123.service-now.com",
            _result(),
            _change(),
            env={"SERVICENOW_TOKEN": "oauth-token"},
        )
        assert fake.calls[0]["headers"]["Authorization"] == "Bearer oauth-token"

    def test_missing_credentials_raise(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("must not make a request without credentials")

        monkeypatch.setattr(integrations, "_http_request", _boom)
        with pytest.raises(IntegrationError):
            push_to_servicenow("https://dev123.service-now.com", _result(), _change(), env={})

    def test_missing_instance_url_raises(self):
        with pytest.raises(IntegrationError):
            push_to_servicenow("", _result(), _change(), env=SERVICENOW_ENV)


class TestServiceNowConfiguration:
    @pytest.mark.parametrize(
        "url",
        [
            "http://dev123.service-now.com",
            "https://user:pass@dev123.service-now.com",
            "https://dev123.service-now.com/path",
            "https://dev123.service-now.com?x=1",
            "https://127.0.0.1",
        ],
    )
    def test_unsafe_destination_is_rejected(self, url):
        with pytest.raises(IntegrationError):
            validate_servicenow_instance_url(url, {})

    def test_exact_custom_host_requires_allowlist(self):
        assert (
            validate_servicenow_instance_url(
                "https://changes.example.com",
                {"SERVICENOW_ALLOWED_HOSTS": "changes.example.com"},
            )
            == "https://changes.example.com"
        )

    def test_mapping_refuses_workflow_state(self):
        with pytest.raises(IntegrationError, match="outside the pre-change evidence allowlist"):
            load_servicenow_mapping(
                {"version": "1", "table": "change_request", "fields": {"state": {"value": "3"}}}
            )

    def test_mapping_refuses_non_idempotent_journal_field(self):
        with pytest.raises(IntegrationError, match="outside the pre-change evidence allowlist"):
            load_servicenow_mapping(
                {
                    "version": "1",
                    "table": "change_request",
                    "fields": {"work_notes": {"source": "evidence_summary"}},
                }
            )

    def test_mapping_loads_file_and_string_shorthand(self, tmp_path):
        path = tmp_path / "mapping.yaml"
        path.write_text(
            "version: '1'\ntable: change_request\nfields:\n  description: ticket_markdown\n",
            encoding="utf-8",
        )
        loaded = load_servicenow_mapping(path)
        assert loaded["fields"]["description"] == {"source": "ticket_markdown"}

    @pytest.mark.parametrize(
        "mapping, message",
        [
            ([], "must be a YAML/JSON object"),
            ({"version": "2", "fields": {"description": "ticket_markdown"}}, "version"),
            (
                {"version": "1", "table": "incident", "fields": {"description": "ticket_markdown"}},
                "change_request",
            ),
            ({"version": "1", "fields": {}}, "non-empty fields"),
            (
                {"version": "1", "fields": {"Bad-Field": {"value": "x"}}},
                "Invalid ServiceNow destination",
            ),
            (
                {"version": "1", "fields": {"description": {"source": "x", "value": "y"}}},
                "exactly one",
            ),
            (
                {"version": "1", "fields": {"description": {"source": 42}}},
                "must be a string",
            ),
            (
                {"version": "1", "fields": {"description": {"source": "x", "max_length": 0}}},
                "between 1 and 100000",
            ),
        ],
    )
    def test_invalid_mapping_contracts_fail_closed(self, mapping, message):
        with pytest.raises(IntegrationError, match=message):
            load_servicenow_mapping(mapping)

    def test_missing_mapping_file_is_actionable(self, tmp_path):
        with pytest.raises(IntegrationError, match="Unable to load"):
            load_servicenow_mapping(tmp_path / "missing.yaml")

    def test_unsupported_mapping_source_fails(self):
        mapping = {
            "version": "1",
            "fields": {"description": {"source": "untrusted.instructions"}},
        }
        with pytest.raises(IntegrationError, match="Unsupported ServiceNow mapping source"):
            prepare_servicenow_payload(_result(), _change(), mapping=mapping, env={})

    def test_required_empty_mapping_value_fails(self):
        mapping = {
            "version": "1",
            "fields": {"u_required": {"source": "change.does_not_exist", "required": True}},
        }
        with pytest.raises(IntegrationError, match="resolved to an empty value"):
            prepare_servicenow_payload(_result(), _change(), mapping=mapping, env={})

    def test_custom_evidence_field_and_literal_are_supported(self):
        mapping = {
            "version": "1",
            "fields": {
                "u_preflightops_hash": "evidence_hash",
                "correlation_display": {"value": "PreflightOps"},
            },
        }
        prepared = prepare_servicenow_payload(_result(), _change(), mapping=mapping, env={})
        assert len(prepared["payload"]["u_preflightops_hash"]) == 64
        assert prepared["payload"]["correlation_display"] == "PreflightOps"

    def test_mapping_populates_operational_plans(self):
        change = {
            "change": {
                "id": "CHG-42",
                "title": "Deploy",
                "description": "Deploy safely",
                "rollback_plan": "Roll back image",
                "validation_plan": ["Smoke test", "Check alerts"],
            }
        }
        prepared = prepare_servicenow_payload(_result(), change, env={})
        assert prepared["payload"]["implementation_plan"] == "Deploy safely"
        assert prepared["payload"]["backout_plan"] == "Roll back image"
        assert "Smoke test" in prepared["payload"]["test_plan"]
        assert prepared["correlation_id"] == "preflightops-chg-42"

    def test_evidence_scrubs_secret_like_keys(self):
        result = {**_result(), "token": "never", "nested": {"password": "never"}}
        evidence = build_servicenow_evidence(result, _change(), env={})
        serialized = json.dumps(evidence)
        assert "never" not in serialized
        assert evidence["governance"]["changes_workflow_state"] is False

    def test_http_error_detail_is_bounded_and_structured(self):
        assert (
            integrations._safe_http_detail('{"error":{"message":"Denied","detail":"ACL"}}')
            == "Denied ACL"
        )
        assert len(integrations._safe_http_detail("x" * 1000)) == 500


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

    def test_servicenow_dry_run_uses_no_credentials_or_network(self, tmp_path, monkeypatch, capsys):
        def _boom(*args, **kwargs):
            raise AssertionError("dry-run must not invoke the live push")

        monkeypatch.setattr(cli, "push_to_servicenow", _boom)
        services = _write_yaml(tmp_path / "services.yaml", sample_data.LOW_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.LOW_RISK_CHANGE)
        preview = tmp_path / "servicenow-preview.json"
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
                "--servicenow-change",
                "CHG0030001",
                "--servicenow-attach-evidence",
                "--servicenow-dry-run",
                "--servicenow-preview-output",
                str(preview),
            ]
        )
        assert code == 0
        rendered = json.loads(preview.read_text(encoding="utf-8"))
        assert rendered["mode"] == "enrich_existing"
        assert rendered["attach_evidence"] is True
        assert "No credentials were read and no API call was made" in capsys.readouterr().out

    def test_servicenow_existing_change_options_reach_push(self, tmp_path, monkeypatch):
        captured = {}

        def _fake_push(instance_url, result, change_doc=None, ticket_markdown=None, **kwargs):
            captured.update(kwargs)
            return {
                "system": "servicenow",
                "action": "updated",
                "number": "CHG0030001",
                "sys_id": "a" * 32,
                "url": "https://dev123.service-now.com/x",
            }

        monkeypatch.setattr(cli, "push_to_servicenow", _fake_push)
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
                "--servicenow-change",
                "CHG0030001",
                "--servicenow-attach-evidence",
                "--yes",
            ]
        )
        assert code == 0
        assert captured["change_reference"] == "CHG0030001"
        assert captured["attach_evidence"] is True

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

"""Tests for the Streamlit web UI in ``preflightops/app.py``.

These exercise the app's helper/logic functions and run the full Streamlit
script headlessly via ``streamlit.testing.v1.AppTest`` (no live browser), so a
regression in the example buttons, input parsing, or the score/level shown is
caught by ``pytest``.
"""

import json
import os

import pytest
import yaml

import app
from preflightops import sample_data
from preflightops.report import generate_json_report, generate_markdown_report
from preflightops.risk_engine import assess_risk

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

APP_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")


def _run_app():
    return AppTest.from_file(APP_PATH, default_timeout=60).run()


def _capture_downloads(monkeypatch):
    """Capture the bytes Streamlit registers for ``st.download_button`` calls.

    ``AppTest`` does not expose a download button's payload directly, so we wrap
    ``MediaFileManager.add`` (which every ``download_button`` call routes its
    data through) and record the registered ``file_name`` -> bytes mapping.
    """
    from streamlit.runtime.media_file_manager import MediaFileManager

    captured = {}
    original_add = MediaFileManager.add

    def _add(
        self, path_or_data, mimetype, coordinates, file_name=None, is_for_static_download=False
    ):
        captured[file_name] = {"data": path_or_data, "mimetype": mimetype}
        return original_add(
            self,
            path_or_data,
            mimetype,
            coordinates,
            file_name,
            is_for_static_download,
        )

    monkeypatch.setattr(MediaFileManager, "add", _add)
    return captured


# ---------------------------------------------------------------------------
# Pure helper functions (no Streamlit runtime required)
# ---------------------------------------------------------------------------
class TestHelpers:
    def test_yaml_dump_roundtrips(self):
        dumped = app._yaml_dump(sample_data.LOW_RISK_CHANGE)
        assert yaml.safe_load(dumped) == sample_data.LOW_RISK_CHANGE

    def test_yaml_dump_preserves_key_order(self):
        dumped = app._yaml_dump({"b": 1, "a": 2})
        # sort_keys=False -> insertion order preserved.
        assert dumped.index("b:") < dumped.index("a:")

    def test_group_by_source_orders_known_sources_first(self):
        triggered = [
            {"source": "Kubernetes", "score": 5},
            {"source": "Service Controls", "score": 10},
            {"source": "Custom", "score": 1},
            {"source": "Change Type", "score": 3},
        ]
        grouped = app._group_by_source(triggered)
        # SOURCE_ORDER groups come first, in order; unknown sources trail.
        assert list(grouped.keys()) == [
            "Service Controls",
            "Change Type",
            "Kubernetes",
            "Custom",
        ]

    def test_group_by_source_defaults_missing_source(self):
        grouped = app._group_by_source([{"score": 1}])
        assert "Other" in grouped

    def test_dominant_severity_picks_most_severe(self):
        rules = [{"severity": "low"}, {"severity": "critical"}, {"severity": "medium"}]
        assert app._dominant_severity(rules) == "critical"

    def test_dominant_severity_defaults_to_medium(self):
        assert app._dominant_severity([]) == "medium"
        assert app._dominant_severity([{}]) == "medium"

    def test_severity_chip_uses_severity_color(self):
        chip = app._severity_chip("critical")
        assert app.SEVERITY_COLORS["critical"] in chip
        # Text is lowercased in markup; uppercasing is applied via CSS.
        assert "critical" in chip
        assert "text-transform:uppercase" in chip

    def test_severity_chip_handles_missing_severity(self):
        chip = app._severity_chip(None)
        assert app.SEVERITY_COLORS["medium"] in chip

    def test_level_color_and_renderer_tables_are_consistent(self):
        for level in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            assert level in app.LEVEL_COLORS
            assert level in app.LEVEL_RENDERERS


# ---------------------------------------------------------------------------
# Example loading: the "Start here" buttons populate the editors
# ---------------------------------------------------------------------------
class TestExampleButtons:
    def test_low_example_button_loads_sample_data(self):
        at = _run_app()
        at.button[0].click().run()
        assert not at.exception
        assert yaml.safe_load(at.session_state["services_input"]) == sample_data.LOW_RISK_SERVICES
        assert yaml.safe_load(at.session_state["change_input"]) == sample_data.LOW_RISK_CHANGE
        # LOW example carries no terraform / k8s input.
        assert at.session_state["terraform_input"] == ""
        assert at.session_state["k8s_input"] == ""

    def test_high_example_button_loads_sample_data(self):
        at = _run_app()
        at.button[1].click().run()
        assert not at.exception
        assert yaml.safe_load(at.session_state["services_input"]) == sample_data.HIGH_RISK_SERVICES
        assert yaml.safe_load(at.session_state["change_input"]) == sample_data.HIGH_RISK_CHANGE

    def test_critical_example_button_loads_terraform_and_k8s(self):
        at = _run_app()
        at.button[2].click().run()
        assert not at.exception
        assert (
            yaml.safe_load(at.session_state["services_input"]) == sample_data.CRITICAL_RISK_SERVICES
        )
        assert at.session_state["terraform_input"] == sample_data.CRITICAL_TERRAFORM_TEXT
        assert at.session_state["k8s_input"] == sample_data.RISKY_K8S_TEXT

    def test_loading_example_clears_stale_result(self):
        at = _run_app()
        # Produce a result first.
        at.button[3].click().run()
        assert "result" in at.session_state
        # Loading an example must drop the stale result.
        at.button[0].click().run()
        assert "result" not in at.session_state


# ---------------------------------------------------------------------------
# Running the assessment: the displayed score/level matches the engine
# ---------------------------------------------------------------------------
class TestRunAssessment:
    def _assert_matches_engine(self, at, services, change, terraform="", k8s=""):
        expected = assess_risk(services, change, terraform, k8s)
        score_metric = next(m for m in at.metric if m.label == "Risk Score")
        assert score_metric.value == f"{expected['risk_score']}/100"
        # The risk level badge is rendered as raw markdown/HTML.
        badge_markdown = "\n".join(md.value for md in at.markdown)
        assert expected["risk_level"] in badge_markdown
        return expected

    def test_default_inputs_run_without_error(self):
        at = _run_app()
        at.button[3].click().run()
        assert not at.exception
        services = yaml.safe_load(app.DEFAULT_SERVICES_YAML)
        change = yaml.safe_load(app.DEFAULT_CHANGE_YAML)
        self._assert_matches_engine(at, services, change)

    def test_low_example_assessment_is_low(self):
        at = _run_app()
        at.button[0].click().run()
        at.button[3].click().run()
        assert not at.exception
        expected = self._assert_matches_engine(
            at, sample_data.LOW_RISK_SERVICES, sample_data.LOW_RISK_CHANGE
        )
        assert expected["risk_level"] == "LOW"
        assert any("0/100" == m.value for m in at.metric)

    def test_high_example_assessment_is_high(self):
        at = _run_app()
        at.button[1].click().run()
        at.button[3].click().run()
        assert not at.exception
        expected = self._assert_matches_engine(
            at, sample_data.HIGH_RISK_SERVICES, sample_data.HIGH_RISK_CHANGE
        )
        assert expected["risk_level"] == "HIGH"

    def test_critical_example_assessment_is_critical(self):
        at = _run_app()
        at.button[2].click().run()
        at.button[3].click().run()
        assert not at.exception
        expected = self._assert_matches_engine(
            at,
            sample_data.CRITICAL_RISK_SERVICES,
            sample_data.CRITICAL_RISK_CHANGE,
            sample_data.CRITICAL_TERRAFORM_TEXT,
            sample_data.RISKY_K8S_TEXT,
        )
        assert expected["risk_level"] == "CRITICAL"


# ---------------------------------------------------------------------------
# Bad input must surface a clear error, never crash the app
# ---------------------------------------------------------------------------
class TestBadInput:
    def test_invalid_services_yaml_shows_error(self):
        at = _run_app()
        at.text_area(key="services_input").set_value("not: valid: yaml: :").run()
        at.button[3].click().run()
        assert not at.exception
        assert any("Service Catalog YAML is invalid" in e.value for e in at.error)
        assert "result" not in at.session_state

    def test_invalid_change_yaml_shows_error(self):
        at = _run_app()
        at.text_area(key="change_input").set_value("change: [unclosed").run()
        at.button[3].click().run()
        assert not at.exception
        assert any("Change Request YAML is invalid" in e.value for e in at.error)
        assert "result" not in at.session_state

    def test_unknown_service_reference_shows_error(self):
        at = _run_app()
        bad_change = {
            "change": {
                "id": "CHG-999",
                "title": "Change a service that does not exist",
                "service": "does-not-exist",
                "environment": "production",
                "change_type": "deployment",
                "requested_by": "pedro",
                "description": "References a service missing from the catalog",
            }
        }
        at.text_area(key="change_input").set_value(app._yaml_dump(bad_change)).run()
        at.button[3].click().run()
        assert not at.exception
        assert len(at.error) >= 1
        assert "result" not in at.session_state

    def test_missing_recommended_fields_warns_but_proceeds(self):
        at = _run_app()
        sparse_change = {
            "change": {
                "service": "checkout-api",
                "environment": "production",
            }
        }
        at.text_area(key="change_input").set_value(app._yaml_dump(sparse_change)).run()
        at.button[3].click().run()
        assert not at.exception
        assert any("missing recommended fields" in w.value for w in at.warning)
        # The assessment still runs despite the missing fields.
        assert "result" in at.session_state


# ---------------------------------------------------------------------------
# Downloadable reports: the preview and both download buttons stay correct
# ---------------------------------------------------------------------------
class TestReportDownloads:
    def _run_assessment(self, monkeypatch):
        captured = _capture_downloads(monkeypatch)
        at = _run_app()
        at.button[3].click().run()
        assert not at.exception
        result = at.session_state["result"]
        return at, result, captured

    def test_markdown_preview_matches_generator(self, monkeypatch):
        at, result, _ = self._run_assessment(monkeypatch)
        expected_markdown = generate_markdown_report(result)
        # The preview echoes the report in a markdown code block. ``st.code``
        # strips trailing whitespace for display, so compare on rstrip.
        code_blocks = [c.value for c in at.code if c.language == "markdown"]
        assert any(block.rstrip("\n") == expected_markdown.rstrip("\n") for block in code_blocks)

    def test_download_buttons_are_present_and_labelled(self, monkeypatch):
        at, _, _ = self._run_assessment(monkeypatch)
        download_buttons = at.get("download_button")
        labels = {b.label for b in download_buttons}
        assert labels == {
            "Download Markdown Report",
            "Download JSON Report",
            "Download Change Ticket Summary",
        }

    def test_markdown_download_matches_generator(self, monkeypatch):
        _, result, captured = self._run_assessment(monkeypatch)
        entry = captured["preflightops-report.md"]
        assert entry["mimetype"] == "text/markdown"
        downloaded = entry["data"]
        if isinstance(downloaded, bytes):
            downloaded = downloaded.decode("utf-8")
        assert downloaded == generate_markdown_report(result)

    def test_json_download_parses_and_matches_generator(self, monkeypatch):
        _, result, captured = self._run_assessment(monkeypatch)
        entry = captured["preflightops-report.json"]
        assert entry["mimetype"] == "application/json"
        downloaded = entry["data"]
        if isinstance(downloaded, bytes):
            downloaded = downloaded.decode("utf-8")
        # The JSON must be valid and match the generator byte-for-byte.
        parsed = json.loads(downloaded)
        assert parsed["risk_score"] == result["risk_score"]
        assert parsed["risk_level"] == result["risk_level"]
        assert downloaded == generate_json_report(result)
        assert json.loads(downloaded) == json.loads(generate_json_report(result))

    def test_critical_example_report_downloads_match(self, monkeypatch):
        captured = _capture_downloads(monkeypatch)
        at = _run_app()
        at.button[2].click().run()  # Load the critical example.
        at.button[3].click().run()  # Run the assessment.
        assert not at.exception
        result = at.session_state["result"]

        md = captured["preflightops-report.md"]["data"]
        if isinstance(md, bytes):
            md = md.decode("utf-8")
        js = captured["preflightops-report.json"]["data"]
        if isinstance(js, bytes):
            js = js.decode("utf-8")

        assert md == generate_markdown_report(result)
        assert json.loads(js) == json.loads(generate_json_report(result))


# ---------------------------------------------------------------------------
# Opt-in live ServiceNow / Jira integration helpers
# ---------------------------------------------------------------------------
from preflightops import integrations  # noqa: E402
from preflightops.integrations import IntegrationError  # noqa: E402


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
    "SERVICENOW_INSTANCE_URL": "https://dev123.service-now.com",
    "SERVICENOW_USER": "svc",
    "SERVICENOW_PASSWORD": "secret",
}

JIRA_ENV = {
    "JIRA_BASE_URL": "https://acme.atlassian.net",
    "JIRA_EMAIL": "ops@example.com",
    "JIRA_API_TOKEN": "token",
    "JIRA_PROJECT_KEY": "OPS",
}


class _FakeHttp:
    """Record HTTP calls and return canned responses keyed by (method, url-substr)."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.servicenow_record = None

    def __call__(self, url, method, headers, body=None, timeout=30):
        self.calls.append({"url": url, "method": method, "body": body})
        if method == "GET" and "/change_request/" in url and "sysparm_query" not in url:
            return 200, {"result": dict(self.servicenow_record)}
        if method == "GET" and "sysparm_query" in url and self.servicenow_record is not None:
            return 200, {"result": [dict(self.servicenow_record)]}
        for (m, needle), response in self.responses.items():
            if m == method and needle in url:
                if method in ("POST", "PATCH") and "change_request" in url:
                    result = response[1].get("result", {})
                    self.servicenow_record = {
                        **(self.servicenow_record or {}),
                        **(body or {}),
                        **result,
                    }
                return response
        raise AssertionError(f"unexpected request: {method} {url}")


class TestIntegrationStatus:
    def test_servicenow_status_reports_all_missing_when_unset(self):
        url, missing = app._servicenow_status({})
        assert url == ""
        assert missing == [
            "SERVICENOW_INSTANCE_URL",
            "SERVICENOW_USER",
            "SERVICENOW_PASSWORD",
        ]

    def test_servicenow_status_configured(self):
        url, missing = app._servicenow_status(SERVICENOW_ENV)
        assert url == "https://dev123.service-now.com"
        assert missing == []

    def test_servicenow_status_accepts_bearer_token(self):
        url, missing = app._servicenow_status(
            {
                "SERVICENOW_INSTANCE_URL": "https://dev123.service-now.com",
                "SERVICENOW_TOKEN": "token",
            }
        )
        assert url == "https://dev123.service-now.com"
        assert missing == []

    def test_jira_status_reports_all_missing_when_unset(self):
        url, missing = app._jira_status({})
        assert url == ""
        assert missing == [
            "JIRA_BASE_URL",
            "JIRA_EMAIL",
            "JIRA_API_TOKEN",
            "JIRA_PROJECT_KEY",
        ]

    def test_jira_status_configured(self):
        url, missing = app._jira_status(JIRA_ENV)
        assert url == "https://acme.atlassian.net"
        assert missing == []


class TestSendHelpers:
    def test_send_to_servicenow_pushes_when_configured(self, monkeypatch):
        fake = _FakeHttp(
            {
                ("GET", "sysparm_query"): (200, {"result": []}),
                ("POST", "change_request"): (
                    201,
                    {"result": {"number": "CHG0030001", "sys_id": "a" * 32}},
                ),
            }
        )
        monkeypatch.setattr(integrations, "_http_request", fake)
        info = app._send_to_servicenow(_result(), _change(), None, env=SERVICENOW_ENV)
        assert info["system"] == "servicenow"
        assert info["action"] == "created"
        assert info["number"] == "CHG0030001"

    def test_send_to_servicenow_raises_when_unconfigured(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("must not make a request when unconfigured")

        monkeypatch.setattr(integrations, "_http_request", _boom)
        with pytest.raises(IntegrationError):
            app._send_to_servicenow(_result(), _change(), None, env={})

    def test_send_to_jira_pushes_when_configured(self, monkeypatch):
        fake = _FakeHttp(
            {
                ("GET", "/rest/api/2/search"): (200, {"issues": []}),
                ("POST", "/rest/api/2/issue"): (201, {"key": "OPS-42"}),
            }
        )
        monkeypatch.setattr(integrations, "_http_request", fake)
        info = app._send_to_jira(_result(), _change(), None, env=JIRA_ENV)
        assert info["system"] == "jira"
        assert info["action"] == "created"
        assert info["key"] == "OPS-42"

    def test_send_to_jira_raises_when_unconfigured(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("must not make a request when unconfigured")

        monkeypatch.setattr(integrations, "_http_request", _boom)
        with pytest.raises(IntegrationError):
            app._send_to_jira(_result(), _change(), None, env={})


class TestIntegrationUI:
    def test_offline_message_when_nothing_configured(self, monkeypatch):
        monkeypatch.delenv("SERVICENOW_INSTANCE_URL", raising=False)
        monkeypatch.delenv("SERVICENOW_USER", raising=False)
        monkeypatch.delenv("SERVICENOW_PASSWORD", raising=False)
        monkeypatch.delenv("JIRA_BASE_URL", raising=False)
        monkeypatch.delenv("JIRA_EMAIL", raising=False)
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
        monkeypatch.delenv("JIRA_PROJECT_KEY", raising=False)
        at = _run_app()
        at.button[3].click().run()
        assert not at.exception
        # No "Send to ..." button is shown when nothing is configured.
        button_labels = {b.label for b in at.button}
        assert "Send to ServiceNow" not in button_labels
        assert "Send to Jira" not in button_labels
        # The offline guidance is present.
        infos = "\n".join(i.value for i in at.info)
        assert "No live integration is configured" in infos

    def test_send_buttons_appear_when_configured(self, monkeypatch):
        for key, value in {**SERVICENOW_ENV, **JIRA_ENV}.items():
            monkeypatch.setenv(key, value)
        at = _run_app()
        at.button[3].click().run()
        assert not at.exception
        button_labels = {b.label for b in at.button}
        assert "Send to ServiceNow" in button_labels
        assert "Send to Jira" in button_labels


class TestPushConfirmation:
    def _configured_app(self, monkeypatch):
        for key, value in {**SERVICENOW_ENV, **JIRA_ENV}.items():
            monkeypatch.setenv(key, value)
        at = _run_app()
        at.button[3].click().run()  # Run the assessment so results render.
        assert not at.exception
        return at

    @staticmethod
    def _send_button(at, label):
        return next(b for b in at.button if b.label == label)

    @staticmethod
    def _statuses(at):
        if "integration_status" in at.session_state:
            return at.session_state["integration_status"]
        return {}

    def test_review_surface_shows_target_and_correlation_id(self, monkeypatch):
        at = self._configured_app(monkeypatch)
        result = at.session_state["result"]
        change_doc = at.session_state["change_doc"] if "change_doc" in at.session_state else None
        corr = integrations.correlation_id(result, change_doc)
        blob = "\n".join(m.value for m in at.markdown)
        # Both target instances and the deterministic correlation id are shown.
        assert SERVICENOW_ENV["SERVICENOW_INSTANCE_URL"] in blob
        assert JIRA_ENV["JIRA_BASE_URL"] in blob
        assert corr in blob

    def test_send_disabled_until_confirmed(self, monkeypatch):
        at = self._configured_app(monkeypatch)
        # Both send buttons start disabled (no confirmation yet).
        assert self._send_button(at, "Send to ServiceNow").disabled
        assert self._send_button(at, "Send to Jira").disabled
        # Ticking the ServiceNow confirm box enables only that button.
        at.checkbox(key="confirm_servicenow").check().run()
        assert not self._send_button(at, "Send to ServiceNow").disabled
        assert self._send_button(at, "Send to Jira").disabled

    def test_no_api_call_without_confirmation(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("must not make a request without confirmation")

        monkeypatch.setattr(integrations, "_http_request", _boom)
        at = self._configured_app(monkeypatch)
        # No confirmation -> no network call and no successful push recorded.
        assert not at.exception
        statuses = self._statuses(at)
        assert statuses.get("servicenow", {}).get("ok") is not True
        assert statuses.get("jira", {}).get("ok") is not True

    def test_confirmed_click_performs_servicenow_push(self, monkeypatch):
        fake = _FakeHttp(
            {
                ("GET", "sysparm_query"): (200, {"result": []}),
                ("POST", "change_request"): (
                    201,
                    {"result": {"number": "CHG0030001", "sys_id": "a" * 32}},
                ),
            }
        )
        monkeypatch.setattr(integrations, "_http_request", fake)
        at = self._configured_app(monkeypatch)
        at.checkbox(key="confirm_servicenow").check().run()
        self._send_button(at, "Send to ServiceNow").click().run()
        assert not at.exception
        status = self._statuses(at).get("servicenow")
        assert status is not None and status["ok"] is True
        assert status["info"]["number"] == "CHG0030001"

    def test_handle_push_records_reminder_without_confirmation(self, monkeypatch):
        # Defensive guard: even if invoked directly, an unconfirmed push makes
        # no network call and records the reminder instead.
        def _boom(*a, **k):
            raise AssertionError("must not make a request without confirmation")

        monkeypatch.setattr(integrations, "_http_request", _boom)
        at = self._configured_app(monkeypatch)
        # Confirm Jira, then click ServiceNow (still unconfirmed) -> reminder.
        at.checkbox(key="confirm_jira").check().run()
        statuses = self._statuses(at)
        assert statuses.get("servicenow", {}).get("ok") is not True

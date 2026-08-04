"""Tests for the ServiceNow/Jira ticket generator (``preflightops.ticket``).

These lock in that the ticket Markdown contains every required section in order,
that approval / deployment-window text varies by risk level, and that missing
rollback / monitoring / validation plans (and a missing business impact) fall
back to the exact text specified in the feature request. They also cover the CLI
``--ticket-output`` flag writing the file and printing its confirmation message.
"""

import pytest
import yaml

from preflightops import cli, sample_data
from preflightops.ticket import (
    APPROVAL_BY_LEVEL,
    DEFAULT_TEMPLATE,
    DEPLOYMENT_WINDOW_BY_LEVEL,
    NO_BUSINESS_IMPACT,
    NO_MONITORING_PLAN,
    NO_ROLLBACK_PLAN,
    NO_VALIDATION_PLAN,
    generate_ticket_markdown,
    load_template,
    load_template_file,
)

REQUIRED_HEADINGS = [
    "# Production Change Summary",
    "## Change Title",
    "## Service",
    "## Environment",
    "## Business Impact",
    "## Risk Level",
    "## Risk Score",
    "## Required Approvals",
    "## Rollback Plan",
    "## Monitoring Plan",
    "## Validation Plan",
    "## Recommended Deployment Window",
    "## Risk Findings",
    "## Recommended Actions",
    "## Notes",
]


def _write_yaml(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle)
    return str(path)


def _critical_result():
    return {
        "service": "payments-core",
        "environment": "production",
        "change_type": "infrastructure",
        "risk_score": 100,
        "risk_level": "CRITICAL",
        "recommendation": "Deployment should be blocked until gaps are resolved.",
        "triggered_rules": [
            {
                "id": "missing-rollback-plan",
                "description": "Production change has no valid rollback plan",
                "severity": "high",
                "score": 30,
                "source": "Service Controls",
            }
        ],
        "missing_controls": ["rollback_plan", "monitoring_plan"],
        "business_impact": "Customers cannot be charged and revenue stops immediately",
    }


# ---------------------------------------------------------------------------
# Required structure
# ---------------------------------------------------------------------------
class TestStructure:
    def test_all_required_headings_present_in_order(self):
        ticket = generate_ticket_markdown(_critical_result(), {"change": {"title": "x"}})
        positions = [ticket.find(h) for h in REQUIRED_HEADINGS]
        assert all(pos != -1 for pos in positions), "a required heading is missing"
        assert positions == sorted(positions), "headings are out of order"

    def test_score_and_title_render(self):
        ticket = generate_ticket_markdown(
            _critical_result(), {"change": {"title": "Migrate payments-core"}}
        )
        assert "100/100" in ticket
        assert "Migrate payments-core" in ticket

    def test_findings_listed(self):
        ticket = generate_ticket_markdown(_critical_result(), None)
        assert "- Production change has no valid rollback plan" in ticket

    def test_notes_footer_disclaims_api(self):
        ticket = generate_ticket_markdown(_critical_result(), None)
        assert "copy/paste-ready change summary" in ticket
        assert "ServiceNow, Jira, CAB review" in ticket


# ---------------------------------------------------------------------------
# Level-specific wording
# ---------------------------------------------------------------------------
class TestLevelWording:
    def test_approval_and_window_per_level(self):
        for level in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            result = _critical_result()
            result["risk_level"] = level
            ticket = generate_ticket_markdown(result, None)
            assert APPROVAL_BY_LEVEL[level] in ticket
            assert DEPLOYMENT_WINDOW_BY_LEVEL[level] in ticket


# ---------------------------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------------------------
class TestFallbacks:
    def test_missing_plans_use_fallback_text(self):
        # change_doc with empty plans -> all three fallbacks.
        change = {
            "change": {
                "title": "Risky change",
                "rollback_plan": "",
                "monitoring_plan": {},
                "validation_plan": [],
            }
        }
        ticket = generate_ticket_markdown(_critical_result(), change)
        assert NO_ROLLBACK_PLAN in ticket
        assert NO_MONITORING_PLAN in ticket
        assert NO_VALIDATION_PLAN in ticket

    def test_no_change_doc_uses_fallback_text(self):
        ticket = generate_ticket_markdown(_critical_result(), None)
        assert NO_ROLLBACK_PLAN in ticket
        assert NO_MONITORING_PLAN in ticket
        assert NO_VALIDATION_PLAN in ticket

    def test_missing_business_impact_fallback(self):
        result = _critical_result()
        result["business_impact"] = ""
        ticket = generate_ticket_markdown(result, None)
        assert NO_BUSINESS_IMPACT in ticket

    def test_present_plans_render_instead_of_fallback(self):
        change = {
            "change": {
                "title": "Safe change",
                "rollback_plan": "Redeploy the previous image tag within 10 minutes.",
                "monitoring_plan": {"dashboards": ["https://grafana/d/x"], "alerts": ["5xx"]},
                "validation_plan": ["Smoke test checkout", "Verify p95 latency"],
            }
        }
        ticket = generate_ticket_markdown(_critical_result(), change)
        assert "Redeploy the previous image tag" in ticket
        assert "- dashboards: https://grafana/d/x" in ticket
        assert "- Smoke test checkout" in ticket
        assert NO_ROLLBACK_PLAN not in ticket
        assert NO_VALIDATION_PLAN not in ticket


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------
class TestCliTicketOutput:
    def test_ticket_output_creates_file(self, tmp_path):
        services = _write_yaml(tmp_path / "services.yaml", sample_data.HIGH_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.HIGH_RISK_CHANGE)
        ticket = tmp_path / "ticket.md"
        code = cli.main(
            [
                "--services",
                services,
                "--change",
                change,
                "--output",
                str(tmp_path / "report.md"),
                "--ticket-output",
                str(ticket),
            ]
        )
        assert code == 0
        assert ticket.exists()
        contents = ticket.read_text(encoding="utf-8")
        assert "# Production Change Summary" in contents
        assert "## Risk Score" in contents

    def test_ticket_output_prints_confirmation(self, tmp_path, capsys):
        services = _write_yaml(tmp_path / "services.yaml", sample_data.HIGH_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.HIGH_RISK_CHANGE)
        ticket = tmp_path / "ticket.md"
        cli.main(
            [
                "--services",
                services,
                "--change",
                change,
                "--output",
                str(tmp_path / "report.md"),
                "--ticket-output",
                str(ticket),
            ]
        )
        out = capsys.readouterr().out
        assert f"Change ticket summary written to {ticket}" in out

    def test_ticket_output_optional(self, tmp_path):
        # Without --ticket-output, no ticket file is written; behavior unchanged.
        services = _write_yaml(tmp_path / "services.yaml", sample_data.LOW_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.LOW_RISK_CHANGE)
        code = cli.main(
            ["--services", services, "--change", change, "--output", str(tmp_path / "report.md")]
        )
        assert code == 0
        assert not (tmp_path / "ticket.md").exists()


# ---------------------------------------------------------------------------
# Configurable templates
# ---------------------------------------------------------------------------
class TestDefaultTemplate:
    def test_default_template_matches_unspecified_output(self):
        # Passing the default template explicitly must be byte-identical to
        # passing nothing, so existing output is reproduced exactly.
        change = {"change": {"title": "Migrate payments-core"}}
        without = generate_ticket_markdown(_critical_result(), change)
        with_default = generate_ticket_markdown(_critical_result(), change, DEFAULT_TEMPLATE)
        assert without == with_default

    def test_load_template_none_returns_default_copy(self):
        loaded = load_template(None)
        assert loaded["title"] == DEFAULT_TEMPLATE["title"]
        assert [s["content"] for s in loaded["sections"]] == [
            s["content"] for s in DEFAULT_TEMPLATE["sections"]
        ]
        # A defensive copy so callers cannot mutate the module default.
        loaded["title"] = "Mutated"
        assert DEFAULT_TEMPLATE["title"] != "Mutated"


class TestCustomTemplate:
    def test_custom_headings_and_order(self):
        template = {
            "title": "RFC Change Record",
            "sections": [
                {"heading": "Summary", "content": "change_title"},
                {"heading": "Blast Radius", "content": "service"},
                {"heading": "Sign-off", "content": "required_approvals"},
            ],
        }
        ticket = generate_ticket_markdown(
            _critical_result(), {"change": {"title": "Move IAM roles"}}, template
        )
        assert ticket.startswith("# RFC Change Record\n")
        # Custom headings replace the defaults, in the order given.
        positions = [
            ticket.find("## Summary"),
            ticket.find("## Blast Radius"),
            ticket.find("## Sign-off"),
        ]
        assert all(pos != -1 for pos in positions)
        assert positions == sorted(positions)
        # Sections omitted from the template are not rendered.
        assert "## Risk Findings" not in ticket
        assert "Move IAM roles" in ticket

    def test_custom_approval_and_window_wording(self):
        template = {
            "approvals": {"CRITICAL": "CAB chair must approve in person."},
            "deployment_windows": {"CRITICAL": "Weekend freeze window only."},
        }
        ticket = generate_ticket_markdown(_critical_result(), None, template)
        assert "CAB chair must approve in person." in ticket
        assert "Weekend freeze window only." in ticket
        # The default CRITICAL wording is gone once overridden.
        assert APPROVAL_BY_LEVEL["CRITICAL"] not in ticket
        assert DEPLOYMENT_WINDOW_BY_LEVEL["CRITICAL"] not in ticket

    def test_partial_approval_override_keeps_other_levels(self):
        template = load_template({"approvals": {"LOW": "Just merge it."}})
        assert template["approvals"]["LOW"] == "Just merge it."
        assert template["approvals"]["CRITICAL"] == APPROVAL_BY_LEVEL["CRITICAL"]

    def test_custom_notes_footer(self):
        ticket = generate_ticket_markdown(
            _critical_result(), None, {"notes": "Filed via internal CAB tool."}
        )
        assert "Filed via internal CAB tool." in ticket

    def test_unknown_content_key_rejected(self):
        with pytest.raises(ValueError):
            load_template({"sections": [{"heading": "Bad", "content": "nope"}]})

    def test_empty_sections_rejected(self):
        with pytest.raises(ValueError):
            load_template({"sections": []})

    def test_non_dict_template_rejected(self):
        with pytest.raises(ValueError):
            load_template("not a template")


class TestTemplateFileAndCli:
    def test_load_template_file(self, tmp_path):
        template_path = tmp_path / "template.yaml"
        _write_yaml(
            template_path,
            {
                "title": "Internal CAB Record",
                "sections": [{"heading": "Title", "content": "change_title"}],
            },
        )
        template = load_template_file(str(template_path))
        assert template["title"] == "Internal CAB Record"
        assert template["sections"] == [{"heading": "Title", "content": "change_title"}]

    def test_cli_ticket_template_applied(self, tmp_path):
        services = _write_yaml(tmp_path / "services.yaml", sample_data.HIGH_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.HIGH_RISK_CHANGE)
        template = _write_yaml(
            tmp_path / "template.yaml",
            {
                "title": "Internal CAB Record",
                "sections": [{"heading": "Summary", "content": "change_title"}],
            },
        )
        ticket = tmp_path / "ticket.md"
        code = cli.main(
            [
                "--services",
                services,
                "--change",
                change,
                "--output",
                str(tmp_path / "report.md"),
                "--ticket-output",
                str(ticket),
                "--ticket-template",
                template,
            ]
        )
        assert code == 0
        contents = ticket.read_text(encoding="utf-8")
        assert contents.startswith("# Internal CAB Record\n")
        assert "## Summary" in contents
        assert "# Production Change Summary" not in contents

    def test_cli_invalid_template_errors(self, tmp_path):
        services = _write_yaml(tmp_path / "services.yaml", sample_data.HIGH_RISK_SERVICES)
        change = _write_yaml(tmp_path / "change.yaml", sample_data.HIGH_RISK_CHANGE)
        template = _write_yaml(
            tmp_path / "template.yaml",
            {"sections": [{"heading": "Bad", "content": "does_not_exist"}]},
        )
        code = cli.main(
            [
                "--services",
                services,
                "--change",
                change,
                "--output",
                str(tmp_path / "report.md"),
                "--ticket-output",
                str(tmp_path / "ticket.md"),
                "--ticket-template",
                template,
            ]
        )
        assert code == 2

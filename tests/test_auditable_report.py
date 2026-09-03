"""Auditable Assessment Report v1 contract and renderer tests."""

import copy
import datetime as dt
import json
import socket
from pathlib import Path

import jsonschema
import pytest

from preflightops import cli
from preflightops.assessment import (
    AssessmentContext,
    ControlObservation,
    HumanDecision,
    InputDigest,
    PolicyIdentity,
    TrustKernel,
)
from preflightops.auditable_report import (
    AuditableReportConfig,
    AuditableReportError,
    build_auditable_report_v1,
    render_assessment_markdown_v1,
    render_pr_summary_v1,
    render_ticket_summary_v1,
    serialize_auditable_report_v1,
    validate_auditable_report_v1,
)
from preflightops.report import generate_json_report

ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 9, 3, 15, 0, tzinfo=dt.UTC)
CONTEXT = AssessmentContext(
    actor_id="release-bot",
    actor_type="automation",
    run_id="8008",
    run_attempt=2,
    repository="acme/checkout-api",
    pull_request="108",
    commit="a" * 40,
    pipeline_name="preflight",
    pipeline_url="https://github.example.test/acme/checkout-api/actions/runs/8008",
)
POLICY = PolicyIdentity("production", "3.0.0", "b" * 64)


def _observation(
    control_id: str,
    status: str,
    digest_character: str,
    *,
    summary: str | None = None,
) -> ControlObservation:
    return ControlObservation(
        control_id=control_id,
        status=status,  # type: ignore[arg-type]
        summary=summary or f"{control_id} produced {status}.",
        source="stage-08-test",
        collected_at=NOW - dt.timedelta(minutes=5),
        valid_until=NOW + dt.timedelta(minutes=55),
        risk_points=25 if status == "FAIL" else 0,
        evidence_sha256=digest_character * 64,
        evidence_kind="control-result",
    )


def _assessment(*, secret_text: bool = False, human_decision: HumanDecision | None = None):
    risky = (
        "Bearer abcdefghijklmnopqrstuvwxyz <script>alert(1)</script> | injected\nheading"
        if secret_text
        else None
    )
    return TrustKernel().evaluate(
        change_id="CHG-2026-0808",
        timestamp=NOW,
        context=CONTEXT,
        policy=POLICY,
        inputs=(InputDigest("change-request", "c" * 64), InputDigest("service-catalog", "d" * 64)),
        controls=(
            _observation("rollback-plan", "PASS", "1"),
            _observation("deployment-risk", "FAIL", "2", summary=risky),
            _observation("monitoring-evidence", "UNKNOWN", "3"),
            _observation("validation-provider", "ERROR", "4"),
        ),
        risk_score=75,
        risk_level="HIGH",
        recommendation_summary="Do not proceed until the indeterminate controls are resolved.",
        evidence_links=("https://evidence.example.test/runs/8008",),
        human_decision=human_decision,
    )


def test_report_is_deterministic_strict_and_matches_schema():
    assessment = _assessment()
    first = build_auditable_report_v1(assessment)
    second = build_auditable_report_v1(copy.deepcopy(assessment))

    assert first == second
    assert serialize_auditable_report_v1(first) == serialize_auditable_report_v1(second)
    assert serialize_auditable_report_v1(first).endswith(b"\n")
    assert first["report_id"].endswith(first["integrity"]["value"])
    validate_auditable_report_v1(first)

    schema = json.loads(
        (ROOT / "schemas" / "assessment-report-v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(first, schema, format_checker=jsonschema.FormatChecker())


def test_golden_report_bytes_are_stable():
    expected = (
        ROOT / "tests" / "fixtures" / "reports" / "assessment-report-v1.golden.json"
    ).read_bytes()
    assert serialize_auditable_report_v1(build_auditable_report_v1(_assessment())) == expected


def test_all_statuses_are_explicit_and_error_unknown_fail_closed():
    report = build_auditable_report_v1(_assessment())
    controls = report["controls"]
    assert controls["counts"] == {"PASS": 1, "FAIL": 1, "UNKNOWN": 1, "ERROR": 1}
    assert [item["status"] for item in controls["passed"]] == ["PASS"]
    assert [item["status"] for item in controls["failed"]] == ["FAIL"]
    assert [item["status"] for item in controls["unknown"]] == ["UNKNOWN"]
    assert [item["status"] for item in controls["errors"]] == ["ERROR"]
    assert report["decision"]["verdict"] == "INDETERMINATE"
    assert report["decision"]["technical_recommendation"]["action"] == "DO_NOT_PROCEED"
    assert report["decision"]["technical_recommendation"]["grants_approval"] is False


def test_human_decision_remains_separate_from_technical_recommendation():
    decision = HumanDecision(
        status="RECORDED",
        decision="DEFER",
        actor_id="cab-chair",
        decided_at=NOW,
        rationale_code="awaiting-evidence",
    )
    report = build_auditable_report_v1(_assessment(human_decision=decision))
    assert report["decision"]["human_decision"]["decision"] == "DEFER"
    assert report["decision"]["technical_recommendation"]["grants_approval"] is False
    assert report["scores"]["risk"] == {"value": 75, "level": "HIGH"}
    assert (
        report["scores"]["confidence"]
        == build_auditable_report_v1(_assessment())["scores"]["confidence"]
    )


def test_full_markdown_is_scan_ordered_and_contains_audit_surface():
    markdown = render_assessment_markdown_v1(build_auditable_report_v1(_assessment()))
    headings = [
        "## 30-second review",
        "## Top blockers",
        "## Unknown and errors",
        "## Failed controls",
        "## Passed controls",
        "## Evidence freshness",
        "## Provenance",
        "## Next actions",
        "## Automation Details",
        "## Audit metadata",
    ]
    positions = [markdown.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "Technical recommendation only" in markdown
    assert "Human decision" in markdown
    assert "**ERROR**" in markdown
    assert "**UNKNOWN**" in markdown
    assert "**PASS**" in markdown
    assert "Assessment hash" in markdown
    assert markdown.endswith("\n")


def test_redaction_and_markdown_escaping_remove_adversarial_content():
    report = build_auditable_report_v1(_assessment(secret_text=True))
    json_bytes = serialize_auditable_report_v1(report)
    markdown = render_assessment_markdown_v1(report)
    pr_summary = render_pr_summary_v1(report)
    ticket_summary = render_ticket_summary_v1(report)
    combined = json_bytes.decode() + markdown + pr_summary + ticket_summary

    assert "abcdefghijklmnopqrstuvwxyz" not in combined
    assert "Bearer [redacted]" in combined
    assert "<script>" not in markdown
    assert "&lt;script&gt;" in markdown
    assert "| injected\nheading" not in markdown
    assert "\\| injected heading" in markdown


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/report",
        "https://user:password@example.test/report",
        "https://example.test/report?token=secret",
        "https://example.test/report#private",
        "javascript:alert(1)",
    ],
)
def test_unsafe_full_report_links_are_omitted(url):
    summary = render_pr_summary_v1(build_auditable_report_v1(_assessment()), url)
    assert url not in summary
    assert "Open the full assessment report" not in summary


def test_safe_full_report_link_is_visible_near_the_pr_decision():
    url = "https://github.example.test/acme/checkout-api/actions/runs/8008"
    summary = render_pr_summary_v1(build_auditable_report_v1(_assessment()), url)
    assert f"[Open the full assessment report]({url})" in summary
    assert summary.index("Open the full assessment report") < summary.index("### Top blockers")


def test_pr_and_ticket_budgets_are_enforced_at_line_boundaries():
    config = AuditableReportConfig(
        max_text_length=320,
        pr_summary_max_characters=1000,
        ticket_summary_max_characters=1500,
    )
    report = build_auditable_report_v1(_assessment(), config)
    pr_summary = render_pr_summary_v1(report)
    ticket_summary = render_ticket_summary_v1(report)
    assert len(pr_summary) <= 1000
    assert len(ticket_summary) <= 1500
    assert "Output truncated deterministically" in pr_summary
    assert "Output truncated deterministically" in ticket_summary
    assert pr_summary.endswith("\n")
    assert ticket_summary.endswith("\n")


def test_automation_details_can_be_omitted_without_changing_decision():
    included = build_auditable_report_v1(_assessment())
    omitted = build_auditable_report_v1(
        _assessment(), AuditableReportConfig(include_automation_details=False)
    )
    assert omitted["automation_details"] == {"included": False}
    assert included["decision"] == omitted["decision"]
    assert included["scores"] == omitted["scores"]
    assert "## Automation Details" not in render_assessment_markdown_v1(omitted)


def test_tamper_and_fail_open_mutations_are_rejected():
    report = build_auditable_report_v1(_assessment())
    tampered = copy.deepcopy(report)
    tampered["scores"]["risk"]["value"] = 1
    with pytest.raises(AuditableReportError, match="integrity"):
        validate_auditable_report_v1(tampered)

    fail_open = copy.deepcopy(report)
    fail_open["decision"]["verdict"] = "READY_FOR_HUMAN_REVIEW"
    fail_open["decision"]["technical_recommendation"]["action"] = "PROCEED"
    with pytest.raises(AuditableReportError, match="fail closed"):
        validate_auditable_report_v1(fail_open)


@pytest.mark.parametrize(
    "config,match",
    [
        (AuditableReportConfig(max_text_length=79), "max_text_length"),
        (AuditableReportConfig(top_blockers_limit=0), "top_blockers_limit"),
        (AuditableReportConfig(next_actions_limit=33), "next_actions_limit"),
        (AuditableReportConfig(pr_summary_max_characters=999), "pr_summary"),
        (AuditableReportConfig(ticket_summary_max_characters=1499), "ticket_summary"),
    ],
)
def test_invalid_rendering_limits_fail_closed(config, match):
    with pytest.raises(AuditableReportError, match=match):
        build_auditable_report_v1(_assessment(), config)


def test_build_and_render_are_offline_and_do_not_mutate_legacy_outputs(monkeypatch):
    assessment = _assessment()
    original = copy.deepcopy(assessment)
    legacy = {"risk_score": 25, "risk_level": "LOW", "triggered_rules": []}
    legacy_json = generate_json_report(legacy)

    def deny_network(*args, **kwargs):
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "socket", deny_network)
    report = build_auditable_report_v1(assessment)
    render_assessment_markdown_v1(report)
    render_pr_summary_v1(report, "https://example.test/report")
    render_ticket_summary_v1(report, "https://example.test/report")

    assert assessment == original
    assert generate_json_report(legacy) == legacy_json


def test_report_rejects_unknown_fields():
    report = build_auditable_report_v1(_assessment())
    report["unexpected"] = True
    with pytest.raises(AuditableReportError, match="unexpected"):
        validate_auditable_report_v1(report)


def test_report_render_cli_writes_only_explicit_outputs(tmp_path, monkeypatch):
    assessment_path = tmp_path / "assessment.json"
    assessment_path.write_text(json.dumps(_assessment()), encoding="utf-8")
    json_output = tmp_path / "auditable.json"
    markdown_output = tmp_path / "auditable.md"
    pr_output = tmp_path / "pr.md"
    ticket_output = tmp_path / "ticket.md"

    def deny_network(*args, **kwargs):
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "socket", deny_network)
    exit_code = cli.main(
        [
            "report",
            "render",
            "--assessment",
            str(assessment_path),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
            "--pr-summary-output",
            str(pr_output),
            "--ticket-summary-output",
            str(ticket_output),
            "--full-report-url",
            "https://example.test/artifacts/8008",
        ]
    )

    assert exit_code == 0
    validate_auditable_report_v1(json.loads(json_output.read_text(encoding="utf-8")))
    assert "30-second review" in markdown_output.read_text(encoding="utf-8")
    assert "Open the full assessment report" in pr_output.read_text(encoding="utf-8")
    assert "Automatic approval: **No**" in ticket_output.read_text(encoding="utf-8")
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "assessment.json",
        "auditable.json",
        "auditable.md",
        "pr.md",
        "ticket.md",
    ]


def test_report_render_cli_refuses_existing_output_without_overwrite(tmp_path, capsys):
    assessment_path = tmp_path / "assessment.json"
    assessment_path.write_text(json.dumps(_assessment()), encoding="utf-8")
    output = tmp_path / "report.json"
    output.write_text("keep-me", encoding="utf-8")

    exit_code = cli.main(
        [
            "report",
            "render",
            "--assessment",
            str(assessment_path),
            "--json-output",
            str(output),
        ]
    )

    assert exit_code == 2
    assert output.read_text(encoding="utf-8") == "keep-me"
    assert "--overwrite" in capsys.readouterr().err


def test_report_render_cli_requires_an_explicit_output(tmp_path, capsys):
    assessment_path = tmp_path / "assessment.json"
    assessment_path.write_text(json.dumps(_assessment()), encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["report", "render", "--assessment", str(assessment_path)])
    assert excinfo.value.code == 2
    assert "at least one explicit output path" in capsys.readouterr().err

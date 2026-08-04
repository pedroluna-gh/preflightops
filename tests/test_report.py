"""Tests for the Markdown report generator (``preflightops.report``).

The report is what reviewers read in a pull request, so these lock in that the
summary fields, triggered rules (rendered under the grouped ``Score Breakdown``
section), missing controls, and business impact sections all render correctly
for both populated and empty results.
"""

import json

from preflightops import __version__
from preflightops.report import generate_json_report, generate_markdown_report


def _section(report, heading):
    """Return the lines of a ``## heading`` section, excluding the heading."""
    lines = report.split("\n")
    start = lines.index(f"## {heading}")
    body = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        body.append(line)
    return [line for line in body if line.strip()]


# ---------------------------------------------------------------------------
# A fully populated result
# ---------------------------------------------------------------------------
def populated_result():
    return {
        "service": "payments-core",
        "environment": "production",
        "change_type": "infrastructure",
        "risk_score": 100,
        "risk_level": "CRITICAL",
        "recommendation": "Deployment should be blocked until gaps are resolved.",
        "triggered_rules": [
            {
                "id": "production-change",
                "description": "Change targets production environment",
                "severity": "medium",
                "score": 20,
                "source": "Service Controls",
            },
            {
                "id": "missing-rollback-plan",
                "description": "Production change has no valid rollback plan",
                "severity": "high",
                "score": 30,
                "source": "Service Controls",
            },
        ],
        "missing_controls": ["rollback_plan", "monitoring_plan"],
        "business_impact": "Customers cannot be charged and revenue stops immediately",
    }


class TestPopulatedReport:
    def test_has_title(self):
        report = generate_markdown_report(populated_result())
        assert report.startswith("# PreflightOps Risk Report")

    def test_summary_fields_render(self):
        report = generate_markdown_report(populated_result())
        summary = _section(report, "Summary")
        assert "Service: payments-core" in summary
        assert "Environment: production" in summary
        assert "Change Type: infrastructure" in summary
        assert "Risk Score: 100/100" in summary
        assert "Risk Level: CRITICAL" in summary
        assert f"PreflightOps Version: {__version__}" in summary

    def test_recommendation_renders(self):
        report = generate_markdown_report(populated_result())
        recommendation = _section(report, "Recommendation")
        assert recommendation == [
            "Deployment should be blocked until gaps are resolved."
        ]

    def test_triggered_rules_render(self):
        report = generate_markdown_report(populated_result())
        rules = _section(report, "Score Breakdown")
        assert (
            "- production-change | medium | +20 | "
            "Change targets production environment"
        ) in rules
        assert (
            "- missing-rollback-plan | high | +30 | "
            "Production change has no valid rollback plan"
        ) in rules

    def test_score_breakdown_groups_by_source(self):
        # Both rules share the "Service Controls" source, so they collapse into
        # a single group worth 50 points (100% of the score) with 2 findings.
        report = generate_markdown_report(populated_result())
        breakdown = _section(report, "Score Breakdown")
        assert "### Service Controls — +50 pts (100%, 2 findings)" in breakdown

    def test_missing_controls_render(self):
        report = generate_markdown_report(populated_result())
        controls = _section(report, "Missing Controls")
        assert "- rollback_plan" in controls
        assert "- monitoring_plan" in controls

    def test_business_impact_renders(self):
        report = generate_markdown_report(populated_result())
        impact = _section(report, "Business Impact")
        assert impact == [
            "Customers cannot be charged and revenue stops immediately"
        ]


# ---------------------------------------------------------------------------
# An empty / low-risk result
# ---------------------------------------------------------------------------
def empty_result():
    return {
        "service": "reporting-api",
        "environment": "staging",
        "change_type": "deployment",
        "risk_score": 0,
        "risk_level": "LOW",
        "recommendation": "Change appears low risk. Proceed with normal deployment process.",
        "triggered_rules": [],
        "missing_controls": [],
        "business_impact": "",
    }


class TestEmptyReport:
    def test_triggered_rules_show_none(self):
        report = generate_markdown_report(empty_result())
        assert _section(report, "Score Breakdown") == ["- None"]

    def test_missing_controls_show_none(self):
        report = generate_markdown_report(empty_result())
        assert _section(report, "Missing Controls") == ["- None"]

    def test_business_impact_falls_back(self):
        report = generate_markdown_report(empty_result())
        assert _section(report, "Business Impact") == ["Not specified"]

    def test_summary_still_renders(self):
        report = generate_markdown_report(empty_result())
        summary = _section(report, "Summary")
        assert "Service: reporting-api" in summary
        assert "Risk Level: LOW" in summary
        assert "Risk Score: 0/100" in summary


# ---------------------------------------------------------------------------
# Robustness: a sparse dict should not crash the generator
# ---------------------------------------------------------------------------
def test_handles_missing_keys_gracefully():
    report = generate_markdown_report({})
    assert "# PreflightOps Risk Report" in report
    assert "## Summary" in report
    # Defaults render rather than raising KeyError.
    assert "Risk Score: 0/100" in report
    assert "## Score Breakdown" in report
    assert "## Missing Controls" in report
    assert "## Business Impact" in report


def test_json_report_includes_package_version():
    report = json.loads(generate_json_report(populated_result()))
    assert report["preflightops_version"] == __version__

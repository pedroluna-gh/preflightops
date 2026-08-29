"""Markdown, GitHub comment, JSON, and static HTML risk reports."""

from __future__ import annotations

import html
import json
from urllib.parse import urlparse

from ._version import __version__
from .risk_engine import SOURCE_ORDER

_RISK_ICONS = {
    "LOW": "🟢",
    "MEDIUM": "🟡",
    "HIGH": "🟠",
    "CRITICAL": "🔴",
}

_CONTROL_ACTIONS = {
    "service_owner": "Assign an accountable service owner before approval.",
    "runbook": "Link an actionable service runbook for responders.",
    "business_impact": "Document the customer and business impact of failure.",
    "rollback_plan": "Add a tested rollback plan with trigger conditions.",
    "monitoring_plan": "Define dashboards, alerts, and the post-deploy watch window.",
    "validation_plan": "Define measurable post-deploy validation and success criteria.",
}


def _group_by_source(triggered: list) -> dict:
    """Group triggered findings by their ``source`` category, preserving order.

    Known sources are ordered per ``SOURCE_ORDER``; any unexpected sources are
    appended afterwards in first-seen order.
    """
    groups: dict[str, list[dict]] = {}
    for rule in triggered:
        source = rule.get("source", "Other")
        groups.setdefault(source, []).append(rule)

    ordered: dict[str, list[dict]] = {}
    for source in SOURCE_ORDER:
        if source in groups:
            ordered[source] = groups[source]
    for source, rules in groups.items():
        if source not in ordered:
            ordered[source] = rules
    return ordered


def _score_breakdown(triggered: list) -> list:
    """Return per-source totals and percentage shares of the total score."""
    groups = _group_by_source(triggered)
    total = sum(rule.get("score", 0) for rule in triggered)

    breakdown = []
    for source, rules in groups.items():
        group_score = sum(rule.get("score", 0) for rule in rules)
        share = (group_score / total * 100) if total else 0.0
        breakdown.append(
            {
                "source": source,
                "score": group_score,
                "share_percent": round(share, 1),
                "count": len(rules),
                "rules": rules,
            }
        )
    return breakdown


def _markdown_cell(value: object) -> str:
    """Escape a value for a compact GitHub Markdown table cell."""
    rendered = html.escape(str(value if value is not None else ""), quote=False)
    return rendered.replace("|", "\\|").replace("\n", " ")


def _safe_report_url(value: object) -> str | None:
    """Return an HTTP(S) report URL, rejecting executable or malformed schemes."""
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if any(character.isspace() or ord(character) < 32 for character in candidate):
        return None
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate.replace("(", "%28").replace(")", "%29")


def _top_actions(result: dict, limit: int = 3) -> list[str]:
    """Derive a short, deterministic action list for reviewers."""
    actions: list[str] = []
    for control in result.get("missing_controls", []):
        action = _CONTROL_ACTIONS.get(control, f"Resolve the missing control: {control}.")
        if action not in actions:
            actions.append(action)

    severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    findings = sorted(
        result.get("triggered_rules", []),
        key=lambda rule: (
            severity_rank.get(str(rule.get("severity", "")).lower(), 0),
            rule.get("score", 0),
        ),
        reverse=True,
    )
    for finding in findings:
        action = f"Review {finding.get('source', 'finding')}: {finding.get('description', '')}."
        if action not in actions:
            actions.append(action)

    recommendation = str(result.get("recommendation", "")).strip()
    if recommendation and recommendation not in actions:
        actions.append(recommendation)
    return actions[:limit]


def generate_markdown_report(result: dict) -> str:
    """Render a risk result as a Markdown report."""
    lines = []
    lines.append("# PreflightOps Risk Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"Service: {result.get('service', '')}")
    lines.append(f"Environment: {result.get('environment', '')}")
    lines.append(f"Change Type: {result.get('change_type', '')}")
    lines.append(f"Risk Score: {result.get('risk_score', 0)}/100")
    lines.append(f"Risk Level: {result.get('risk_level', '')}")
    policy = result.get("policy_pack", {})
    lines.append(f"Policy Pack: {policy.get('name', 'default')} (v{policy.get('version', '1')})")
    if policy.get("digest"):
        lines.append(f"Policy Digest: {policy['digest']}")
    lineage = policy.get("lineage", [])
    if lineage:
        lines.append(f"Policy Lineage: {' -> '.join(lineage)}")
    lines.append(f"PreflightOps Version: {__version__}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append("")
    lines.append(result.get("recommendation", ""))
    lines.append("")
    lines.append("## Score Breakdown")
    lines.append("")
    triggered = result.get("triggered_rules", [])
    if triggered:
        breakdown = _score_breakdown(triggered)
        for group in breakdown:
            findings = group["count"]
            noun = "finding" if findings == 1 else "findings"
            lines.append(
                f"### {group['source']} — +{group['score']} pts "
                f"({group['share_percent']:.0f}%, {findings} {noun})"
            )
            lines.append("")
            for rule in group["rules"]:
                lines.append(
                    f"- {rule.get('id')} | {rule.get('severity')} | "
                    f"+{rule.get('score')} | {rule.get('description')}"
                )
            lines.append("")
    else:
        lines.append("- None")
        lines.append("")
    lines.append("## Missing Controls")
    lines.append("")
    missing = result.get("missing_controls", [])
    if missing:
        for control in missing:
            lines.append(f"- {control}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Business Impact")
    lines.append("")
    lines.append(result.get("business_impact") or "Not specified")
    lines.append("")

    lines.append("## Monitoring Evidence")
    lines.append("")
    monitoring = result.get("monitor_validation", {})
    lines.append(f"Validation Status: {str(monitoring.get('status', 'not-evaluated')).upper()}")
    lines.append(f"Valid Dashboards: {monitoring.get('valid_dashboard_count', 0)}")
    lines.append(f"Enabled Inventory Monitors: {monitoring.get('enabled_monitor_count', 0)}")
    providers = monitoring.get("providers", [])
    lines.append(f"Providers: {', '.join(providers) if providers else 'None declared'}")
    lines.append("")

    decision = result.get("decision_record", {})
    human = decision.get("human_decision", {})
    lines.append("## Governance Decision Boundary")
    lines.append("")
    lines.append(f"Verified Exceptions: {decision.get('verified_exception_count', 0)}")
    lines.append(f"Human Decision: {human.get('status', 'not_recorded')}")
    lines.append(
        f"Decision Authority: {human.get('authority', 'external_cab_or_change_management')}"
    )
    lines.append("Automatic Approval: No")
    lines.append("")

    return "\n".join(lines)


def generate_github_comment(result: dict, full_report_url: str | None = None) -> str:
    """Render a compact, scan-friendly pull-request comment.

    The output is a file artifact only; publishing or updating a PR comment is
    deliberately left to the consuming workflow and its explicit permissions.
    """
    level = str(result.get("risk_level", "UNKNOWN")).upper()
    icon = _RISK_ICONS.get(level, "⚪")
    score = result.get("risk_score", 0)
    policy = result.get("policy_pack", {})
    triggered = result.get("triggered_rules", [])
    groups = _group_by_source(triggered)

    lines = [
        "<!-- preflightops-report -->",
        "## PreflightOps change risk review",
        "",
        f"### {icon} `{level}` risk · **{score}/100**",
        "",
        "| Service | Environment | Change type | Policy | Findings |",
        "| --- | --- | --- | --- | ---: |",
        (
            f"| {_markdown_cell(result.get('service', ''))} "
            f"| {_markdown_cell(result.get('environment', ''))} "
            f"| {_markdown_cell(result.get('change_type', ''))} "
            f"| {_markdown_cell(policy.get('name', 'default'))} "
            f"| {len(triggered)} |"
        ),
        "",
        f"**Decision guidance:** {_markdown_cell(result.get('recommendation', ''))}",
        "",
        "### Top actions",
        "",
    ]

    actions = _top_actions(result)
    if actions:
        lines.extend(
            f"{index}. {_markdown_cell(action)}" for index, action in enumerate(actions, 1)
        )
    else:
        lines.append("1. No additional remediation is required by the active policy.")

    lines.extend(["", "### Findings by source", ""])
    if groups:
        for source, rules in groups.items():
            group_score = sum(rule.get("score", 0) for rule in rules)
            lines.extend(
                [
                    f"<details><summary><strong>{html.escape(str(source))}</strong> "
                    f"— {len(rules)} finding(s), +{group_score} pts</summary>",
                    "",
                    "| Severity | Rule | Points | Evidence |",
                    "| --- | --- | ---: | --- |",
                ]
            )
            for rule in rules:
                lines.append(
                    f"| {_markdown_cell(str(rule.get('severity', '')).upper())} "
                    f"| `{_markdown_cell(rule.get('id', ''))}` "
                    f"| +{rule.get('score', 0)} "
                    f"| {_markdown_cell(rule.get('description', ''))} |"
                )
            lines.extend(["", "</details>", ""])
    else:
        lines.extend(["No risk findings were triggered.", ""])

    monitoring = result.get("monitor_validation", {})
    decision = result.get("decision_record", {})
    lines.extend(
        [
            "### Evidence status",
            "",
            "| Monitoring | Dashboards | Enabled monitors | Missing controls |",
            "| --- | ---: | ---: | ---: |",
            (
                f"| {_markdown_cell(str(monitoring.get('status', 'not-evaluated')).upper())} "
                f"| {monitoring.get('valid_dashboard_count', 0)} "
                f"| {monitoring.get('enabled_monitor_count', 0)} "
                f"| {len(result.get('missing_controls', []))} |"
            ),
            "",
            (
                "**Governance boundary:** technical recommendation only; "
                f"{decision.get('verified_exception_count', 0)} verified exception(s); "
                "human decision not recorded; automatic approval disabled."
            ),
            "",
        ]
    )

    safe_url = _safe_report_url(full_report_url)
    if safe_url:
        lines.extend([f"[Open the full report artifact]({safe_url})", ""])
    lines.append(f"<sub>Generated by PreflightOps {__version__}</sub>")
    return "\n".join(lines)


def generate_html_report(result: dict, full_report_url: str | None = None) -> str:
    """Render a dependency-free, accessible static HTML report."""

    def esc(value: object) -> str:
        return html.escape(str(value if value is not None else ""), quote=True)

    level = str(result.get("risk_level", "UNKNOWN")).upper()
    score = result.get("risk_score", 0)
    triggered = result.get("triggered_rules", [])
    policy = result.get("policy_pack", {})
    groups = _group_by_source(triggered)

    action_items = "".join(f"<li>{esc(action)}</li>" for action in _top_actions(result))
    if not action_items:
        action_items = "<li>No additional remediation is required by the active policy.</li>"

    finding_sections = []
    for source, rules in groups.items():
        rows = "".join(
            "<tr>"
            f'<td><span class="severity">{esc(str(rule.get("severity", "")).upper())}</span></td>'
            f"<td><code>{esc(rule.get('id', ''))}</code></td>"
            f'<td class="number">+{esc(rule.get("score", 0))}</td>'
            f"<td>{esc(rule.get('description', ''))}</td>"
            "</tr>"
            for rule in rules
        )
        finding_sections.append(
            '<section class="panel">'
            f"<h3>{esc(source)}</h3>"
            '<div class="table-wrap"><table>'
            "<thead><tr><th>Severity</th><th>Rule</th><th>Points</th><th>Evidence</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></section>"
        )
    if not finding_sections:
        finding_sections.append(
            '<section class="panel"><p>No risk findings were triggered.</p></section>'
        )

    missing = result.get("missing_controls", [])
    missing_html = "".join(f"<li><code>{esc(control)}</code></li>" for control in missing)
    if not missing_html:
        missing_html = "<li>None</li>"

    monitoring = result.get("monitor_validation", {})
    decision = result.get("decision_record", {})
    safe_url = _safe_report_url(full_report_url)
    report_link = (
        f'<p><a class="button" href="{esc(safe_url)}">Open source workflow run</a></p>'
        if safe_url
        else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PreflightOps risk report — {esc(result.get("service", "change"))}</title>
  <style>
    :root {{ color-scheme: light dark; --bg:#f6f8fa; --panel:#fff; --text:#1f2328; --muted:#59636e; --line:#d0d7de; --accent:#0969da; }}
    @media (prefers-color-scheme: dark) {{ :root {{ --bg:#0d1117; --panel:#161b22; --text:#e6edf3; --muted:#8b949e; --line:#30363d; --accent:#58a6ff; }} }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
    main {{ width:min(1100px,calc(100% - 32px)); margin:32px auto; }} header,.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:24px; margin-bottom:16px; }}
    h1,h2,h3 {{ line-height:1.2; }} h1 {{ margin:0 0 8px; }} .muted {{ color:var(--muted); }} .risk {{ display:inline-block; padding:5px 10px; border-radius:999px; font-weight:700; border:1px solid currentColor; }}
    .risk-low {{ color:#1a7f37; }} .risk-medium {{ color:#9a6700; }} .risk-high {{ color:#bc4c00; }} .risk-critical {{ color:#cf222e; }}
    .summary {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-top:20px; }} .metric {{ border:1px solid var(--line); border-radius:8px; padding:12px; }} .metric strong {{ display:block; font-size:1.25rem; }}
    .table-wrap {{ overflow-x:auto; }} table {{ border-collapse:collapse; width:100%; }} th,td {{ border-bottom:1px solid var(--line); padding:10px; text-align:left; vertical-align:top; }} th {{ color:var(--muted); font-size:.8rem; text-transform:uppercase; }} .number {{ text-align:right; white-space:nowrap; }}
    code {{ background:var(--bg); border-radius:4px; padding:2px 5px; }} .severity {{ font-weight:700; }} .button {{ display:inline-block; background:var(--accent); color:white; padding:8px 12px; border-radius:6px; text-decoration:none; }} footer {{ color:var(--muted); text-align:center; padding:16px; }}
    @media print {{ body {{ background:white; color:black; }} main {{ width:100%; margin:0; }} header,.panel {{ break-inside:avoid; box-shadow:none; }} .button {{ display:none; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <p class="muted">Pre-deployment change review</p>
    <h1>{esc(result.get("service", ""))}</h1>
    <span class="risk risk-{esc(level.lower())}">{esc(_RISK_ICONS.get(level, "⚪"))} {esc(level)} · {esc(score)}/100</span>
    <div class="summary" aria-label="Assessment summary">
      <div class="metric"><span class="muted">Environment</span><strong>{esc(result.get("environment", ""))}</strong></div>
      <div class="metric"><span class="muted">Change type</span><strong>{esc(result.get("change_type", ""))}</strong></div>
      <div class="metric"><span class="muted">Policy</span><strong>{esc(policy.get("name", "default"))}</strong></div>
      <div class="metric"><span class="muted">Findings</span><strong>{len(triggered)}</strong></div>
    </div>
  </header>
  <section class="panel"><h2>Decision guidance</h2><p>{esc(result.get("recommendation", ""))}</p><h3>Top actions</h3><ol>{action_items}</ol>{report_link}</section>
  <h2>Findings by source</h2>
  {"".join(finding_sections)}
  <section class="panel"><h2>Control and evidence readiness</h2><div class="summary">
    <div class="metric"><span class="muted">Monitoring</span><strong>{esc(str(monitoring.get("status", "not-evaluated")).upper())}</strong></div>
    <div class="metric"><span class="muted">Valid dashboards</span><strong>{esc(monitoring.get("valid_dashboard_count", 0))}</strong></div>
    <div class="metric"><span class="muted">Enabled monitors</span><strong>{esc(monitoring.get("enabled_monitor_count", 0))}</strong></div>
    <div class="metric"><span class="muted">Verified exceptions</span><strong>{esc(decision.get("verified_exception_count", 0))}</strong></div>
  </div><h3>Governance boundary</h3><p>Technical recommendation only. Human decision is not recorded and automatic approval is disabled.</p><h3>Missing controls</h3><ul>{missing_html}</ul><h3>Business impact</h3><p>{esc(result.get("business_impact") or "Not specified")}</p></section>
  <footer>Generated by PreflightOps {esc(__version__)} · Static report, no scripts or external assets</footer>
</main>
</body>
</html>
"""


def generate_json_report(result: dict) -> str:
    """Render a risk result as a pretty-printed JSON string.

    Adds a ``score_breakdown`` grouped summary (per-source totals and shares)
    alongside the existing per-rule ``source`` field, without mutating the input.
    """
    enriched = dict(result)
    enriched["preflightops_version"] = __version__
    breakdown = _score_breakdown(result.get("triggered_rules", []))
    enriched["score_breakdown"] = [
        {
            "source": group["source"],
            "score": group["score"],
            "share_percent": group["share_percent"],
            "count": group["count"],
        }
        for group in breakdown
    ]
    return json.dumps(enriched, indent=2)

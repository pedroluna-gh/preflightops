"""Markdown and JSON report generators for a risk result."""

import json

from ._version import __version__
from .risk_engine import SOURCE_ORDER


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

    return "\n".join(lines)


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

"""Deterministic, secret-safe reports derived from Assessment Contract v1.

This module is intentionally pure and offline.  It projects the strict assessment
contract into a report contract and human views without reading the clock,
environment, filesystem, network, or random state.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .assessment import validate_assessment_v1
from .evidence import canonical_json

REPORT_SCHEMA_VERSION = "1.0"
REPORT_CANONICALIZATION_PROFILE = "preflightops-canonical-json-v1"
REPORT_REDACTION_PROFILE = "preflightops-report-redaction-v1"

_CONTROL_STATUSES = ("PASS", "FAIL", "UNKNOWN", "ERROR")
_FRESHNESS = ("FRESH", "STALE", "UNKNOWN")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|authorization|cookie|api[-_ ]?key)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
    r"[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
)
_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_GITHUB_TOKEN_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class AuditableReportError(ValueError):
    """Raised when an auditable report cannot be built or validated."""


@dataclass(frozen=True, slots=True)
class AuditableReportConfig:
    """Versioned, bounded rendering configuration."""

    include_automation_details: bool = True
    max_text_length: int = 320
    top_blockers_limit: int = 5
    next_actions_limit: int = 8
    pr_summary_max_characters: int = 3500
    ticket_summary_max_characters: int = 8000

    def to_dict(self) -> dict[str, Any]:
        if type(self.include_automation_details) is not bool:
            raise AuditableReportError("include_automation_details must be a boolean.")
        _bounded_integer(self.max_text_length, "max_text_length", 80, 1024)
        _bounded_integer(self.top_blockers_limit, "top_blockers_limit", 1, 20)
        _bounded_integer(self.next_actions_limit, "next_actions_limit", 1, 32)
        _bounded_integer(
            self.pr_summary_max_characters,
            "pr_summary_max_characters",
            1000,
            65_536,
        )
        _bounded_integer(
            self.ticket_summary_max_characters,
            "ticket_summary_max_characters",
            1500,
            131_072,
        )
        return {
            "include_automation_details": self.include_automation_details,
            "max_text_length": self.max_text_length,
            "top_blockers_limit": self.top_blockers_limit,
            "next_actions_limit": self.next_actions_limit,
            "pr_summary_max_characters": self.pr_summary_max_characters,
            "ticket_summary_max_characters": self.ticket_summary_max_characters,
            "redaction_profile": REPORT_REDACTION_PROFILE,
        }


def _bounded_integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise AuditableReportError(f"{field} must be an integer from {minimum} to {maximum}.")
    return value


def _redact_text(value: object, maximum: int) -> str:
    rendered = _CONTROL_CHAR_RE.sub("", str(value if value is not None else ""))
    rendered = " ".join(rendered.split())
    rendered = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[redacted]", rendered)
    rendered = _BEARER_RE.sub("Bearer [redacted]", rendered)
    rendered = _JWT_RE.sub("[redacted-jwt]", rendered)
    rendered = _ACCESS_KEY_RE.sub("[redacted-access-key]", rendered)
    rendered = _GITHUB_TOKEN_RE.sub("[redacted-access-token]", rendered)
    if len(rendered) > maximum:
        marker = "…[truncated]"
        rendered = rendered[: maximum - len(marker)].rstrip() + marker
    return rendered


def _md(value: object) -> str:
    rendered = html.escape(str(value if value is not None else ""), quote=False)
    return rendered.replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`")


def _safe_https_url(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if any(character.isspace() or ord(character) < 32 for character in candidate):
        return None
    parsed = urlsplit(candidate)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    return candidate.replace("(", "%28").replace(")", "%29")


def _semantic_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(value))).hexdigest()


def _issue(item: Mapping[str, Any], maximum: int) -> dict[str, str]:
    return {
        "code": str(item["code"]),
        "control_id": str(item["control_id"]),
        "message": _redact_text(item["message"], maximum),
    }


def _control(item: Mapping[str, Any], maximum: int) -> dict[str, Any]:
    return {
        "control_id": str(item["control_id"]),
        "execution_id": str(item["execution_id"]),
        "status": str(item["status"]),
        "risk_points": int(item["risk_points"]),
        "summary": _redact_text(item["summary"], maximum),
        "source": _redact_text(item["source"], maximum),
        "evidence_ids": sorted(str(value) for value in item["evidence_ids"]),
    }


def _derive_actions(
    controls: Sequence[Mapping[str, Any]], risk_level: str, limit: int
) -> dict[str, Any]:
    action_templates = {
        "ERROR": ("RESOLVE_TECHNICAL_ERROR", "Resolve the control error and rerun the assessment."),
        "UNKNOWN": (
            "COLLECT_TRUSTED_EVIDENCE",
            "Collect fresh, digest-pinned evidence and rerun the assessment.",
        ),
        "FAIL": (
            "REMEDIATE_FAILED_CONTROL",
            "Remediate the failed control or follow the independently governed waiver process.",
        ),
    }
    actions: list[dict[str, str]] = []
    for status in ("ERROR", "UNKNOWN", "FAIL"):
        code, message = action_templates[status]
        for control in controls:
            if control["status"] == status:
                actions.append(
                    {
                        "code": code,
                        "control_id": str(control["control_id"]),
                        "action": message,
                    }
                )
    if risk_level == "CRITICAL":
        actions.insert(
            0,
            {
                "code": "KEEP_CHANGE_BLOCKED",
                "control_id": "assessment:risk",
                "action": "Keep the change blocked until technical risk is reduced and reassessed.",
            },
        )
    if not actions:
        actions.append(
            {
                "code": "REQUEST_AUTHORIZED_HUMAN_REVIEW",
                "control_id": "assessment:decision",
                "action": "Present the technical recommendation to the authorized human reviewer.",
            }
        )
    return {
        "total": len(actions),
        "items": actions[:limit],
        "omitted_count": max(0, len(actions) - limit),
    }


def build_auditable_report_v1(
    assessment: Mapping[str, Any],
    config: AuditableReportConfig | None = None,
) -> dict[str, Any]:
    """Build a strict, content-free report projection from Assessment Contract v1."""

    validate_assessment_v1(assessment)
    active_config = config or AuditableReportConfig()
    rendering = active_config.to_dict()
    maximum = active_config.max_text_length

    controls = sorted(
        (_control(item, maximum) for item in assessment["controls"]),
        key=lambda item: item["control_id"],
    )
    categories = {
        status: [item for item in controls if item["status"] == status]
        for status in _CONTROL_STATUSES
    }
    counts = {status: len(categories[status]) for status in _CONTROL_STATUSES}

    blockers = sorted(
        (_issue(item, maximum) for item in assessment["blockers"]),
        key=lambda item: (item["control_id"], item["code"]),
    )
    warnings = sorted(
        (_issue(item, maximum) for item in assessment["warnings"]),
        key=lambda item: (item["control_id"], item["code"]),
    )
    top_blockers = {
        "total": len(blockers),
        "items": blockers[: active_config.top_blockers_limit],
        "omitted_count": max(0, len(blockers) - active_config.top_blockers_limit),
    }

    provenance = []
    freshness_counts = {freshness: 0 for freshness in _FRESHNESS}
    for item in sorted(assessment["evidence"], key=lambda value: value["evidence_id"]):
        freshness = str(item["freshness"])
        freshness_counts[freshness] += 1
        provenance.append(
            {
                "evidence_id": str(item["evidence_id"]),
                "control_id": str(item["control_id"]),
                "kind": str(item["kind"]),
                "source": _redact_text(item["source"], maximum),
                "collected_at": str(item["collected_at"]),
                "valid_until": item["valid_until"],
                "freshness": freshness,
                "hash": dict(item["hash"]),
                "links": sorted(str(link) for link in item["links"]),
            }
        )

    context = assessment["context"]
    automation: dict[str, Any]
    if active_config.include_automation_details:
        automation = {
            "included": True,
            "repository": _redact_text(context["repository"], maximum),
            "pull_request": context["pull_request"],
            "commit": _redact_text(context["commit"], maximum),
            "run_id": str(context["run"]["id"]),
            "run_attempt": int(context["run"]["attempt"]),
            "pipeline_name": _redact_text(context["pipeline"]["name"], maximum),
            "pipeline_url": context["pipeline"]["url"],
        }
    else:
        automation = {"included": False}

    human_decision = dict(assessment["human_decision"])
    recommendation = {
        **assessment["recommendation"],
        "summary": _redact_text(assessment["recommendation"]["summary"], maximum),
    }
    audit = {
        "assessment_id": str(assessment["assessment_id"]),
        "assessment_schema_version": str(assessment["schema_version"]),
        "assessment_timestamp": str(assessment["timestamp"]),
        "change_id": str(assessment["change_id"]),
        "producer": dict(assessment["producer"]),
        "policy": dict(assessment["policy"]),
        "repository": _redact_text(context["repository"], maximum),
        "pull_request": context["pull_request"],
        "commit": _redact_text(context["commit"], maximum),
        "run": dict(context["run"]),
        "pipeline": dict(context["pipeline"]),
        "input_hashes": [
            {"name": item["name"], "hash": dict(item["hash"])}
            for item in sorted(assessment["inputs"], key=lambda value: value["name"])
        ],
        "assessment_integrity": dict(assessment["integrity"]),
        "canonical_assessment_sha256": hashlib.sha256(canonical_json(dict(assessment))).hexdigest(),
    }

    semantic: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "audit": audit,
        "decision": {
            "verdict": str(assessment["verdict"]),
            "technical_recommendation": recommendation,
            "human_decision": human_decision,
        },
        "scores": {
            "risk": dict(assessment["scores"]["risk"]),
            "confidence": dict(assessment["scores"]["confidence"]),
        },
        "controls": {
            "counts": counts,
            "top_blockers": top_blockers,
            "passed": categories["PASS"],
            "failed": categories["FAIL"],
            "unknown": categories["UNKNOWN"],
            "errors": categories["ERROR"],
            "warnings": warnings,
        },
        "evidence": {
            "freshness_counts": freshness_counts,
            "provenance": provenance,
        },
        "next_actions": _derive_actions(
            controls, str(assessment["scores"]["risk"]["level"]), active_config.next_actions_limit
        ),
        "automation_details": automation,
        "rendering": rendering,
        "data": {
            "classification": assessment["data"]["classification"],
            "content_embedded": False,
            "redaction_profile": REPORT_REDACTION_PROFILE,
        },
    }
    digest = _semantic_digest(semantic)
    report = {
        **semantic,
        "report_id": f"urn:preflightops:assessment-report:sha256:{digest}",
        "integrity": {
            "algorithm": "sha256",
            "value": digest,
            "canonicalization": REPORT_CANONICALIZATION_PROFILE,
        },
    }
    validate_auditable_report_v1(report)
    return report


def _expect_exact(value: object, expected: set[str], field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuditableReportError(f"{field} must be an object.")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unexpected {', '.join(extra)}")
        raise AuditableReportError(f"{field} has invalid fields: {'; '.join(details)}.")
    return value


def _expect_list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise AuditableReportError(f"{field} must be a list.")
    return value


def validate_auditable_report_v1(report: Mapping[str, Any]) -> None:
    """Strictly validate report identity and decision/status invariants."""

    top = _expect_exact(
        report,
        {
            "schema_version",
            "report_id",
            "audit",
            "decision",
            "scores",
            "controls",
            "evidence",
            "next_actions",
            "automation_details",
            "rendering",
            "data",
            "integrity",
        },
        "report",
    )
    if top["schema_version"] != REPORT_SCHEMA_VERSION:
        raise AuditableReportError("report.schema_version is unsupported.")

    decision = _expect_exact(
        top["decision"], {"verdict", "technical_recommendation", "human_decision"}, "decision"
    )
    recommendation = _expect_exact(
        decision["technical_recommendation"],
        {"action", "summary", "basis", "grants_approval"},
        "decision.technical_recommendation",
    )
    if (
        recommendation["grants_approval"] is not False
        or recommendation["basis"] != "technical_only"
    ):
        raise AuditableReportError("A technical recommendation cannot grant approval.")

    controls = _expect_exact(
        top["controls"],
        {"counts", "top_blockers", "passed", "failed", "unknown", "errors", "warnings"},
        "controls",
    )
    counts = _expect_exact(controls["counts"], set(_CONTROL_STATUSES), "controls.counts")
    category_names = {"PASS": "passed", "FAIL": "failed", "UNKNOWN": "unknown", "ERROR": "errors"}
    seen: list[str] = []
    for status, category in category_names.items():
        items = _expect_list(controls[category], f"controls.{category}")
        if counts[status] != len(items):
            raise AuditableReportError(f"controls.counts.{status} does not match its category.")
        for item in items:
            control = _expect_exact(
                item,
                {
                    "control_id",
                    "execution_id",
                    "status",
                    "risk_points",
                    "summary",
                    "source",
                    "evidence_ids",
                },
                f"controls.{category}",
            )
            if control["status"] != status:
                raise AuditableReportError(f"controls.{category} contains a mismatched status.")
            seen.append(str(control["control_id"]))
    if len(seen) != len(set(seen)):
        raise AuditableReportError("Control IDs must be unique across report categories.")
    if counts["ERROR"] or counts["UNKNOWN"]:
        if decision["verdict"] != "INDETERMINATE" or recommendation["action"] != "DO_NOT_PROCEED":
            raise AuditableReportError(
                "ERROR/UNKNOWN reports must remain indeterminate and fail closed."
            )

    top_blockers = _expect_exact(
        controls["top_blockers"], {"total", "items", "omitted_count"}, "controls.top_blockers"
    )
    blocker_items = _expect_list(top_blockers["items"], "controls.top_blockers.items")
    if top_blockers["total"] != len(blocker_items) + top_blockers["omitted_count"]:
        raise AuditableReportError("Top blocker counts are inconsistent.")
    _expect_list(controls["warnings"], "controls.warnings")

    evidence = _expect_exact(top["evidence"], {"freshness_counts", "provenance"}, "evidence")
    freshness_counts = _expect_exact(
        evidence["freshness_counts"], set(_FRESHNESS), "evidence.freshness_counts"
    )
    provenance = _expect_list(evidence["provenance"], "evidence.provenance")
    actual_freshness = {freshness: 0 for freshness in _FRESHNESS}
    for item in provenance:
        record = _expect_exact(
            item,
            {
                "evidence_id",
                "control_id",
                "kind",
                "source",
                "collected_at",
                "valid_until",
                "freshness",
                "hash",
                "links",
            },
            "evidence.provenance",
        )
        freshness = str(record["freshness"])
        if freshness not in actual_freshness:
            raise AuditableReportError("Evidence freshness is unsupported.")
        actual_freshness[freshness] += 1
    if dict(freshness_counts) != actual_freshness:
        raise AuditableReportError("Evidence freshness counts are inconsistent.")

    actions = _expect_exact(
        top["next_actions"], {"total", "items", "omitted_count"}, "next_actions"
    )
    action_items = _expect_list(actions["items"], "next_actions.items")
    if actions["total"] != len(action_items) + actions["omitted_count"]:
        raise AuditableReportError("Next action counts are inconsistent.")

    rendering = _expect_exact(
        top["rendering"],
        {
            "include_automation_details",
            "max_text_length",
            "top_blockers_limit",
            "next_actions_limit",
            "pr_summary_max_characters",
            "ticket_summary_max_characters",
            "redaction_profile",
        },
        "rendering",
    )
    if rendering["redaction_profile"] != REPORT_REDACTION_PROFILE:
        raise AuditableReportError("The report redaction profile is unsupported.")
    automation = top["automation_details"]
    if rendering["include_automation_details"]:
        _expect_exact(
            automation,
            {
                "included",
                "repository",
                "pull_request",
                "commit",
                "run_id",
                "run_attempt",
                "pipeline_name",
                "pipeline_url",
            },
            "automation_details",
        )
        if automation["included"] is not True:
            raise AuditableReportError("Automation details inclusion is inconsistent.")
    elif automation != {"included": False}:
        raise AuditableReportError("Omitted automation details must contain only included=false.")

    data = _expect_exact(
        top["data"], {"classification", "content_embedded", "redaction_profile"}, "data"
    )
    if (
        data["content_embedded"] is not False
        or data["redaction_profile"] != REPORT_REDACTION_PROFILE
    ):
        raise AuditableReportError("Report data-handling invariants are invalid.")

    _expect_exact(
        top["audit"],
        {
            "assessment_id",
            "assessment_schema_version",
            "assessment_timestamp",
            "change_id",
            "producer",
            "policy",
            "repository",
            "pull_request",
            "commit",
            "run",
            "pipeline",
            "input_hashes",
            "assessment_integrity",
            "canonical_assessment_sha256",
        },
        "audit",
    )
    _expect_exact(top["scores"], {"risk", "confidence"}, "scores")
    integrity = _expect_exact(
        top["integrity"], {"algorithm", "value", "canonicalization"}, "integrity"
    )
    if (
        integrity["algorithm"] != "sha256"
        or integrity["canonicalization"] != REPORT_CANONICALIZATION_PROFILE
    ):
        raise AuditableReportError("Report integrity profile is unsupported.")
    semantic = dict(top)
    semantic.pop("report_id")
    semantic.pop("integrity")
    digest = _semantic_digest(semantic)
    if integrity["value"] != digest:
        raise AuditableReportError("Report integrity does not match canonical content.")
    if top["report_id"] != f"urn:preflightops:assessment-report:sha256:{digest}":
        raise AuditableReportError("Report ID does not match canonical content.")


def serialize_auditable_report_v1(report: Mapping[str, Any]) -> bytes:
    """Return canonical UTF-8 JSON with exactly one trailing LF."""

    validate_auditable_report_v1(report)
    return canonical_json(dict(report)) + b"\n"


def _control_line(control: Mapping[str, Any]) -> str:
    return (
        f"- `{_md(control['control_id'])}` — **{_md(control['status'])}** — "
        f"{_md(control['summary'])} (source: {_md(control['source'])})"
    )


def _issue_line(issue: Mapping[str, Any]) -> str:
    return f"- `{_md(issue['code'])}` / `{_md(issue['control_id'])}` — {_md(issue['message'])}"


def render_assessment_markdown_v1(report: Mapping[str, Any]) -> str:
    """Render the complete reviewer-oriented Markdown report."""

    validate_auditable_report_v1(report)
    decision = report["decision"]
    recommendation = decision["technical_recommendation"]
    human = decision["human_decision"]
    risk = report["scores"]["risk"]
    confidence = report["scores"]["confidence"]
    controls = report["controls"]
    audit = report["audit"]
    evidence = report["evidence"]

    lines = [
        "# PreflightOps Assessment Review",
        "",
        "> Technical recommendation only. It does not grant human or CAB approval.",
        "",
        "## 30-second review",
        "",
        "| Item | Result |",
        "| --- | --- |",
        f"| Technical recommendation | **{_md(recommendation['action'])}** — {_md(recommendation['summary'])} |",
        f"| Verdict | **{_md(decision['verdict'])}** |",
        f"| Risk | **{_md(risk['level'])}** — {_md(risk['value'])}/100 |",
        f"| Confidence | **{_md(confidence['level'])}** — {_md(confidence['value'])}/100 |",
        f"| Human decision | **{_md(human['status'])}** — authority: {_md(human['authority'])} |",
        "",
        "## Top blockers",
        "",
    ]
    blocker_items = controls["top_blockers"]["items"]
    lines.extend(_issue_line(item) for item in blocker_items)
    if not blocker_items:
        lines.append("- None")
    if controls["top_blockers"]["omitted_count"]:
        lines.append(
            f"- {controls['top_blockers']['omitted_count']} additional blocker(s) are in the JSON report."
        )

    lines.extend(["", "## Unknown and errors", "", "### ERROR", ""])
    lines.extend(_control_line(item) for item in controls["errors"])
    if not controls["errors"]:
        lines.append("- None")
    lines.extend(["", "### UNKNOWN", ""])
    lines.extend(_control_line(item) for item in controls["unknown"])
    if not controls["unknown"]:
        lines.append("- None")

    lines.extend(["", "## Failed controls", ""])
    lines.extend(_control_line(item) for item in controls["failed"])
    if not controls["failed"]:
        lines.append("- None")
    lines.extend(["", "## Passed controls", ""])
    lines.extend(_control_line(item) for item in controls["passed"])
    if not controls["passed"]:
        lines.append("- None")

    freshness = evidence["freshness_counts"]
    lines.extend(
        [
            "",
            "## Evidence freshness",
            "",
            "| Fresh | Stale | Unknown |",
            "| ---: | ---: | ---: |",
            f"| {freshness['FRESH']} | {freshness['STALE']} | {freshness['UNKNOWN']} |",
            "",
            "## Provenance",
            "",
            "| Control | Source | Freshness | Collected | Valid until | Digest |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in evidence["provenance"]:
        lines.append(
            f"| `{_md(item['control_id'])}` | {_md(item['source'])} | {_md(item['freshness'])} "
            f"| {_md(item['collected_at'])} | {_md(item['valid_until'] or 'not declared')} "
            f"| `sha256:{_md(item['hash']['value'])}` |"
        )
    if not evidence["provenance"]:
        lines.append("| — | No digest-pinned evidence | UNKNOWN | — | — | — |")

    lines.extend(["", "## Next actions", ""])
    for index, item in enumerate(report["next_actions"]["items"], 1):
        lines.append(
            f"{index}. **{_md(item['code'])}** (`{_md(item['control_id'])}`): {_md(item['action'])}"
        )
    if report["next_actions"]["omitted_count"]:
        lines.append(
            f"{report['next_actions']['omitted_count']} additional action(s) are in the JSON report."
        )

    automation = report["automation_details"]
    if automation["included"]:
        lines.extend(
            [
                "",
                "## Automation Details",
                "",
                f"- Repository: `{_md(automation['repository'])}`",
                f"- Pull request: `{_md(automation['pull_request'] or 'not provided')}`",
                f"- Commit: `{_md(automation['commit'])}`",
                f"- Run: `{_md(automation['run_id'])}` (attempt {automation['run_attempt']})",
                f"- Pipeline: {_md(automation['pipeline_name'])}",
            ]
        )

    lines.extend(
        [
            "",
            "## Audit metadata",
            "",
            f"- Report ID: `{_md(report['report_id'])}`",
            f"- Assessment ID: `{_md(audit['assessment_id'])}`",
            f"- Assessment timestamp: `{_md(audit['assessment_timestamp'])}`",
            f"- Producer: `{_md(audit['producer']['name'])} {_md(audit['producer']['version'])}`",
            f"- Policy: `{_md(audit['policy']['name'])} {_md(audit['policy']['version'])}`",
            f"- Policy hash: `sha256:{_md(audit['policy']['hash']['value'])}`",
            f"- Commit: `{_md(audit['commit'])}`",
            f"- Assessment hash: `sha256:{_md(audit['canonical_assessment_sha256'])}`",
            f"- Report hash: `sha256:{_md(report['integrity']['value'])}`",
            "",
        ]
    )
    return "\n".join(lines)


def _bounded_markdown(lines: list[str], maximum: int) -> str:
    document = "\n".join(lines).rstrip() + "\n"
    if len(document) <= maximum:
        return document
    marker = "\n\n> Output truncated deterministically. Use the full JSON/Markdown artifact.\n"
    available = maximum - len(marker)
    if available <= 0:
        raise AuditableReportError("Markdown character budget is too small.")
    cut = document.rfind("\n", 0, available)
    if cut < 0:
        cut = available
    return document[:cut].rstrip() + marker


def render_pr_summary_v1(report: Mapping[str, Any], full_report_url: str | None = None) -> str:
    """Render a compact PR summary within the configured character budget."""

    validate_auditable_report_v1(report)
    decision = report["decision"]
    recommendation = decision["technical_recommendation"]
    risk = report["scores"]["risk"]
    confidence = report["scores"]["confidence"]
    controls = report["controls"]
    safe_link = _safe_https_url(full_report_url)
    lines = [
        "<!-- preflightops-assessment-report-v1 -->",
        "## PreflightOps assessment",
        "",
        "> Technical recommendation only; human/CAB approval is separate.",
        "",
        f"**{_md(recommendation['action'])}** · verdict `{_md(decision['verdict'])}` · "
        f"risk **{_md(risk['level'])} {risk['value']}/100** · confidence "
        f"**{_md(confidence['level'])} {confidence['value']}/100**",
        "",
        f"Human decision: **{_md(decision['human_decision']['status'])}**",
    ]
    if safe_link:
        lines.extend(["", f"[Open the full assessment report]({safe_link})"])
    lines.extend(["", "### Top blockers", ""])
    blockers = controls["top_blockers"]["items"]
    lines.extend(_issue_line(item) for item in blockers)
    if not blockers:
        lines.append("- None")
    lines.extend(
        [
            "",
            "### Control status",
            "",
            "| PASS | FAIL | UNKNOWN | ERROR |",
            "| ---: | ---: | ---: | ---: |",
            f"| {controls['counts']['PASS']} | {controls['counts']['FAIL']} "
            f"| {controls['counts']['UNKNOWN']} | {controls['counts']['ERROR']} |",
            "",
            "### Next actions",
            "",
        ]
    )
    for index, item in enumerate(report["next_actions"]["items"], 1):
        lines.append(f"{index}. {_md(item['action'])} (`{_md(item['control_id'])}`)")
    lines.extend(["", f"Assessment: `{_md(report['audit']['assessment_id'])}`"])
    return _bounded_markdown(lines, report["rendering"]["pr_summary_max_characters"])


def render_ticket_summary_v1(report: Mapping[str, Any], full_report_url: str | None = None) -> str:
    """Render a bounded copy/paste ticket summary without performing any write."""

    validate_auditable_report_v1(report)
    decision = report["decision"]
    recommendation = decision["technical_recommendation"]
    audit = report["audit"]
    controls = report["controls"]
    safe_link = _safe_https_url(full_report_url)
    lines = [
        "# PreflightOps change assessment summary",
        "",
        f"Change: `{_md(audit['change_id'])}`",
        f"Assessment: `{_md(audit['assessment_id'])}`",
        f"Timestamp: `{_md(audit['assessment_timestamp'])}`",
        "",
        "## Decision boundary",
        "",
        f"Technical recommendation: **{_md(recommendation['action'])}** — {_md(recommendation['summary'])}",
        f"Human decision: **{_md(decision['human_decision']['status'])}**",
        f"Authority: `{_md(decision['human_decision']['authority'])}`",
        "Automatic approval: **No**",
        "",
        "## Risk and confidence",
        "",
        f"- Risk: **{_md(report['scores']['risk']['level'])} {report['scores']['risk']['value']}/100**",
        f"- Confidence: **{_md(report['scores']['confidence']['level'])} {report['scores']['confidence']['value']}/100**",
        f"- Verdict: **{_md(decision['verdict'])}**",
        "",
        "## Blockers and indeterminate controls",
        "",
    ]
    issues = controls["top_blockers"]["items"]
    lines.extend(_issue_line(item) for item in issues)
    if not issues:
        lines.append("- None")
    for category in ("errors", "unknown", "failed"):
        lines.extend(_control_line(item) for item in controls[category])
    lines.extend(["", "## Passed controls", ""])
    lines.extend(f"- `{_md(item['control_id'])}`" for item in controls["passed"])
    if not controls["passed"]:
        lines.append("- None")
    lines.extend(["", "## Next actions", ""])
    for index, item in enumerate(report["next_actions"]["items"], 1):
        lines.append(f"{index}. {_md(item['action'])} (`{_md(item['control_id'])}`)")
    if safe_link:
        lines.extend(["", f"[Open the complete versioned report]({safe_link})"])
    lines.extend(
        [
            "",
            "## Audit reference",
            "",
            f"- Commit: `{_md(audit['commit'])}`",
            f"- Policy: `{_md(audit['policy']['name'])} {_md(audit['policy']['version'])}`",
            f"- Report ID: `{_md(report['report_id'])}`",
        ]
    )
    return _bounded_markdown(lines, report["rendering"]["ticket_summary_max_characters"])

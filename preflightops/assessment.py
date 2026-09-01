"""Deterministic Assessment Contract v1 and fail-closed Trust Kernel.

The kernel is deliberately pure and offline.  Callers provide timestamps,
digests, execution context, and control observations; the same values always
produce the same contract bytes, identifier, and integrity digest.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from ._version import __version__
from .evidence import canonical_json

ASSESSMENT_SCHEMA_VERSION = "1.0"
ASSESSMENT_ADAPTER_VERSION = "1.0"
CANONICALIZATION_PROFILE = "preflightops-canonical-json-v1"
HASH_PROFILE = "caller-supplied-sha256-v1"

ControlStatus = Literal["PASS", "FAIL", "ERROR", "UNKNOWN"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
ActorType = Literal["human", "service", "automation", "unknown"]

_CONTROL_STATUSES = {"PASS", "FAIL", "ERROR", "UNKNOWN"}
_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_ACTOR_TYPES = {"human", "service", "automation", "unknown"}
_VERDICTS = {"BLOCK", "INDETERMINATE", "READY_FOR_HUMAN_REVIEW", "REVIEW_REQUIRED"}
_RECOMMENDATIONS = {"BLOCK", "DO_NOT_PROCEED", "PROCEED", "PROCEED_WITH_CAUTION", "REVIEW"}
_FRESHNESS = {"FRESH", "STALE", "UNKNOWN"}
_CONFIDENCE_LEVELS = {"LOW", "MEDIUM", "HIGH"}
_WAIVER_STATUSES = {"VERIFIED", "EXPIRED", "REJECTED"}
_HUMAN_STATUSES = {"NOT_RECORDED", "RECORDED"}
_HUMAN_DECISIONS = {"APPROVE", "REJECT", "DEFER"}
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INLINE_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|authorization|cookie|api[-_ ]?key)"
    r"\s*[:=]\s*([^\s,;]+)"
)


class AssessmentContractError(ValueError):
    """Raised when an assessment cannot be built or strictly validated."""


def _clean_text(value: object, field: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AssessmentContractError(f"{field} must be a non-empty string.")
    clean = _INLINE_SECRET_RE.sub(lambda match: f"{match.group(1)}=[redacted]", value.strip())
    if len(clean) > maximum:
        clean = clean[:maximum]
    return clean


def _clean_optional_text(value: object, field: str, *, maximum: int = 512) -> str | None:
    if value is None or value == "":
        return None
    return _clean_text(value, field, maximum=maximum)


def _identifier(value: object, field: str) -> str:
    rendered = _clean_text(value, field, maximum=256)
    if not _IDENTIFIER_RE.fullmatch(rendered):
        raise AssessmentContractError(f"{field} contains unsupported identifier characters.")
    return rendered


def _slug_identifier(value: object, *, prefix: str) -> str:
    rendered = str(value or "unknown").strip()
    rendered = re.sub(r"[^A-Za-z0-9._:/-]+", "-", rendered).strip("-._:/") or "unknown"
    return _identifier(f"{prefix}{rendered}"[:256], "control_id")


def _normalize_sha256(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise AssessmentContractError(f"{field} must be a SHA-256 digest string.")
    digest = value.strip().lower()
    if digest.startswith("sha256:"):
        digest = digest[7:]
    if not _SHA256_RE.fullmatch(digest):
        raise AssessmentContractError(f"{field} must contain 64 hexadecimal characters.")
    return digest


def _parse_timestamp(value: dt.datetime | str, field: str) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AssessmentContractError(f"{field} must be an RFC 3339 timestamp.") from exc
    else:
        raise AssessmentContractError(f"{field} must be an RFC 3339 timestamp.")
    if parsed.tzinfo is None:
        raise AssessmentContractError(f"{field} must include a timezone.")
    return parsed.astimezone(dt.UTC)


def _timestamp(value: dt.datetime | str, field: str) -> str:
    return _parse_timestamp(value, field).isoformat().replace("+00:00", "Z")


def _safe_url(value: object, field: str) -> str:
    rendered = _clean_text(value, field, maximum=2048)
    parsed = urlsplit(rendered)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise AssessmentContractError(
            f"{field} must be an HTTPS URL without credentials, query, or fragment."
        )
    return rendered


def _safe_optional_url(value: object, field: str) -> str | None:
    if value is None or value == "":
        return None
    return _safe_url(value, field)


def _semantic_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(value))).hexdigest()


def _stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    return f"urn:preflightops:{prefix}:sha256:{_semantic_digest(value)}"


def _safe_projection_digest(value: Mapping[str, Any]) -> str:
    """Hash a narrow metadata projection without retaining arbitrary values."""

    projection: dict[str, Any] = {}
    for key in sorted(value):
        if key in {
            "digest",
            "effective_from",
            "expires_at",
            "name",
            "owner",
            "version",
            "verified_key_id",
        }:
            item = value[key]
            if item is None or isinstance(item, (bool, int, float, str)):
                projection[key] = item
    return _semantic_digest(projection)


@dataclass(frozen=True, slots=True)
class AssessmentContext:
    """Version-independent actor, source, and execution context."""

    actor_id: str
    actor_type: ActorType
    run_id: str
    run_attempt: int
    repository: str
    pull_request: str | None
    commit: str
    pipeline_name: str
    pipeline_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        actor_type = str(self.actor_type)
        if actor_type not in _ACTOR_TYPES:
            raise AssessmentContractError("context.actor.type is unsupported.")
        if type(self.run_attempt) is not int or self.run_attempt < 1:
            raise AssessmentContractError("context.run.attempt must be a positive integer.")
        return {
            "actor": {
                "id": _identifier(self.actor_id, "context.actor.id"),
                "type": actor_type,
            },
            "run": {
                "id": _identifier(self.run_id, "context.run.id"),
                "attempt": self.run_attempt,
            },
            "repository": _clean_text(self.repository, "context.repository", maximum=512),
            "pull_request": _clean_optional_text(
                self.pull_request, "context.pull_request", maximum=128
            ),
            "commit": _clean_text(self.commit, "context.commit", maximum=128),
            "pipeline": {
                "name": _clean_text(self.pipeline_name, "context.pipeline.name", maximum=256),
                "url": _safe_optional_url(self.pipeline_url, "context.pipeline.url"),
            },
        }


@dataclass(frozen=True, slots=True)
class PolicyIdentity:
    """Immutable policy identity pinned by name, version, and SHA-256."""

    name: str
    version: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": _clean_text(self.name, "policy.name", maximum=256),
            "version": _clean_text(self.version, "policy.version", maximum=128),
            "hash": {
                "algorithm": "sha256",
                "value": _normalize_sha256(self.sha256, "policy.hash.value"),
            },
        }


@dataclass(frozen=True, slots=True)
class InputDigest:
    """Caller-supplied digest; raw input content never enters this contract."""

    name: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": _identifier(self.name, "inputs.name"),
            "hash": {
                "algorithm": "sha256",
                "value": _normalize_sha256(self.sha256, "inputs.hash.value"),
                "profile": HASH_PROFILE,
            },
        }


@dataclass(frozen=True, slots=True)
class ControlObservation:
    """One executed control and its bounded, content-free evidence reference."""

    control_id: str
    status: ControlStatus
    summary: str
    source: str
    collected_at: dt.datetime | str
    valid_until: dt.datetime | str | None
    risk_points: int = 0
    evidence_sha256: str | None = None
    evidence_kind: str = "control-observation"
    links: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WaiverReference:
    """Minimal verified exception reference; never changes technical risk."""

    waiver_id: str
    sha256: str
    policy_sha256: str
    control_ids: tuple[str, ...]
    status: Literal["VERIFIED", "EXPIRED", "REJECTED"]
    valid_until: dt.datetime | str
    reason_code: str
    evidence_links: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        status = str(self.status)
        if status not in _WAIVER_STATUSES:
            raise AssessmentContractError("waivers.status is unsupported.")
        control_ids = sorted(
            {_identifier(item, "waivers.control_ids") for item in self.control_ids}
        )
        if not control_ids:
            raise AssessmentContractError("waivers.control_ids must not be empty.")
        return {
            "waiver_id": _identifier(self.waiver_id, "waivers.waiver_id"),
            "hash": {
                "algorithm": "sha256",
                "value": _normalize_sha256(self.sha256, "waivers.hash.value"),
            },
            "policy_hash": {
                "algorithm": "sha256",
                "value": _normalize_sha256(self.policy_sha256, "waivers.policy_hash.value"),
            },
            "control_ids": control_ids,
            "status": status,
            "valid_until": _timestamp(self.valid_until, "waivers.valid_until"),
            "reason_code": _identifier(self.reason_code, "waivers.reason_code"),
            "evidence_links": sorted(
                {_safe_url(item, "waivers.evidence_links") for item in self.evidence_links}
            ),
        }


@dataclass(frozen=True, slots=True)
class HumanDecision:
    """External human decision, represented independently from recommendation."""

    status: Literal["NOT_RECORDED", "RECORDED"] = "NOT_RECORDED"
    decision: Literal["APPROVE", "REJECT", "DEFER"] | None = None
    actor_id: str | None = None
    decided_at: dt.datetime | str | None = None
    rationale_code: str | None = None
    authority: str = "external_cab_or_change_management"

    def to_dict(self) -> dict[str, Any]:
        status = str(self.status)
        if status not in _HUMAN_STATUSES:
            raise AssessmentContractError("human_decision.status is unsupported.")
        if status == "NOT_RECORDED":
            if any(
                value is not None
                for value in (self.decision, self.actor_id, self.decided_at, self.rationale_code)
            ):
                raise AssessmentContractError(
                    "An unrecorded human decision cannot contain decision details."
                )
            decision = actor_id = decided_at = rationale_code = None
        else:
            if self.decision not in _HUMAN_DECISIONS:
                raise AssessmentContractError("A recorded human decision requires a decision.")
            decision = str(self.decision)
            actor_id = _identifier(self.actor_id, "human_decision.actor_id")
            if self.decided_at is None:
                raise AssessmentContractError(
                    "A recorded human decision requires human_decision.decided_at."
                )
            decided_at = _timestamp(self.decided_at, "human_decision.decided_at")
            rationale_code = _identifier(self.rationale_code, "human_decision.rationale_code")
        return {
            "status": status,
            "decision": decision,
            "actor_id": actor_id,
            "decided_at": decided_at,
            "rationale_code": rationale_code,
            "authority": _identifier(self.authority, "human_decision.authority"),
        }


def _freshness(
    collected_at: dt.datetime, valid_until: dt.datetime | None, evaluated_at: dt.datetime
) -> str:
    if collected_at > evaluated_at or valid_until is None:
        return "UNKNOWN"
    if valid_until < evaluated_at:
        return "STALE"
    return "FRESH"


def _issue(code: str, control_id: str, message: str) -> dict[str, str]:
    return {"code": code, "control_id": control_id, "message": message}


class TrustKernel:
    """Pure evaluator that creates one strictly validated Assessment Contract v1."""

    def evaluate(
        self,
        *,
        change_id: str,
        timestamp: dt.datetime | str,
        context: AssessmentContext,
        policy: PolicyIdentity,
        inputs: Sequence[InputDigest],
        controls: Sequence[ControlObservation],
        risk_score: int,
        risk_level: RiskLevel,
        recommendation_summary: str,
        waivers: Sequence[WaiverReference] = (),
        evidence_links: Sequence[str] = (),
        human_decision: HumanDecision | None = None,
        source_contract: str = "native-assessment-v1",
        confidence_cap: int = 100,
        data_classification: str = "internal",
    ) -> dict[str, Any]:
        """Evaluate controls without network, clock, filesystem, or random state."""

        evaluated_at = _parse_timestamp(timestamp, "timestamp")
        timestamp_text = _timestamp(evaluated_at, "timestamp")
        change = _identifier(change_id, "change_id")
        if type(risk_score) is not int or not 0 <= risk_score <= 100:
            raise AssessmentContractError("risk_score must be an integer from 0 to 100.")
        level = str(risk_level).upper()
        if level not in _RISK_LEVELS:
            raise AssessmentContractError("risk_level is unsupported.")
        if type(confidence_cap) is not int or not 0 <= confidence_cap <= 100:
            raise AssessmentContractError("confidence_cap must be an integer from 0 to 100.")
        if data_classification not in {"public", "internal", "confidential", "restricted"}:
            raise AssessmentContractError("data_classification is unsupported.")

        input_records = sorted((item.to_dict() for item in inputs), key=lambda item: item["name"])
        input_names = [item["name"] for item in input_records]
        if not input_records or len(input_names) != len(set(input_names)):
            raise AssessmentContractError("inputs must be non-empty and have unique names.")

        observation_ids = [item.control_id for item in controls]
        if not observation_ids or len(observation_ids) != len(set(observation_ids)):
            raise AssessmentContractError("controls must be non-empty and have unique control_ids.")

        control_records: list[dict[str, Any]] = []
        evidence_records: list[dict[str, Any]] = []
        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []
        passed_controls: list[str] = []
        confidence_components: list[int] = []

        for observation in sorted(controls, key=lambda item: item.control_id):
            control_id = _identifier(observation.control_id, "controls.control_id")
            requested_status = str(observation.status).upper()
            if requested_status not in _CONTROL_STATUSES:
                raise AssessmentContractError(f"Control {control_id} has an unsupported status.")
            if type(observation.risk_points) is not int or observation.risk_points < 0:
                raise AssessmentContractError(
                    f"Control {control_id} risk_points must be a non-negative integer."
                )
            collected = _parse_timestamp(
                observation.collected_at, f"controls.{control_id}.collected_at"
            )
            valid = (
                _parse_timestamp(observation.valid_until, f"controls.{control_id}.valid_until")
                if observation.valid_until is not None
                else None
            )
            if valid is not None and valid < collected:
                raise AssessmentContractError(
                    f"Control {control_id} valid_until cannot precede collected_at."
                )
            freshness = _freshness(collected, valid, evaluated_at)
            evidence_ids: list[str] = []
            evidence_digest: str | None = None
            if observation.evidence_sha256 is not None:
                evidence_digest = _normalize_sha256(
                    observation.evidence_sha256,
                    f"controls.{control_id}.evidence_sha256",
                )
                evidence_body = {
                    "control_id": control_id,
                    "kind": _identifier(observation.evidence_kind, "evidence.kind"),
                    "source": _clean_text(observation.source, "evidence.source", maximum=256),
                    "collected_at": _timestamp(collected, "evidence.collected_at"),
                    "valid_until": (
                        _timestamp(valid, "evidence.valid_until") if valid is not None else None
                    ),
                    "freshness": freshness,
                    "hash": {"algorithm": "sha256", "value": evidence_digest},
                    "links": sorted(
                        {_safe_url(item, "evidence.links") for item in observation.links}
                    ),
                }
                evidence_id = _stable_id("evidence", evidence_body)
                evidence_ids.append(evidence_id)
                evidence_records.append({"evidence_id": evidence_id, **evidence_body})

            final_status = requested_status
            if requested_status == "PASS" and (evidence_digest is None or freshness != "FRESH"):
                final_status = "UNKNOWN"
                warnings.append(
                    _issue(
                        "PASS_DOWNGRADED",
                        control_id,
                        "PASS requires fresh, digest-pinned evidence and was downgraded to UNKNOWN.",
                    )
                )
            if collected > evaluated_at:
                final_status = "ERROR"
                errors.append(
                    _issue(
                        "EVIDENCE_FROM_FUTURE",
                        control_id,
                        "Evidence collection time is later than the assessment timestamp.",
                    )
                )

            if final_status == "PASS":
                passed_controls.append(control_id)
            elif final_status == "FAIL":
                blockers.append(
                    _issue("CONTROL_FAILED", control_id, "The control reported a failure.")
                )
            elif final_status == "ERROR":
                issue = _issue(
                    "CONTROL_ERROR", control_id, "The control could not be evaluated reliably."
                )
                blockers.append(issue)
                if issue not in errors:
                    errors.append(issue)
            else:
                issue = _issue("CONTROL_UNKNOWN", control_id, "The control result is not known.")
                blockers.append(issue)
                warnings.append(issue)

            confidence_components.append(
                100
                if final_status in {"PASS", "FAIL"}
                and evidence_digest is not None
                and freshness == "FRESH"
                else 0
            )
            control_body = {
                "control_id": control_id,
                "status": final_status,
                "risk_points": observation.risk_points,
                "summary": _clean_text(
                    observation.summary, f"controls.{control_id}.summary", maximum=512
                ),
                "source": _clean_text(
                    observation.source, f"controls.{control_id}.source", maximum=256
                ),
                "evidence_ids": evidence_ids,
            }
            control_records.append(
                {"execution_id": _stable_id("control", control_body), **control_body}
            )

        confidence_value = min(
            confidence_cap,
            sum(confidence_components) // len(confidence_components),
        )
        confidence_level = (
            "HIGH" if confidence_value >= 80 else "MEDIUM" if confidence_value >= 50 else "LOW"
        )
        control_statuses = {item["status"] for item in control_records}
        if "ERROR" in control_statuses or "UNKNOWN" in control_statuses:
            verdict = "INDETERMINATE"
            action = "DO_NOT_PROCEED"
        elif level == "CRITICAL":
            verdict = "BLOCK"
            action = "BLOCK"
        elif "FAIL" in control_statuses or level == "HIGH":
            verdict = "REVIEW_REQUIRED"
            action = "REVIEW"
        else:
            verdict = "READY_FOR_HUMAN_REVIEW"
            action = "PROCEED_WITH_CAUTION" if level == "MEDIUM" else "PROCEED"

        waiver_records = sorted(
            (item.to_dict() for item in waivers), key=lambda item: item["waiver_id"]
        )
        safe_links = sorted({_safe_url(item, "evidence_links") for item in evidence_links})
        decision = (human_decision or HumanDecision()).to_dict()
        semantic: dict[str, Any] = {
            "schema_version": ASSESSMENT_SCHEMA_VERSION,
            "change_id": change,
            "timestamp": timestamp_text,
            "context": context.to_dict(),
            "producer": {"name": "PreflightOps", "version": __version__},
            "policy": policy.to_dict(),
            "inputs": input_records,
            "controls": control_records,
            "evidence": sorted(evidence_records, key=lambda item: item["evidence_id"]),
            "scores": {
                "risk": {"value": risk_score, "level": level},
                "confidence": {
                    "value": confidence_value,
                    "level": confidence_level,
                    "basis": "fresh-digest-pinned-control-observations-v1",
                },
            },
            "verdict": verdict,
            "blockers": sorted(blockers, key=lambda item: (item["control_id"], item["code"])),
            "warnings": sorted(warnings, key=lambda item: (item["control_id"], item["code"])),
            "passed_controls": sorted(passed_controls),
            "errors": sorted(errors, key=lambda item: (item["control_id"], item["code"])),
            "waivers": waiver_records,
            "evidence_links": safe_links,
            "recommendation": {
                "action": action,
                "summary": _clean_text(
                    recommendation_summary, "recommendation.summary", maximum=1024
                ),
                "basis": "technical_only",
                "grants_approval": False,
            },
            "human_decision": decision,
            "compatibility": {
                "source_contract": _identifier(source_contract, "compatibility.source_contract"),
                "adapter_version": ASSESSMENT_ADAPTER_VERSION,
                "legacy_output_preserved": source_contract != "native-assessment-v1",
            },
            "data": {
                "classification": data_classification,
                "content_embedded": False,
                "redaction_profile": "preflightops-assessment-metadata-v1",
                "input_hash_profile": HASH_PROFILE,
            },
        }
        digest = _semantic_digest(semantic)
        contract = {
            **semantic,
            "assessment_id": f"urn:preflightops:assessment:sha256:{digest}",
            "integrity": {
                "algorithm": "sha256",
                "value": digest,
                "canonicalization": CANONICALIZATION_PROFILE,
            },
        }
        validate_assessment_v1(contract)
        return contract


def _legacy_waivers(
    legacy_result: Mapping[str, Any], policy: PolicyIdentity
) -> tuple[WaiverReference, ...]:
    records: list[WaiverReference] = []
    raw = legacy_result.get("verified_waivers", [])
    if not isinstance(raw, list):
        raise AssessmentContractError("legacy verified_waivers must be a list.")
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise AssessmentContractError("legacy verified_waivers entries must be objects.")
        rules = item.get("rules")
        if not isinstance(rules, list) or not rules:
            raise AssessmentContractError("legacy waiver rules must be a non-empty list.")
        links = item.get("evidence_references", [])
        safe_links = tuple(
            value
            for value in links
            if isinstance(value, str) and value.startswith("https://") and "?" not in value
        )
        records.append(
            WaiverReference(
                waiver_id=str(item.get("id") or f"legacy-waiver-{index + 1}"),
                sha256=_normalize_sha256(item.get("digest"), "legacy waiver digest"),
                policy_sha256=policy.sha256,
                control_ids=tuple(_slug_identifier(rule, prefix="legacy:rule:") for rule in rules),
                status="VERIFIED",
                valid_until=str(item.get("expires_at") or ""),
                reason_code=str(item.get("reason_code") or "verified-exception"),
                evidence_links=safe_links,
            )
        )
    return tuple(records)


def adapt_legacy_assessment(
    legacy_result: Mapping[str, Any],
    *,
    change_id: str,
    timestamp: dt.datetime | str,
    context: AssessmentContext,
    input_digests: Mapping[str, str],
    valid_for: dt.timedelta = dt.timedelta(hours=24),
    policy: PolicyIdentity | None = None,
    evidence_links: Sequence[str] = (),
    human_decision: HumanDecision | None = None,
) -> dict[str, Any]:
    """Adapt risk-report-v1 without mutating or removing the legacy output."""

    if not isinstance(legacy_result, Mapping):
        raise AssessmentContractError("legacy_result must be an object.")
    if valid_for <= dt.timedelta(0):
        raise AssessmentContractError("valid_for must be greater than zero.")
    evaluated_at = _parse_timestamp(timestamp, "timestamp")
    valid_until = evaluated_at + valid_for
    policy_data = legacy_result.get("policy_pack", {})
    if not isinstance(policy_data, Mapping):
        raise AssessmentContractError("legacy policy_pack must be an object.")
    active_policy = policy
    if active_policy is None:
        raw_digest = policy_data.get("digest")
        digest = (
            _normalize_sha256(raw_digest, "legacy policy digest")
            if isinstance(raw_digest, str) and raw_digest.strip()
            else _safe_projection_digest(policy_data)
        )
        active_policy = PolicyIdentity(
            name=str(policy_data.get("name") or "legacy-default"),
            version=str(policy_data.get("version") or "legacy-unknown"),
            sha256=digest,
        )

    inputs = tuple(InputDigest(name=name, sha256=digest) for name, digest in input_digests.items())
    observations: list[ControlObservation] = []
    triggered = legacy_result.get("triggered_rules", [])
    if not isinstance(triggered, list):
        raise AssessmentContractError("legacy triggered_rules must be a list.")
    for index, rule in enumerate(triggered):
        if not isinstance(rule, Mapping):
            raise AssessmentContractError("legacy triggered_rules entries must be objects.")
        rule_name = rule.get("id") or f"finding-{index + 1}"
        evidence_projection = {
            "id": str(rule_name),
            "score": rule.get("score"),
            "severity": rule.get("severity"),
            "source": rule.get("source"),
            "waiver_ids": sorted(rule.get("waiver_ids", []))
            if isinstance(rule.get("waiver_ids"), list)
            else [],
        }
        observations.append(
            ControlObservation(
                control_id=_slug_identifier(rule_name, prefix="legacy:rule:"),
                status="FAIL",
                summary=str(rule.get("description") or "Legacy risk rule reported a finding."),
                source=str(rule.get("source") or "legacy-risk-engine"),
                collected_at=evaluated_at,
                valid_until=valid_until,
                risk_points=int(rule.get("score") or 0),
                evidence_sha256=_semantic_digest(evidence_projection),
                evidence_kind="legacy-risk-finding",
            )
        )

    missing = legacy_result.get("missing_controls", [])
    if not isinstance(missing, list):
        raise AssessmentContractError("legacy missing_controls must be a list.")
    for item in sorted({str(value) for value in missing}):
        observations.append(
            ControlObservation(
                control_id=_slug_identifier(item, prefix="legacy:missing:"),
                status="FAIL",
                summary="A required operational control is missing.",
                source="legacy-risk-engine",
                collected_at=evaluated_at,
                valid_until=valid_until,
                evidence_sha256=_semantic_digest({"missing_control": item}),
                evidence_kind="legacy-missing-control",
            )
        )

    monitoring = legacy_result.get("monitor_validation")
    if isinstance(monitoring, Mapping):
        monitor_status = str(monitoring.get("status") or "unknown").upper()
        status: ControlStatus = (
            "PASS"
            if monitor_status == "PASS"
            else "FAIL"
            if monitor_status == "FAIL"
            else "UNKNOWN"
        )
        monitor_projection = {
            key: monitoring.get(key)
            for key in (
                "dashboard_count",
                "enabled_monitor_count",
                "inventory_monitor_count",
                "providers",
                "referenced_monitor_ids",
                "status",
                "valid_dashboard_count",
            )
        }
        observations.append(
            ControlObservation(
                control_id="legacy:monitoring-evidence",
                status=status,
                summary="Legacy monitoring evidence validation result.",
                source="legacy-monitor-validation",
                collected_at=evaluated_at,
                valid_until=valid_until,
                evidence_sha256=_semantic_digest(monitor_projection),
                evidence_kind="legacy-monitor-validation",
            )
        )

    legacy_errors = legacy_result.get("errors", [])
    if legacy_errors is not None and not isinstance(legacy_errors, list):
        raise AssessmentContractError("legacy errors must be a list when present.")
    for index, error in enumerate(legacy_errors or []):
        observations.append(
            ControlObservation(
                control_id=f"legacy:error:{index + 1}",
                status="ERROR",
                summary=str(error or "Legacy assessment error."),
                source="legacy-risk-engine",
                collected_at=evaluated_at,
                valid_until=valid_until,
                evidence_sha256=_semantic_digest({"error_index": index + 1}),
                evidence_kind="legacy-assessment-error",
            )
        )

    if not observations:
        observations.append(
            ControlObservation(
                control_id="legacy:coverage",
                status="UNKNOWN",
                summary="Legacy output did not enumerate executed controls.",
                source="legacy-adapter",
                collected_at=evaluated_at,
                valid_until=valid_until,
                evidence_sha256=None,
                evidence_kind="legacy-coverage",
            )
        )

    risk_score = legacy_result.get("risk_score")
    if type(risk_score) is not int:
        raise AssessmentContractError("legacy risk_score must be an integer.")
    risk_level = str(legacy_result.get("risk_level") or "").upper()
    recommendation = str(
        legacy_result.get("recommendation") or "Human review is required before a decision."
    )
    return TrustKernel().evaluate(
        change_id=change_id,
        timestamp=evaluated_at,
        context=context,
        policy=active_policy,
        inputs=inputs,
        controls=tuple(observations),
        risk_score=risk_score,
        risk_level=risk_level,  # type: ignore[arg-type]
        recommendation_summary=recommendation,
        waivers=_legacy_waivers(legacy_result, active_policy),
        evidence_links=evidence_links,
        human_decision=human_decision,
        source_contract="risk-report-v1",
        confidence_cap=80,
    )


def _expect_exact_keys(value: object, expected: set[str], field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AssessmentContractError(f"{field} must be an object.")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = []
        if missing:
            detail.append(f"missing {', '.join(missing)}")
        if extra:
            detail.append(f"unexpected {', '.join(extra)}")
        raise AssessmentContractError(f"{field} has invalid fields: {'; '.join(detail)}.")
    return value


def _expect_list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise AssessmentContractError(f"{field} must be a list.")
    return value


def validate_assessment_v1(contract: Mapping[str, Any]) -> None:
    """Strictly validate shape, identity, integrity, and fail-closed invariants."""

    top = _expect_exact_keys(
        contract,
        {
            "assessment_id",
            "blockers",
            "change_id",
            "compatibility",
            "context",
            "controls",
            "data",
            "errors",
            "evidence",
            "evidence_links",
            "human_decision",
            "inputs",
            "integrity",
            "passed_controls",
            "policy",
            "producer",
            "recommendation",
            "schema_version",
            "scores",
            "timestamp",
            "verdict",
            "waivers",
            "warnings",
        },
        "assessment",
    )
    if top["schema_version"] != ASSESSMENT_SCHEMA_VERSION:
        raise AssessmentContractError("assessment.schema_version is unsupported.")
    _identifier(top["change_id"], "assessment.change_id")
    _timestamp(top["timestamp"], "assessment.timestamp")

    context = _expect_exact_keys(
        top["context"],
        {"actor", "commit", "pipeline", "pull_request", "repository", "run"},
        "assessment.context",
    )
    actor = _expect_exact_keys(context["actor"], {"id", "type"}, "assessment.context.actor")
    _identifier(actor["id"], "assessment.context.actor.id")
    if actor["type"] not in _ACTOR_TYPES:
        raise AssessmentContractError("assessment.context.actor.type is unsupported.")
    run = _expect_exact_keys(context["run"], {"attempt", "id"}, "assessment.context.run")
    _identifier(run["id"], "assessment.context.run.id")
    if type(run["attempt"]) is not int or run["attempt"] < 1:
        raise AssessmentContractError("assessment.context.run.attempt is invalid.")
    _clean_text(context["repository"], "assessment.context.repository", maximum=512)
    _clean_optional_text(context["pull_request"], "assessment.context.pull_request", maximum=128)
    _clean_text(context["commit"], "assessment.context.commit", maximum=128)
    pipeline = _expect_exact_keys(
        context["pipeline"], {"name", "url"}, "assessment.context.pipeline"
    )
    _clean_text(pipeline["name"], "assessment.context.pipeline.name", maximum=256)
    _safe_optional_url(pipeline["url"], "assessment.context.pipeline.url")

    producer = _expect_exact_keys(top["producer"], {"name", "version"}, "assessment.producer")
    if producer["name"] != "PreflightOps":
        raise AssessmentContractError("assessment.producer.name is unsupported.")
    _clean_text(producer["version"], "assessment.producer.version", maximum=128)

    policy = _expect_exact_keys(top["policy"], {"hash", "name", "version"}, "assessment.policy")
    _clean_text(policy["name"], "assessment.policy.name", maximum=256)
    _clean_text(policy["version"], "assessment.policy.version", maximum=128)
    policy_hash = _expect_exact_keys(
        policy["hash"], {"algorithm", "value"}, "assessment.policy.hash"
    )
    if policy_hash["algorithm"] != "sha256":
        raise AssessmentContractError("assessment.policy.hash.algorithm is unsupported.")
    _normalize_sha256(policy_hash["value"], "assessment.policy.hash.value")

    input_names: list[str] = []
    for index, item in enumerate(_expect_list(top["inputs"], "assessment.inputs")):
        record = _expect_exact_keys(item, {"hash", "name"}, f"assessment.inputs[{index}]")
        input_names.append(_identifier(record["name"], f"assessment.inputs[{index}].name"))
        digest = _expect_exact_keys(
            record["hash"],
            {"algorithm", "profile", "value"},
            f"assessment.inputs[{index}].hash",
        )
        if digest["algorithm"] != "sha256" or digest["profile"] != HASH_PROFILE:
            raise AssessmentContractError(f"assessment.inputs[{index}].hash is unsupported.")
        _normalize_sha256(digest["value"], f"assessment.inputs[{index}].hash.value")
    if not input_names or input_names != sorted(set(input_names)):
        raise AssessmentContractError("assessment.inputs must be sorted, unique, and non-empty.")

    control_status: dict[str, str] = {}
    execution_ids: set[str] = set()
    for index, item in enumerate(_expect_list(top["controls"], "assessment.controls")):
        record = _expect_exact_keys(
            item,
            {
                "control_id",
                "evidence_ids",
                "execution_id",
                "risk_points",
                "source",
                "status",
                "summary",
            },
            f"assessment.controls[{index}]",
        )
        control_id = _identifier(record["control_id"], f"assessment.controls[{index}].control_id")
        if control_id in control_status:
            raise AssessmentContractError("assessment.controls contains duplicate control_ids.")
        status = str(record["status"])
        if status not in _CONTROL_STATUSES:
            raise AssessmentContractError(f"assessment.controls[{index}].status is unsupported.")
        control_status[control_id] = status
        execution_id = _clean_text(
            record["execution_id"], f"assessment.controls[{index}].execution_id", maximum=256
        )
        if execution_id in execution_ids:
            raise AssessmentContractError("assessment.controls contains duplicate execution_ids.")
        execution_ids.add(execution_id)
        if type(record["risk_points"]) is not int or record["risk_points"] < 0:
            raise AssessmentContractError(f"assessment.controls[{index}].risk_points is invalid.")
        _clean_text(record["summary"], f"assessment.controls[{index}].summary", maximum=512)
        _clean_text(record["source"], f"assessment.controls[{index}].source", maximum=256)
        evidence_ids = _expect_list(
            record["evidence_ids"], f"assessment.controls[{index}].evidence_ids"
        )
        if evidence_ids != sorted(set(evidence_ids)):
            raise AssessmentContractError(
                f"assessment.controls[{index}].evidence_ids must be sorted and unique."
            )

    if not control_status or list(control_status) != sorted(control_status):
        raise AssessmentContractError("assessment.controls must be sorted and non-empty.")

    known_evidence_ids: set[str] = set()
    for index, item in enumerate(_expect_list(top["evidence"], "assessment.evidence")):
        record = _expect_exact_keys(
            item,
            {
                "collected_at",
                "control_id",
                "evidence_id",
                "freshness",
                "hash",
                "kind",
                "links",
                "source",
                "valid_until",
            },
            f"assessment.evidence[{index}]",
        )
        evidence_id = _clean_text(
            record["evidence_id"], f"assessment.evidence[{index}].evidence_id", maximum=256
        )
        if evidence_id in known_evidence_ids:
            raise AssessmentContractError("assessment.evidence contains duplicate evidence_ids.")
        known_evidence_ids.add(evidence_id)
        if record["control_id"] not in control_status:
            raise AssessmentContractError("assessment.evidence references an unknown control_id.")
        _identifier(record["kind"], f"assessment.evidence[{index}].kind")
        _clean_text(record["source"], f"assessment.evidence[{index}].source", maximum=256)
        collected = _parse_timestamp(
            record["collected_at"], f"assessment.evidence[{index}].collected_at"
        )
        valid_until = record["valid_until"]
        valid = (
            _parse_timestamp(valid_until, f"assessment.evidence[{index}].valid_until")
            if valid_until is not None
            else None
        )
        if valid is not None and valid < collected:
            raise AssessmentContractError("assessment.evidence validity interval is invalid.")
        if record["freshness"] not in _FRESHNESS:
            raise AssessmentContractError(f"assessment.evidence[{index}].freshness is unsupported.")
        digest = _expect_exact_keys(
            record["hash"], {"algorithm", "value"}, f"assessment.evidence[{index}].hash"
        )
        if digest["algorithm"] != "sha256":
            raise AssessmentContractError("assessment.evidence hash algorithm is unsupported.")
        _normalize_sha256(digest["value"], f"assessment.evidence[{index}].hash.value")
        links = _expect_list(record["links"], f"assessment.evidence[{index}].links")
        normalized_links = sorted({_safe_url(link, "assessment.evidence.links") for link in links})
        if links != normalized_links:
            raise AssessmentContractError("assessment.evidence links must be sorted and unique.")

    for item in top["controls"]:
        if not set(item["evidence_ids"]).issubset(known_evidence_ids):
            raise AssessmentContractError("assessment.controls references unknown evidence_ids.")

    scores = _expect_exact_keys(top["scores"], {"confidence", "risk"}, "assessment.scores")
    risk = _expect_exact_keys(scores["risk"], {"level", "value"}, "assessment.scores.risk")
    if type(risk["value"]) is not int or not 0 <= risk["value"] <= 100:
        raise AssessmentContractError("assessment.scores.risk.value is invalid.")
    if risk["level"] not in _RISK_LEVELS:
        raise AssessmentContractError("assessment.scores.risk.level is unsupported.")
    confidence = _expect_exact_keys(
        scores["confidence"], {"basis", "level", "value"}, "assessment.scores.confidence"
    )
    if type(confidence["value"]) is not int or not 0 <= confidence["value"] <= 100:
        raise AssessmentContractError("assessment.scores.confidence.value is invalid.")
    if confidence["level"] not in _CONFIDENCE_LEVELS:
        raise AssessmentContractError("assessment.scores.confidence.level is unsupported.")
    _identifier(confidence["basis"], "assessment.scores.confidence.basis")
    if top["verdict"] not in _VERDICTS:
        raise AssessmentContractError("assessment.verdict is unsupported.")

    issue_controls: set[str] = set()
    for collection in ("blockers", "warnings", "errors"):
        values = _expect_list(top[collection], f"assessment.{collection}")
        if values != sorted(values, key=lambda item: (item["control_id"], item["code"])):
            raise AssessmentContractError(f"assessment.{collection} must be sorted.")
        for index, item in enumerate(values):
            record = _expect_exact_keys(
                item, {"code", "control_id", "message"}, f"assessment.{collection}[{index}]"
            )
            _identifier(record["code"], f"assessment.{collection}[{index}].code")
            control_id = _identifier(
                record["control_id"], f"assessment.{collection}[{index}].control_id"
            )
            if control_id not in control_status:
                raise AssessmentContractError(
                    f"assessment.{collection} references an unknown control."
                )
            issue_controls.add(control_id)
            _clean_text(record["message"], f"assessment.{collection}[{index}].message")

    passed = _expect_list(top["passed_controls"], "assessment.passed_controls")
    if passed != sorted(set(passed)):
        raise AssessmentContractError("assessment.passed_controls must be sorted and unique.")
    expected_passed = sorted(
        control_id for control_id, status in control_status.items() if status == "PASS"
    )
    if passed != expected_passed:
        raise AssessmentContractError("assessment.passed_controls does not match PASS controls.")
    if any(control_status[control_id] in {"ERROR", "UNKNOWN"} for control_id in passed):
        raise AssessmentContractError("ERROR or UNKNOWN controls cannot appear as passed.")
    if any(
        status in {"ERROR", "UNKNOWN"} and control_id not in issue_controls
        for control_id, status in control_status.items()
    ):
        raise AssessmentContractError("ERROR and UNKNOWN controls require explicit issues.")

    for index, item in enumerate(_expect_list(top["waivers"], "assessment.waivers")):
        record = _expect_exact_keys(
            item,
            {
                "control_ids",
                "evidence_links",
                "hash",
                "policy_hash",
                "reason_code",
                "status",
                "valid_until",
                "waiver_id",
            },
            f"assessment.waivers[{index}]",
        )
        _identifier(record["waiver_id"], f"assessment.waivers[{index}].waiver_id")
        if record["status"] not in _WAIVER_STATUSES:
            raise AssessmentContractError(f"assessment.waivers[{index}].status is unsupported.")
        _timestamp(record["valid_until"], f"assessment.waivers[{index}].valid_until")
        _identifier(record["reason_code"], f"assessment.waivers[{index}].reason_code")
        for hash_field in ("hash", "policy_hash"):
            digest = _expect_exact_keys(
                record[hash_field],
                {"algorithm", "value"},
                f"assessment.waivers[{index}].{hash_field}",
            )
            if digest["algorithm"] != "sha256":
                raise AssessmentContractError("assessment waiver hash algorithm is unsupported.")
            _normalize_sha256(digest["value"], f"assessment.waivers[{index}].{hash_field}.value")
        waiver_controls = _expect_list(
            record["control_ids"], f"assessment.waivers[{index}].control_ids"
        )
        if not waiver_controls or waiver_controls != sorted(set(waiver_controls)):
            raise AssessmentContractError(
                "assessment waiver control_ids must be sorted and unique."
            )
        for control_id in waiver_controls:
            _identifier(control_id, f"assessment.waivers[{index}].control_ids")
        waiver_links = _expect_list(
            record["evidence_links"], f"assessment.waivers[{index}].evidence_links"
        )
        if waiver_links != sorted(set(waiver_links)):
            raise AssessmentContractError(
                "assessment waiver evidence_links must be sorted and unique."
            )
        for link in waiver_links:
            _safe_url(link, f"assessment.waivers[{index}].evidence_links")

    links = _expect_list(top["evidence_links"], "assessment.evidence_links")
    if links != sorted(set(links)):
        raise AssessmentContractError("assessment.evidence_links must be sorted and unique.")
    for link in links:
        _safe_url(link, "assessment.evidence_links")

    recommendation = _expect_exact_keys(
        top["recommendation"],
        {"action", "basis", "grants_approval", "summary"},
        "assessment.recommendation",
    )
    if recommendation["action"] not in _RECOMMENDATIONS:
        raise AssessmentContractError("assessment.recommendation.action is unsupported.")
    if (
        recommendation["basis"] != "technical_only"
        or recommendation["grants_approval"] is not False
    ):
        raise AssessmentContractError("assessment.recommendation cannot grant approval.")
    _clean_text(recommendation["summary"], "assessment.recommendation.summary", maximum=1024)

    decision = _expect_exact_keys(
        top["human_decision"],
        {"actor_id", "authority", "decided_at", "decision", "rationale_code", "status"},
        "assessment.human_decision",
    )
    if decision["status"] not in _HUMAN_STATUSES:
        raise AssessmentContractError("assessment.human_decision.status is unsupported.")
    _identifier(decision["authority"], "assessment.human_decision.authority")
    if decision["status"] == "NOT_RECORDED":
        if any(
            decision[field] is not None
            for field in ("actor_id", "decided_at", "decision", "rationale_code")
        ):
            raise AssessmentContractError("Unrecorded human decisions cannot contain details.")
    else:
        if decision["decision"] not in _HUMAN_DECISIONS:
            raise AssessmentContractError("Recorded human decision is invalid.")
        _identifier(decision["actor_id"], "assessment.human_decision.actor_id")
        _timestamp(decision["decided_at"], "assessment.human_decision.decided_at")
        _identifier(decision["rationale_code"], "assessment.human_decision.rationale_code")

    compatibility = _expect_exact_keys(
        top["compatibility"],
        {"adapter_version", "legacy_output_preserved", "source_contract"},
        "assessment.compatibility",
    )
    _identifier(compatibility["source_contract"], "assessment.compatibility.source_contract")
    if compatibility["adapter_version"] != ASSESSMENT_ADAPTER_VERSION:
        raise AssessmentContractError("assessment.compatibility.adapter_version is unsupported.")
    if type(compatibility["legacy_output_preserved"]) is not bool:
        raise AssessmentContractError(
            "assessment.compatibility.legacy_output_preserved is invalid."
        )

    data = _expect_exact_keys(
        top["data"],
        {"classification", "content_embedded", "input_hash_profile", "redaction_profile"},
        "assessment.data",
    )
    if data["classification"] not in {"public", "internal", "confidential", "restricted"}:
        raise AssessmentContractError("assessment.data.classification is unsupported.")
    if data["content_embedded"] is not False or data["input_hash_profile"] != HASH_PROFILE:
        raise AssessmentContractError("assessment.data handling invariants are invalid.")
    if data["redaction_profile"] != "preflightops-assessment-metadata-v1":
        raise AssessmentContractError("assessment.data.redaction_profile is unsupported.")

    integrity = _expect_exact_keys(
        top["integrity"], {"algorithm", "canonicalization", "value"}, "assessment.integrity"
    )
    if (
        integrity["algorithm"] != "sha256"
        or integrity["canonicalization"] != CANONICALIZATION_PROFILE
    ):
        raise AssessmentContractError("assessment.integrity profile is unsupported.")
    claimed_digest = _normalize_sha256(integrity["value"], "assessment.integrity.value")
    semantic = dict(top)
    semantic.pop("assessment_id")
    semantic.pop("integrity")
    actual_digest = _semantic_digest(semantic)
    if claimed_digest != actual_digest:
        raise AssessmentContractError("assessment.integrity does not match canonical content.")
    if top["assessment_id"] != f"urn:preflightops:assessment:sha256:{actual_digest}":
        raise AssessmentContractError("assessment.assessment_id does not match canonical content.")


def serialize_assessment_v1(contract: Mapping[str, Any]) -> bytes:
    """Return stable canonical UTF-8 JSON with one trailing newline."""

    validate_assessment_v1(contract)
    return canonical_json(dict(contract)) + b"\n"

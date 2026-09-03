"""Deterministic semantic validation, confidence, and freshness contract v1.

The evaluator is deliberately pure and offline. Callers provide plans, evidence
metadata, a policy, and the evaluation timestamp. Plan content is inspected but
never copied to the result; only bounded metadata and fixed issue messages leave
the trust boundary.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from .evidence import canonical_json

SEMANTIC_VALIDATION_SCHEMA_VERSION = "1.0"
SEMANTIC_VALIDATION_ADAPTER_VERSION = "1.0"
SEMANTIC_VALIDATION_CANONICALIZATION = "preflightops-canonical-json-v1"
SEMANTIC_CONFIDENCE_BASIS = "determinability-freshness-provenance-v1"

SemanticStatus = Literal["PASS", "FAIL", "UNKNOWN", "ERROR", "NOT_APPLICABLE"]
FreshnessStatus = Literal["FRESH", "STALE", "UNKNOWN"]
ProviderStatus = Literal["AVAILABLE", "ABSENT", "ERROR"]
ParserStatus = Literal["OK", "ERROR"]

_CONTROL_IDS = ("monitoring-plan", "rollback-plan", "validation-plan")
_PLAN_KEYS = {
    "monitoring-plan": "monitoring_plan",
    "rollback-plan": "rollback_plan",
    "validation-plan": "validation_plan",
}
_STATUSES = {"PASS", "FAIL", "UNKNOWN", "ERROR", "NOT_APPLICABLE"}
_FRESHNESS = {"FRESH", "STALE", "UNKNOWN"}
_PROVIDER_STATUSES = {"AVAILABLE", "ABSENT", "ERROR"}
_PARSER_STATUSES = {"OK", "ERROR"}
_REFERENCE_STATES = {"ACTIVE", "BROKEN", "UNKNOWN"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_PLACEHOLDER_VALUES = {
    "asdf",
    "fix later",
    "foo",
    "lorem ipsum",
    "n/a",
    "na",
    "none",
    "qwerty",
    "tbd",
    "todo",
    "unknown",
    "xxx",
}
_COMMON_PLAN_FIELDS = {
    "applicable",
    "contradictions",
    "duration_minutes",
    "not_applicable_reason",
    "owner",
    "steps",
    "success_criteria",
}
_PLAN_FIELDS = {
    "rollback-plan": _COMMON_PLAN_FIELDS | {"action", "trigger"},
    "monitoring-plan": _COMMON_PLAN_FIELDS | {"alerts", "dashboards"},
    "validation-plan": _COMMON_PLAN_FIELDS,
}


class SemanticValidationError(ValueError):
    """Raised when the API boundary or a generated contract is invalid."""


@dataclass(frozen=True, slots=True)
class SemanticValidationPolicy:
    """Versioned confidence and maximum-age policy."""

    name: str = "preflightops-semantic-validation"
    version: str = "1.0"
    max_age_seconds: int = 3600

    def to_dict(self) -> dict[str, Any]:
        if type(self.max_age_seconds) is not int or self.max_age_seconds < 1:
            raise SemanticValidationError("policy.max_age_seconds must be positive.")
        return {
            "name": _identifier(self.name, "policy.name"),
            "version": _identifier(self.version, "policy.version"),
            "max_age_seconds": self.max_age_seconds,
            "confidence_basis": SEMANTIC_CONFIDENCE_BASIS,
        }


@dataclass(frozen=True, slots=True)
class SemanticEvidenceReference:
    """Content-free provenance and validity metadata for one plan."""

    source: str
    provider_status: ProviderStatus = "AVAILABLE"
    parser_status: ParserStatus = "OK"
    collected_at: dt.datetime | str | None = None
    valid_until: dt.datetime | str | None = None
    sha256: str | None = None


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise SemanticValidationError(f"{field} must be an identifier.")
    rendered = value.strip()
    if not _IDENTIFIER_RE.fullmatch(rendered):
        raise SemanticValidationError(f"{field} contains unsupported characters.")
    return rendered


def _parse_timestamp(value: dt.datetime | str, field: str) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SemanticValidationError(f"{field} must be an RFC 3339 timestamp.") from exc
    else:
        raise SemanticValidationError(f"{field} must be an RFC 3339 timestamp.")
    if parsed.tzinfo is None:
        raise SemanticValidationError(f"{field} must include a timezone.")
    return parsed.astimezone(dt.UTC)


def _timestamp(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _normalize_sha256(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    digest = value.strip().lower()
    if digest.startswith("sha256:"):
        digest = digest[7:]
    return digest if _SHA256_RE.fullmatch(digest) else None


def _semantic_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(value))).hexdigest()


def _issue(code: str, field: str, message: str) -> dict[str, str]:
    return {"code": code, "field": field, "message": message}


def _meaningful(value: object) -> tuple[bool, str]:
    if not isinstance(value, str) or not value.strip():
        return False, "MISSING_FIELD"
    normalized = " ".join(value.casefold().split())
    tokens = _TOKEN_RE.findall(normalized)
    if normalized in _PLACEHOLDER_VALUES or any(token in _PLACEHOLDER_VALUES for token in tokens):
        return False, "PLACEHOLDER_TEXT"
    alphanumeric = "".join(tokens)
    if len(alphanumeric) < 3 or len(set(alphanumeric)) < 3:
        return False, "NON_SEMANTIC_TEXT"
    return True, ""


def _text_issue(plan: Mapping[str, Any], field: str, issues: list[dict[str, str]]) -> None:
    valid, code = _meaningful(plan.get(field))
    if not valid:
        issues.append(
            _issue(code, field, "A required semantic text field is missing or non-meaningful.")
        )


def _list_of_text_issue(plan: Mapping[str, Any], field: str, issues: list[dict[str, str]]) -> None:
    value = plan.get(field)
    if not isinstance(value, list) or not value:
        issues.append(_issue("EMPTY_LIST", field, "A required semantic list is empty."))
        return
    if any(not _meaningful(item)[0] for item in value):
        issues.append(
            _issue(
                "NON_SEMANTIC_LIST_ITEM",
                field,
                "A required semantic list contains a missing or non-meaningful item.",
            )
        )


def _steps_issue(plan: Mapping[str, Any], issues: list[dict[str, str]]) -> None:
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        issues.append(_issue("EMPTY_LIST", "steps", "At least one observable step is required."))
        return
    expected = {"action", "expected_result", "observable_signal"}
    for step in steps:
        if not isinstance(step, Mapping) or set(step) != expected:
            issues.append(
                _issue("INVALID_STEP", "steps", "Every step must use the strict observable shape.")
            )
            continue
        if any(not _meaningful(step.get(field))[0] for field in sorted(expected)):
            issues.append(
                _issue(
                    "NON_OBSERVABLE_STEP",
                    "steps",
                    "Every step requires a meaningful action, signal, and expected result.",
                )
            )


def _safe_https_url(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 2048:
        return False
    parsed = urlsplit(value.strip())
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _references_issue(
    plan: Mapping[str, Any], field: str, *, require_url: bool, issues: list[dict[str, str]]
) -> bool:
    references = plan.get(field)
    uncertain = False
    if not isinstance(references, list) or not references:
        issues.append(_issue("EMPTY_LIST", field, "At least one reference is required."))
        return uncertain
    expected = {"id", "state", "url"}
    for reference in references:
        if not isinstance(reference, Mapping) or set(reference) != expected:
            issues.append(
                _issue("INVALID_REFERENCE", field, "Every reference must use the strict shape.")
            )
            continue
        if not _meaningful(reference.get("id"))[0]:
            issues.append(_issue("INVALID_REFERENCE_ID", field, "Reference id is not meaningful."))
        url = reference.get("url")
        if require_url and not _safe_https_url(url):
            issues.append(
                _issue("INVALID_REFERENCE_URL", field, "Reference URL is not safe HTTPS.")
            )
        elif url is not None and not _safe_https_url(url):
            issues.append(
                _issue("INVALID_REFERENCE_URL", field, "Reference URL is not safe HTTPS.")
            )
        state = reference.get("state")
        if state not in _REFERENCE_STATES:
            issues.append(
                _issue("INVALID_REFERENCE_STATE", field, "Reference state is unsupported.")
            )
        elif state == "BROKEN":
            issues.append(
                _issue("BROKEN_REFERENCE", field, "A required reference is declared broken.")
            )
        elif state == "UNKNOWN":
            issues.append(_issue("UNKNOWN_REFERENCE", field, "Reference availability is unknown."))
            uncertain = True
    return uncertain


def _evaluate_plan(control_id: str, value: object) -> tuple[SemanticStatus, list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    if not isinstance(value, Mapping):
        return "FAIL", [
            _issue(
                "UNSTRUCTURED_PLAN",
                _PLAN_KEYS[control_id],
                "The plan is absent or does not use the structured semantic contract.",
            )
        ]

    expected = _PLAN_FIELDS[control_id]
    if set(value) - expected:
        issues.append(
            _issue("UNSUPPORTED_FIELD", _PLAN_KEYS[control_id], "The plan has unsupported fields.")
        )

    applicable = value.get("applicable")
    if type(applicable) is not bool:
        issues.append(
            _issue("INVALID_APPLICABILITY", "applicable", "Applicability must be explicit.")
        )

    contradictions = value.get("contradictions")
    if not isinstance(contradictions, list):
        issues.append(
            _issue("INVALID_CONTRADICTIONS", "contradictions", "Contradictions must be a list.")
        )
    elif contradictions:
        issues.append(
            _issue(
                "CONTRADICTION_DECLARED",
                "contradictions",
                "The producer declared contradictory plan information.",
            )
        )

    if applicable is False:
        valid_reason, code = _meaningful(value.get("not_applicable_reason"))
        if not valid_reason:
            issues.append(
                _issue(
                    code, "not_applicable_reason", "Non-applicability requires a meaningful reason."
                )
            )
        return ("FAIL" if issues else "NOT_APPLICABLE"), sorted(
            issues, key=lambda item: (item["field"], item["code"])
        )

    _text_issue(value, "owner", issues)
    duration = value.get("duration_minutes")
    if type(duration) is not int or duration < 1 or duration > 10080:
        issues.append(
            _issue(
                "INVALID_DURATION",
                "duration_minutes",
                "Duration must be an integer from 1 to 10080 minutes.",
            )
        )
    _list_of_text_issue(value, "success_criteria", issues)
    _steps_issue(value, issues)

    uncertain = False
    if control_id == "rollback-plan":
        _text_issue(value, "action", issues)
        _text_issue(value, "trigger", issues)
    elif control_id == "monitoring-plan":
        uncertain |= _references_issue(value, "dashboards", require_url=True, issues=issues)
        uncertain |= _references_issue(value, "alerts", require_url=False, issues=issues)

    status: SemanticStatus
    if any(item["code"] != "UNKNOWN_REFERENCE" for item in issues):
        status = "FAIL"
    elif uncertain:
        status = "UNKNOWN"
    else:
        status = "PASS"
    return status, sorted(issues, key=lambda item: (item["field"], item["code"]))


def _safe_source(value: object) -> tuple[str, bool]:
    try:
        return _identifier(value, "evidence.source"), True
    except SemanticValidationError:
        return "invalid-source", False


def _evidence_state(
    reference: SemanticEvidenceReference | None,
    evaluated_at: dt.datetime,
    policy: SemanticValidationPolicy,
) -> tuple[FreshnessStatus, str, dict[str, Any], list[dict[str, str]], bool]:
    if reference is None:
        absent_record: dict[str, Any] = {
            "source": "not-provided",
            "provider_status": "ABSENT",
            "parser_status": "OK",
            "collected_at": None,
            "valid_until": None,
            "effective_valid_until": None,
            "hash": None,
        }
        return (
            "UNKNOWN",
            "UNKNOWN",
            absent_record,
            [_issue("PROVIDER_ABSENT", "evidence", "No evidence provider was supplied.")],
            False,
        )

    source, source_valid = _safe_source(reference.source)
    provider_status = str(reference.provider_status)
    parser_status = str(reference.parser_status)
    record: dict[str, Any] = {
        "source": source,
        "provider_status": (provider_status if provider_status in _PROVIDER_STATUSES else "ERROR"),
        "parser_status": parser_status if parser_status in _PARSER_STATUSES else "ERROR",
        "collected_at": None,
        "valid_until": None,
        "effective_valid_until": None,
        "hash": None,
    }
    issues: list[dict[str, str]] = []
    if not source_valid:
        issues.append(_issue("INVALID_SOURCE", "evidence.source", "Evidence source is invalid."))
    if provider_status not in _PROVIDER_STATUSES:
        issues.append(
            _issue(
                "INVALID_PROVIDER_STATUS", "evidence.provider_status", "Provider status is invalid."
            )
        )
    elif provider_status == "ERROR":
        issues.append(
            _issue("PROVIDER_ERROR", "evidence", "The evidence provider reported an error.")
        )
    elif provider_status == "ABSENT":
        issues.append(_issue("PROVIDER_ABSENT", "evidence", "The evidence provider is absent."))
    if parser_status not in _PARSER_STATUSES:
        issues.append(
            _issue("INVALID_PARSER_STATUS", "evidence.parser_status", "Parser status is invalid.")
        )
    elif parser_status == "ERROR":
        issues.append(_issue("PARSER_ERROR", "evidence", "The evidence parser reported an error."))

    digest = _normalize_sha256(reference.sha256)
    if digest is not None:
        record["hash"] = {"algorithm": "sha256", "value": digest}
    elif reference.sha256 is None:
        issues.append(_issue("DIGEST_MISSING", "evidence.sha256", "Evidence digest is missing."))
    else:
        issues.append(_issue("DIGEST_INVALID", "evidence.sha256", "Evidence digest is invalid."))

    collected: dt.datetime | None = None
    valid_until: dt.datetime | None = None
    try:
        if reference.collected_at is not None:
            collected = _parse_timestamp(reference.collected_at, "evidence.collected_at")
            record["collected_at"] = _timestamp(collected)
        else:
            issues.append(
                _issue(
                    "COLLECTED_AT_MISSING", "evidence.collected_at", "Collection time is missing."
                )
            )
        if reference.valid_until is not None:
            valid_until = _parse_timestamp(reference.valid_until, "evidence.valid_until")
            record["valid_until"] = _timestamp(valid_until)
        else:
            issues.append(
                _issue("VALID_UNTIL_MISSING", "evidence.valid_until", "Expiry time is missing.")
            )
    except SemanticValidationError:
        issues.append(_issue("TIMESTAMP_INVALID", "evidence", "Evidence timestamp is invalid."))

    freshness: FreshnessStatus = "UNKNOWN"
    if collected is not None and valid_until is not None:
        invalid_interval = valid_until < collected
        from_future = collected > evaluated_at
        if invalid_interval:
            issues.append(
                _issue(
                    "INVALID_VALIDITY_INTERVAL",
                    "evidence",
                    "Evidence validity interval is invalid.",
                )
            )
        if from_future:
            issues.append(
                _issue(
                    "EVIDENCE_FROM_FUTURE", "evidence.collected_at", "Evidence is from the future."
                )
            )
        if not invalid_interval and not from_future:
            policy_deadline = collected + dt.timedelta(seconds=policy.max_age_seconds)
            effective = min(valid_until, policy_deadline)
            record["effective_valid_until"] = _timestamp(effective)
            freshness = "STALE" if effective < evaluated_at else "FRESH"
            if freshness == "STALE":
                issues.append(_issue("EVIDENCE_EXPIRED", "evidence", "Evidence is expired."))

    error_codes = {
        "DIGEST_INVALID",
        "EVIDENCE_FROM_FUTURE",
        "INVALID_PARSER_STATUS",
        "INVALID_PROVIDER_STATUS",
        "INVALID_SOURCE",
        "INVALID_VALIDITY_INTERVAL",
        "PARSER_ERROR",
        "PROVIDER_ERROR",
        "TIMESTAMP_INVALID",
    }
    if any(item["code"] in error_codes for item in issues):
        gate = "ERROR"
    elif provider_status == "ABSENT" or digest is None or freshness == "UNKNOWN":
        gate = "UNKNOWN"
    elif freshness == "STALE":
        gate = "STALE"
    else:
        gate = "READY"
    provenance = (
        source_valid
        and provider_status == "AVAILABLE"
        and parser_status == "OK"
        and digest is not None
    )
    return (
        freshness,
        gate,
        record,
        sorted(issues, key=lambda item: (item["field"], item["code"])),
        provenance,
    )


def _final_status(semantic: SemanticStatus, gate: str) -> SemanticStatus:
    if gate == "ERROR":
        return "ERROR"
    if gate == "UNKNOWN":
        return "UNKNOWN"
    if gate == "STALE" and semantic in {"PASS", "NOT_APPLICABLE"}:
        return "UNKNOWN"
    return semantic


def _confidence(
    semantic: SemanticStatus,
    final: SemanticStatus,
    freshness: FreshnessStatus,
    provider_status: str,
    provenance: bool,
) -> dict[str, Any]:
    determinability = 60 if semantic in {"PASS", "FAIL", "NOT_APPLICABLE"} else 20
    freshness_points = 25 if freshness == "FRESH" else 5 if freshness == "STALE" else 0
    provenance_points = 15 if provenance else 0
    cap = 100
    if final == "ERROR":
        cap = min(cap, 20)
    if provider_status == "ABSENT":
        cap = min(cap, 25)
    if freshness == "UNKNOWN":
        cap = min(cap, 40)
    if freshness == "STALE":
        cap = min(cap, 49)
    if final == "UNKNOWN":
        cap = min(cap, 49)
    value = min(cap, determinability + freshness_points + provenance_points)
    level = "HIGH" if value >= 80 else "MEDIUM" if value >= 50 else "LOW"
    return {
        "value": value,
        "level": level,
        "basis": SEMANTIC_CONFIDENCE_BASIS,
        "cap": cap,
        "components": {
            "determinability": determinability,
            "freshness": freshness_points,
            "provenance": provenance_points,
        },
    }


def _overall_status(statuses: list[str]) -> str:
    for candidate in ("ERROR", "FAIL", "UNKNOWN", "PASS", "NOT_APPLICABLE"):
        if candidate in statuses:
            return candidate
    raise SemanticValidationError("At least one semantic control is required.")


class SemanticValidator:
    """Pure evaluator for Semantic Validation Contract v1."""

    def evaluate(
        self,
        *,
        plans: Mapping[str, Any],
        evidence: Mapping[str, SemanticEvidenceReference],
        evaluated_at: dt.datetime | str,
        policy: SemanticValidationPolicy | None = None,
        source_contract: str = "semantic-change-controls-v1",
        data_classification: str = "internal",
    ) -> dict[str, Any]:
        if not isinstance(plans, Mapping) or set(plans) - set(_PLAN_KEYS.values()):
            raise SemanticValidationError("plans must use only supported control fields.")
        if not isinstance(evidence, Mapping) or set(evidence) - set(_CONTROL_IDS):
            raise SemanticValidationError("evidence must use only supported control ids.")
        if data_classification not in {"public", "internal", "confidential", "restricted"}:
            raise SemanticValidationError("data_classification is unsupported.")
        evaluated = _parse_timestamp(evaluated_at, "evaluated_at")
        selected_policy = policy or SemanticValidationPolicy()
        policy_record = selected_policy.to_dict()

        controls: list[dict[str, Any]] = []
        for control_id in _CONTROL_IDS:
            semantic_status, semantic_issues = _evaluate_plan(
                control_id, plans.get(_PLAN_KEYS[control_id])
            )
            reference = evidence.get(control_id)
            if reference is not None and not isinstance(reference, SemanticEvidenceReference):
                raise SemanticValidationError("evidence values must be SemanticEvidenceReference.")
            freshness, gate, evidence_record, evidence_issues, provenance = _evidence_state(
                reference, evaluated, selected_policy
            )
            status = _final_status(semantic_status, gate)
            confidence = _confidence(
                semantic_status,
                status,
                freshness,
                evidence_record["provider_status"],
                provenance,
            )
            issues = sorted(
                semantic_issues + evidence_issues,
                key=lambda item: (item["field"], item["code"]),
            )
            body = {
                "control_id": control_id,
                "status": status,
                "freshness": freshness,
                "confidence": confidence,
                "issues": issues,
                "evidence": evidence_record,
            }
            controls.append(
                {
                    "execution_id": f"urn:preflightops:semantic-control:sha256:{_semantic_digest(body)}",
                    **body,
                }
            )

        statuses = [str(item["status"]) for item in controls]
        confidence_value = sum(item["confidence"]["value"] for item in controls) // len(controls)
        semantic: dict[str, Any] = {
            "schema_version": SEMANTIC_VALIDATION_SCHEMA_VERSION,
            "evaluated_at": _timestamp(evaluated),
            "policy": policy_record,
            "controls": controls,
            "summary": {
                "status": _overall_status(statuses),
                "confidence": {
                    "value": confidence_value,
                    "level": (
                        "HIGH"
                        if confidence_value >= 80
                        else "MEDIUM"
                        if confidence_value >= 50
                        else "LOW"
                    ),
                    "basis": SEMANTIC_CONFIDENCE_BASIS,
                },
                "counts": {status: statuses.count(status) for status in sorted(_STATUSES)},
            },
            "compatibility": {
                "source_contract": _identifier(source_contract, "compatibility.source_contract"),
                "adapter_version": SEMANTIC_VALIDATION_ADAPTER_VERSION,
                "legacy_validators_preserved": True,
                "legacy_output_preserved": source_contract != "semantic-change-controls-v1",
            },
            "data": {
                "classification": data_classification,
                "content_embedded": False,
                "metadata_profile": "preflightops-semantic-metadata-v1",
            },
        }
        digest = _semantic_digest(semantic)
        contract = {
            **semantic,
            "semantic_validation_id": f"urn:preflightops:semantic-validation:sha256:{digest}",
            "integrity": {
                "algorithm": "sha256",
                "value": digest,
                "canonicalization": SEMANTIC_VALIDATION_CANONICALIZATION,
            },
        }
        validate_semantic_validation_v1(contract)
        return contract


def _expect_exact(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise SemanticValidationError(f"{name} has an invalid shape.")
    return value


def validate_semantic_validation_v1(contract: Mapping[str, Any]) -> None:
    """Validate strict shape, cross-field invariants, IDs, and integrity."""

    top = _expect_exact(
        contract,
        {
            "compatibility",
            "controls",
            "data",
            "evaluated_at",
            "integrity",
            "policy",
            "schema_version",
            "semantic_validation_id",
            "summary",
        },
        "semantic_validation",
    )
    if top["schema_version"] != SEMANTIC_VALIDATION_SCHEMA_VERSION:
        raise SemanticValidationError("semantic_validation.schema_version is unsupported.")
    evaluated_at = _parse_timestamp(top["evaluated_at"], "semantic_validation.evaluated_at")
    policy = _expect_exact(
        top["policy"],
        {"confidence_basis", "max_age_seconds", "name", "version"},
        "semantic_validation.policy",
    )
    _identifier(policy["name"], "semantic_validation.policy.name")
    _identifier(policy["version"], "semantic_validation.policy.version")
    if policy["confidence_basis"] != SEMANTIC_CONFIDENCE_BASIS:
        raise SemanticValidationError("semantic_validation.policy confidence basis is invalid.")
    if type(policy["max_age_seconds"]) is not int or policy["max_age_seconds"] < 1:
        raise SemanticValidationError("semantic_validation.policy max age is invalid.")

    controls = top["controls"]
    if not isinstance(controls, list) or [item.get("control_id") for item in controls] != list(
        _CONTROL_IDS
    ):
        raise SemanticValidationError("semantic_validation.controls are incomplete or unsorted.")
    statuses: list[str] = []
    confidence_values: list[int] = []
    for index, item in enumerate(controls):
        record = _expect_exact(
            item,
            {
                "confidence",
                "control_id",
                "evidence",
                "execution_id",
                "freshness",
                "issues",
                "status",
            },
            f"semantic_validation.controls[{index}]",
        )
        status = str(record["status"])
        freshness = str(record["freshness"])
        if status not in _STATUSES or freshness not in _FRESHNESS:
            raise SemanticValidationError("semantic_validation control state is invalid.")
        evidence = _expect_exact(
            record["evidence"],
            {
                "collected_at",
                "effective_valid_until",
                "hash",
                "parser_status",
                "provider_status",
                "source",
                "valid_until",
            },
            f"semantic_validation.controls[{index}].evidence",
        )
        _identifier(evidence["source"], "semantic_validation.evidence.source")
        if evidence["provider_status"] not in _PROVIDER_STATUSES:
            raise SemanticValidationError("semantic_validation provider status is invalid.")
        if evidence["parser_status"] not in _PARSER_STATUSES:
            raise SemanticValidationError("semantic_validation parser status is invalid.")
        parsed_times: dict[str, dt.datetime | None] = {}
        for field in ("collected_at", "valid_until", "effective_valid_until"):
            if evidence[field] is not None:
                parsed_times[field] = _parse_timestamp(
                    evidence[field], f"semantic_validation.evidence.{field}"
                )
            else:
                parsed_times[field] = None
        digest = evidence["hash"]
        if digest is not None:
            digest_record = _expect_exact(
                digest, {"algorithm", "value"}, "semantic_validation.evidence.hash"
            )
            if (
                digest_record["algorithm"] != "sha256"
                or _normalize_sha256(digest_record["value"]) is None
            ):
                raise SemanticValidationError("semantic_validation evidence hash is invalid.")
        if status in {"PASS", "NOT_APPLICABLE"} and (
            freshness != "FRESH"
            or evidence["provider_status"] != "AVAILABLE"
            or evidence["parser_status"] != "OK"
            or digest is None
        ):
            raise SemanticValidationError("PASS/N/A requires fresh digest-pinned evidence.")
        collected = parsed_times["collected_at"]
        valid_until = parsed_times["valid_until"]
        effective = parsed_times["effective_valid_until"]
        if (
            collected is not None
            and valid_until is not None
            and valid_until >= collected
            and collected <= evaluated_at
        ):
            expected_effective = min(
                valid_until,
                collected + dt.timedelta(seconds=policy["max_age_seconds"]),
            )
            expected_freshness = "STALE" if expected_effective < evaluated_at else "FRESH"
            if effective != expected_effective or freshness != expected_freshness:
                raise SemanticValidationError(
                    "semantic_validation freshness calculation is invalid."
                )
        elif effective is not None or freshness != "UNKNOWN":
            raise SemanticValidationError("semantic_validation unknown freshness is inconsistent.")
        confidence = _expect_exact(
            record["confidence"],
            {"basis", "cap", "components", "level", "value"},
            f"semantic_validation.controls[{index}].confidence",
        )
        components = _expect_exact(
            confidence["components"],
            {"determinability", "freshness", "provenance"},
            f"semantic_validation.controls[{index}].confidence.components",
        )
        if confidence["basis"] != SEMANTIC_CONFIDENCE_BASIS:
            raise SemanticValidationError("semantic_validation confidence basis is invalid.")
        if any(type(components[field]) is not int for field in components):
            raise SemanticValidationError("semantic_validation confidence components are invalid.")
        if components["determinability"] not in {0, 20, 60}:
            raise SemanticValidationError(
                "semantic_validation determinability component is invalid."
            )
        if status in {"PASS", "FAIL", "NOT_APPLICABLE"} and (components["determinability"] != 60):
            raise SemanticValidationError("semantic_validation determinability is inconsistent.")
        expected_freshness_points = 25 if freshness == "FRESH" else 5 if freshness == "STALE" else 0
        if components["freshness"] != expected_freshness_points:
            raise SemanticValidationError("semantic_validation freshness confidence is invalid.")
        raw_issues = record["issues"]
        if not isinstance(raw_issues, list):
            raise SemanticValidationError("semantic_validation issues must be a list.")
        issue_codes = {issue.get("code") for issue in raw_issues if isinstance(issue, Mapping)}
        expected_provenance = (
            15
            if evidence["provider_status"] == "AVAILABLE"
            and evidence["parser_status"] == "OK"
            and digest is not None
            and "INVALID_SOURCE" not in issue_codes
            else 0
        )
        if components["provenance"] != expected_provenance:
            raise SemanticValidationError("semantic_validation provenance confidence is invalid.")
        value = confidence["value"]
        cap = confidence["cap"]
        if type(value) is not int or type(cap) is not int or not 0 <= value <= cap <= 100:
            raise SemanticValidationError("semantic_validation confidence is invalid.")
        if value != min(cap, sum(components.values())):
            raise SemanticValidationError("semantic_validation confidence formula is invalid.")
        expected_cap = 100
        if status == "ERROR":
            expected_cap = min(expected_cap, 20)
        if evidence["provider_status"] == "ABSENT":
            expected_cap = min(expected_cap, 25)
        if freshness == "UNKNOWN":
            expected_cap = min(expected_cap, 40)
        if freshness == "STALE":
            expected_cap = min(expected_cap, 49)
        if status == "UNKNOWN":
            expected_cap = min(expected_cap, 49)
        if cap != expected_cap:
            raise SemanticValidationError("semantic_validation confidence cap is inconsistent.")
        expected_level = "HIGH" if value >= 80 else "MEDIUM" if value >= 50 else "LOW"
        if confidence["level"] != expected_level:
            raise SemanticValidationError("semantic_validation confidence level is invalid.")
        if status == "ERROR" and cap > 20:
            raise SemanticValidationError("ERROR confidence cap is invalid.")
        if status == "UNKNOWN" and cap > 49:
            raise SemanticValidationError("UNKNOWN confidence cap is invalid.")
        issues = raw_issues
        if issues != sorted(issues, key=lambda issue: (issue["field"], issue["code"])):
            raise SemanticValidationError("semantic_validation issues must be sorted.")
        for issue in issues:
            issue_record = _expect_exact(
                issue, {"code", "field", "message"}, "semantic_validation.issue"
            )
            _identifier(issue_record["code"], "semantic_validation.issue.code")
            if not isinstance(issue_record["field"], str) or not issue_record["field"]:
                raise SemanticValidationError("semantic_validation issue field is invalid.")
            if not isinstance(issue_record["message"], str) or not issue_record["message"]:
                raise SemanticValidationError("semantic_validation issue message is invalid.")
        if status in {"PASS", "NOT_APPLICABLE"} and issues:
            raise SemanticValidationError("PASS/N/A controls cannot contain issues.")
        if status in {"FAIL", "UNKNOWN", "ERROR"} and not issues:
            raise SemanticValidationError("Non-passing controls require explicit issues.")
        body = dict(record)
        execution_id = body.pop("execution_id")
        expected_execution = f"urn:preflightops:semantic-control:sha256:{_semantic_digest(body)}"
        if execution_id != expected_execution:
            raise SemanticValidationError("semantic_validation execution_id is invalid.")
        statuses.append(status)
        confidence_values.append(value)

    summary = _expect_exact(
        top["summary"], {"confidence", "counts", "status"}, "semantic_validation.summary"
    )
    if summary["status"] != _overall_status(statuses):
        raise SemanticValidationError("semantic_validation summary status is invalid.")
    expected_counts = {status: statuses.count(status) for status in sorted(_STATUSES)}
    if summary["counts"] != expected_counts:
        raise SemanticValidationError("semantic_validation summary counts are invalid.")
    summary_confidence = _expect_exact(
        summary["confidence"], {"basis", "level", "value"}, "semantic_validation.summary.confidence"
    )
    expected_value = sum(confidence_values) // len(confidence_values)
    expected_level = "HIGH" if expected_value >= 80 else "MEDIUM" if expected_value >= 50 else "LOW"
    if summary_confidence != {
        "value": expected_value,
        "level": expected_level,
        "basis": SEMANTIC_CONFIDENCE_BASIS,
    }:
        raise SemanticValidationError("semantic_validation summary confidence is invalid.")

    compatibility = _expect_exact(
        top["compatibility"],
        {
            "adapter_version",
            "legacy_output_preserved",
            "legacy_validators_preserved",
            "source_contract",
        },
        "semantic_validation.compatibility",
    )
    _identifier(compatibility["source_contract"], "semantic_validation.source_contract")
    if compatibility["adapter_version"] != SEMANTIC_VALIDATION_ADAPTER_VERSION:
        raise SemanticValidationError("semantic_validation adapter version is invalid.")
    if (
        compatibility["legacy_validators_preserved"] is not True
        or type(compatibility["legacy_output_preserved"]) is not bool
    ):
        raise SemanticValidationError("semantic_validation compatibility flags are invalid.")
    expected_legacy = compatibility["source_contract"] != "semantic-change-controls-v1"
    if compatibility["legacy_output_preserved"] is not expected_legacy:
        raise SemanticValidationError("semantic_validation legacy compatibility is inconsistent.")
    data = _expect_exact(
        top["data"],
        {"classification", "content_embedded", "metadata_profile"},
        "semantic_validation.data",
    )
    if data["classification"] not in {"public", "internal", "confidential", "restricted"}:
        raise SemanticValidationError("semantic_validation classification is invalid.")
    if data["content_embedded"] is not False or data["metadata_profile"] != (
        "preflightops-semantic-metadata-v1"
    ):
        raise SemanticValidationError("semantic_validation data boundary is invalid.")

    integrity = _expect_exact(
        top["integrity"],
        {"algorithm", "canonicalization", "value"},
        "semantic_validation.integrity",
    )
    if integrity["algorithm"] != "sha256" or integrity["canonicalization"] != (
        SEMANTIC_VALIDATION_CANONICALIZATION
    ):
        raise SemanticValidationError("semantic_validation integrity profile is invalid.")
    claimed = _normalize_sha256(integrity["value"])
    semantic = dict(top)
    semantic.pop("semantic_validation_id")
    semantic.pop("integrity")
    actual = _semantic_digest(semantic)
    if claimed != actual:
        raise SemanticValidationError("semantic_validation integrity does not match content.")
    if top["semantic_validation_id"] != (f"urn:preflightops:semantic-validation:sha256:{actual}"):
        raise SemanticValidationError("semantic_validation id does not match content.")


def serialize_semantic_validation_v1(contract: Mapping[str, Any]) -> bytes:
    """Return canonical UTF-8 JSON with one trailing LF."""

    validate_semantic_validation_v1(contract)
    return canonical_json(dict(contract)) + b"\n"


def adapt_legacy_change_request(
    change_request: Mapping[str, Any],
    *,
    evidence: Mapping[str, SemanticEvidenceReference],
    evaluated_at: dt.datetime | str,
    policy: SemanticValidationPolicy | None = None,
    data_classification: str = "internal",
) -> dict[str, Any]:
    """Evaluate Change Request v1 without mutating or replacing legacy outputs.

    The adapter deliberately does not infer structured fields from prose. Legacy
    strings/lists therefore fail semantic completeness or remain UNKNOWN when their
    evidence provider is absent.
    """

    if not isinstance(change_request, Mapping):
        raise SemanticValidationError("change_request must be an object.")
    nested = change_request.get("change", change_request)
    if not isinstance(nested, Mapping):
        raise SemanticValidationError("change_request.change must be an object.")
    plans = {field: nested.get(field) for field in _PLAN_KEYS.values()}
    return SemanticValidator().evaluate(
        plans=plans,
        evidence=evidence,
        evaluated_at=evaluated_at,
        policy=policy,
        source_contract="change-request-v1",
        data_classification=data_classification,
    )

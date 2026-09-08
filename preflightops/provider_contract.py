"""Immutable, offline Evidence Provider Contract v1 primitives.

References are opaque approved identifiers, never provider URLs or payloads.
Provider adapters are responsible for projecting safe summaries before construction.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from typing import Any, Literal

from .evidence import canonical_json

ProviderStatus = Literal["PASS", "FAIL", "UNKNOWN", "ERROR", "NOT_APPLICABLE"]
STATUSES = frozenset({"PASS", "FAIL", "UNKNOWN", "ERROR", "NOT_APPLICABLE"})
ERROR_CODES = frozenset(
    {
        "TIMEOUT",
        "CANCELLED",
        "AUTH",
        "RATE_LIMIT",
        "UNAVAILABLE",
        "INVALID_RESPONSE",
        "INTERNAL",
        "MISSING",
        "STALE",
        "FUTURE",
    }
)
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}\Z")
_SECRET = re.compile(r"(?i)(password|secret|token|authorization|cookie|api.?key)\s*[:=]")


class ProviderContractError(ValueError):
    """A static, content-free contract validation error."""


def _identifier(value: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ProviderContractError("Invalid opaque identifier.")


def _timestamp(value: str) -> dt.datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value
    ):
        raise ProviderContractError("Expected canonical UTC timestamp.")
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ProviderContractError("Invalid UTC timestamp.") from None


def _summary(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 512
        or any(ord(c) < 32 for c in value)
        or _SECRET.search(value)
    ):
        raise ProviderContractError("Expected bounded approved summary without secrets.")


@dataclass(frozen=True, slots=True)
class ProviderEvidence:
    """One control observation. No implicit clocks, network access or credentials."""

    provider: str
    provider_version: str
    control_id: str
    status: ProviderStatus
    summary: str
    source_reference: str
    collected_at: str
    valid_until: str
    confidence: int
    error_code: str | None = None
    raw_evidence_reference: str | None = None
    sensitivity: str = "internal"
    redaction: str = "summary_only"
    not_applicable_reason: str | None = None
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        for value in (self.status, self.sensitivity, self.redaction, self.schema_version):
            if not isinstance(value, str):
                raise ProviderContractError("Contract discriminators must be strings.")
        if self.error_code is not None and not isinstance(self.error_code, str):
            raise ProviderContractError("Invalid error category.")
        for value in (self.provider, self.provider_version, self.control_id, self.source_reference):
            _identifier(value)
        if self.schema_version != "1.0" or self.status not in STATUSES:
            raise ProviderContractError("Unsupported contract version or status.")
        _summary(self.summary)
        if _timestamp(self.valid_until) <= _timestamp(self.collected_at):
            raise ProviderContractError("Validity interval must be positive.")
        if type(self.confidence) is not int or not 0 <= self.confidence <= 100:
            raise ProviderContractError("Confidence must be an integer from 0 to 100.")
        if self.status in {"ERROR", "UNKNOWN"}:
            if self.confidence != 0 or self.error_code not in ERROR_CODES:
                raise ProviderContractError("Unknown/error requires zero confidence and taxonomy.")
        elif self.error_code is not None:
            raise ProviderContractError("Conclusive observations cannot contain an error.")
        if self.status == "NOT_APPLICABLE":
            _summary(self.not_applicable_reason)  # type: ignore[arg-type]
            if self.confidence != 0:
                raise ProviderContractError("Not-applicable is not positive evidence.")
        elif self.not_applicable_reason is not None:
            raise ProviderContractError("Unexpected not-applicable reason.")
        if self.raw_evidence_reference is not None:
            _identifier(self.raw_evidence_reference)
        if self.sensitivity not in {"public", "internal", "confidential"}:
            raise ProviderContractError("Unsupported sensitivity classification.")
        if self.redaction != "summary_only":
            raise ProviderContractError("Raw content is prohibited.")

    def canonical_bytes(self) -> bytes:
        """Stable serialized representation containing only the approved projection."""
        return canonical_json(asdict(self))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def effective_status(self, evaluated_at: str) -> ProviderStatus:
        """Freshness cannot promote an unknown or failed observation to PASS."""
        instant = _timestamp(evaluated_at)
        if self.status in {"ERROR", "UNKNOWN", "FAIL"}:
            return self.status
        if not _timestamp(self.collected_at) <= instant < _timestamp(self.valid_until):
            return "UNKNOWN"
        return self.status


def parse_provider_evidence(value: Mapping[str, Any]) -> ProviderEvidence:
    """Strict decoder: require every versioned field, including explicit nulls."""
    expected = {f.name for f in fields(ProviderEvidence)}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ProviderContractError("Provider contract fields do not match version 1.0.")
    return ProviderEvidence(**dict(value))

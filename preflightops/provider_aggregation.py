"""Deterministic projection of provider observations into the Trust Kernel."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from .assessment import ControlObservation
from .evidence import canonical_json
from .provider_contract import ProviderContractError, ProviderEvidence, _identifier, _timestamp


@dataclass(frozen=True, slots=True)
class ProviderAggregate:
    evaluated_at: str
    evidence: tuple[ProviderEvidence, ...]

    def __post_init__(self) -> None:
        _timestamp(self.evaluated_at)
        if type(self.evidence) is not tuple or not 1 <= len(self.evidence) <= 1024:
            raise ProviderContractError("Expected bounded immutable aggregate evidence.")
        identities = []
        for item in self.evidence:
            if not isinstance(item, ProviderEvidence):
                raise ProviderContractError("Invalid aggregate observation.")
            item.__post_init__()
            identities.append((item.provider, item.provider_version, item.control_id))
        if identities != sorted(set(identities)):
            raise ProviderContractError("Aggregate observations must be unique and sorted.")

    @property
    def confidence_cap(self) -> int:
        applicable = [e for e in self.evidence if e.status != "NOT_APPLICABLE"]
        instant = _timestamp(self.evaluated_at)
        return min(
            (
                e.confidence
                if _timestamp(e.collected_at) <= instant < _timestamp(e.valid_until)
                else 0
                for e in applicable
            ),
            default=0,
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json(
            {
                "schema_version": "1.0",
                "evaluated_at": self.evaluated_at,
                "evidence": [asdict(e) for e in self.evidence],
                "confidence_cap": self.confidence_cap,
            }
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def controls(self) -> tuple[ControlObservation, ...]:
        """v1 has no N/A state: preserve it as UNKNOWN, never fabricate PASS.

        The caller supplies risk independently and must apply confidence_cap.
        """
        result = []
        for e in self.evidence:
            identity = hashlib.sha256(
                canonical_json([e.provider, e.provider_version, e.control_id])
            ).hexdigest()
            effective = e.effective_status(self.evaluated_at)
            status = "UNKNOWN" if effective == "NOT_APPLICABLE" else effective
            result.append(
                ControlObservation(
                    control_id="provider-" + identity,
                    status=status,
                    summary=e.summary,
                    source=e.provider,
                    collected_at=e.collected_at,
                    valid_until=e.valid_until,
                    evidence_sha256=e.digest,
                    evidence_kind="provider-contract-v1",
                )
            )
        return tuple(result)


def aggregate_provider_evidence(
    evidence: Sequence[ProviderEvidence],
    *,
    expected: Sequence[tuple[str, str, str]],
    evaluated_at: str,
) -> ProviderAggregate:
    """Expected identities make absence observable; no arrival-order precedence."""
    instant = _timestamp(evaluated_at)
    if not 1 <= len(expected) <= 1024 or len(evidence) > 1024:
        raise ProviderContractError("Aggregation size must be bounded.")
    for key in expected:
        if type(key) is not tuple or len(key) != 3:
            raise ProviderContractError("Expected provider/version/control identity.")
        for value in key:
            _identifier(value)
    if len(set(expected)) != len(expected):
        raise ProviderContractError("Duplicate expected identity.")
    by_key = {}
    for observed in evidence:
        if not isinstance(observed, ProviderEvidence):
            raise ProviderContractError("Invalid evidence type.")
        observed.__post_init__()
        key = (observed.provider, observed.provider_version, observed.control_id)
        if key not in expected or key in by_key:
            raise ProviderContractError("Unexpected or duplicate evidence identity.")
        by_key[key] = observed
    output = []
    for provider, version, control in sorted(expected):
        item = by_key.get((provider, version, control))
        code = None
        if item is None:
            code = "MISSING"
        elif instant < _timestamp(item.collected_at):
            code = "FUTURE"
        elif instant >= _timestamp(item.valid_until):
            code = "STALE"
        if code is not None:
            # Keep explicit ERROR/FAIL even after expiry; neither may become PASS.
            if item is None or item.status not in {"ERROR", "FAIL"}:
                until = (instant + dt.timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                item = ProviderEvidence(
                    provider,
                    version,
                    control,
                    "UNKNOWN",
                    "Current provider evidence unavailable.",
                    "provider-aggregate",
                    evaluated_at,
                    until,
                    0,
                    error_code=code,
                )
        assert item is not None
        output.append(item)
    return ProviderAggregate(evaluated_at, tuple(output))

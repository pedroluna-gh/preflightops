"""Bounded local operational telemetry, deliberately outside evidence hashes.

Only fixed enums, numbers and approved opaque IDs can enter the recorder. There
is no arbitrary message, label, payload, destination or network exporter API.
"""

from __future__ import annotations

import json
import math
import re
import threading
import uuid
from collections import deque
from collections.abc import Mapping
from typing import Any

from .provider_contract import ERROR_CODES, STATUSES

KINDS = ("cli", "provider")
OUTCOMES = ("completed", "blocked", "degraded", "error")
RISKS = ("LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN")
CACHE = ("hit", "miss", "none")
BUCKETS_MS = (10, 100, 1000, 10000, 120000)
MAX_COUNTER = 2**53 - 1


class OperationsError(ValueError):
    """Content-free operational configuration error."""


def _count(value: int) -> int:
    if type(value) is not int or not 0 <= value <= MAX_COUNTER:
        raise OperationsError("Invalid bounded operational counter.")
    return value


class OperationsRecorder:
    """Thread-safe fixed-cardinality metrics and at most 256 structured events."""

    def __init__(self, correlation_id: str | None = None, *, capacity: int = 256):
        identity = uuid.uuid4().hex if correlation_id is None else correlation_id
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{32}", identity):
            raise OperationsError("Correlation ID must be 32 approved lowercase hex characters.")
        if type(capacity) is not int or not 1 <= capacity <= 256:
            raise OperationsError("Event capacity must be between 1 and 256.")
        self.correlation_id = identity
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._metrics = dict.fromkeys(
            ["events_total", "events_dropped", "retries_total"]
            + [f"operations_{k}_{o}" for k in KINDS for o in OUTCOMES]
            + [f"controls_{s}" for s in sorted(STATUSES)]
            + [f"provider_errors_{e}" for e in sorted(ERROR_CODES)]
            + [f"cache_{c}" for c in CACHE]
            + [f"verdict_{r}" for r in RISKS]
            + [f"latency_{k}_le_{b}_ms" for k in KINDS for b in BUCKETS_MS]
            + [f"latency_{k}_count" for k in KINDS]
            + [f"latency_{k}_sum_ms" for k in KINDS],
            0,
        )

    def record(
        self,
        *,
        kind: str,
        outcome: str,
        duration_seconds: float,
        risk: str = "UNKNOWN",
        controls: Mapping[str, int] | None = None,
        errors: Mapping[str, int] | None = None,
        cache: str = "none",
        assessment_id: str | None = None,
    ) -> None:
        if kind not in KINDS or outcome not in OUTCOMES or risk not in RISKS or cache not in CACHE:
            raise OperationsError("Unsupported operational category.")
        if (
            type(duration_seconds) not in (int, float)
            or not math.isfinite(duration_seconds)
            or not 0 <= duration_seconds <= MAX_COUNTER / 1000
        ):
            raise OperationsError("Invalid operational duration.")
        if assessment_id is not None and (
            not isinstance(assessment_id, str)
            or not re.fullmatch(
                r"(?:urn:preflightops:assessment:sha256:)?[0-9a-f]{64}", assessment_id
            )
        ):
            raise OperationsError("Expected an approved assessment digest identifier.")
        counts = dict(controls or {})
        failures = dict(errors or {})
        if not counts.keys() <= STATUSES or not failures.keys() <= ERROR_CODES:
            raise OperationsError("Unsupported operational counter category.")
        for value in (*counts.values(), *failures.values()):
            _count(value)
        duration_ms = round(duration_seconds * 1000)
        with self._lock:

            def add(key: str, value: int = 1) -> None:
                self._metrics[key] = min(MAX_COUNTER, self._metrics[key] + value)

            add("events_total")
            add(f"operations_{kind}_{outcome}")
            add(f"latency_{kind}_count")
            add(f"latency_{kind}_sum_ms", duration_ms)
            for bound in BUCKETS_MS:
                if duration_ms <= bound:
                    add(f"latency_{kind}_le_{bound}_ms")
            if kind == "cli":
                add(f"verdict_{risk}")
            else:
                add(f"cache_{cache}")
            for status, count in counts.items():
                add(f"controls_{status}", count)
            for code, count in failures.items():
                add(f"provider_errors_{code}", count)
            if len(self._events) == self._events.maxlen:
                add("events_dropped")
            self._events.append(
                {
                    "sequence": self._metrics["events_total"],
                    "correlation_id": self.correlation_id,
                    "assessment_id": assessment_id,
                    "kind": kind,
                    "outcome": outcome,
                    "duration_ms": duration_ms,
                    "risk": risk,
                    "cache": cache,
                    "controls": dict(sorted(counts.items())),
                    "errors": dict(sorted(failures.items())),
                }
            )

    def document(self) -> dict[str, Any]:
        with self._lock:
            # A round trip prevents callers mutating retained nested dictionaries.
            return json.loads(
                json.dumps(
                    {
                        "schema_version": "operations-v1",
                        "correlation_id": self.correlation_id,
                        "event_capacity": self._events.maxlen,
                        "metrics": self._metrics,
                        "events": list(self._events),
                    },
                    allow_nan=False,
                )
            )

    def record_retry(self) -> None:
        """Count an actual additional transport attempt, with no new labels."""
        with self._lock:
            self._metrics["retries_total"] = min(MAX_COUNTER, self._metrics["retries_total"] + 1)

    def serialize(self) -> str:
        return json.dumps(self.document(), sort_keys=True, separators=(",", ":")) + "\n"

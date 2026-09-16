"""Pure failure disposition: continuation never means approval or evidence PASS."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

_CLOSED = frozenset({"policy_validation", "signature", "context_conflict"})
_KNOWN = _CLOSED | {"evidence_unavailable"}


def evaluate_failure_modes(modes: Mapping[str, str], failures: Iterable[str]) -> dict:
    """Evaluate an already validated policy's modes with unknown errors closed.

    Callers must authenticate their policy at the input boundary. This helper
    neither authenticates policy nor assesses evidence and has no external effects.
    """
    if set(modes) != _KNOWN or any(value not in {"open", "closed"} for value in modes.values()):
        raise ValueError("Invalid policy failure modes.")
    if any(modes[name] != "closed" for name in _CLOSED):
        raise ValueError("Governance errors must fail closed.")
    if isinstance(failures, (str, bytes)):
        raise ValueError("Failure types must be a collection.")
    normalized = set()
    for index, failure in enumerate(failures):
        if index >= 1000 or not isinstance(failure, str):
            raise ValueError("Invalid failure collection.")
        normalized.add(failure if failure in _KNOWN else "unclassified_error")
    dispositions = [
        {"type": failure, "mode": modes.get(failure, "closed")} for failure in sorted(normalized)
    ]
    blocked = any(item["mode"] == "closed" for item in dispositions)
    return {
        "schema_version": "governance-failure-v1",
        "failures": dispositions,
        "disposition": "stop" if blocked else "continue_informative" if dispositions else "none",
        "blocking": blocked,
        "automatic_approval": False,
        "human_decision": "not_recorded",
    }

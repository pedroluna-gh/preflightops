"""Offline synthetic operational probe; no production inputs or credentials."""

from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import time
import tracemalloc
from pathlib import Path

from ._version import __version__
from .evidence import canonical_json
from .provider_runtime import FakeProvider, ProviderCapabilities, ProviderRequest, ProviderRunner
from .risk_engine import assess_risk
from .sample_data import LOW_RISK_CHANGE, LOW_RISK_SERVICES


def run_probe(iterations: int = 100) -> dict:
    """Measure a documented warm, single-process workload with zero retries."""
    if type(iterations) is not int or not 10 <= iterations <= 1000:
        raise ValueError("Probe iterations must be between 10 and 1000.")
    baseline = canonical_json(assess_risk(LOW_RISK_SERVICES, LOW_RISK_CHANGE))
    samples = []
    mismatches = 0
    started_tracing = not tracemalloc.is_tracing()
    if started_tracing:
        tracemalloc.start()
    started = time.perf_counter()
    try:
        for _ in range(iterations):
            before = time.perf_counter()
            actual = canonical_json(assess_risk(LOW_RISK_SERVICES, LOW_RISK_CHANGE))
            samples.append((time.perf_counter() - before) * 1000)
            mismatches += actual != baseline
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
    finally:
        if started_tracing:
            tracemalloc.stop()
    samples.sort()
    p95 = samples[math.ceil(iterations * 0.95) - 1]
    # Missing evidence must never be classified as a successful control.
    missing = ProviderRunner().run(
        FakeProvider(ProviderCapabilities("probe", "1", ("monitoring",)), ()),
        ProviderRequest("a" * 64, "b" * 64, ("monitoring",), "2026-01-01T00:00:00Z"),
    )
    fail_closed = all(e.status == "UNKNOWN" and e.error_code == "MISSING" for e in missing)
    goals = {
        "deterministic_replay": mismatches == 0,
        "missing_evidence_fails_closed": fail_closed,
        "p95_at_most_250_ms": p95 <= 250,
        "python_peak_at_most_64_mib": peak <= 64 * 1024 * 1024,
    }
    return {
        "schema_version": "operational-probe-v1",
        "product_version": __version__,
        "python": platform.python_version(),
        "platform": sys.platform,
        "workload": "bundled-low-risk-single-process-warm-v1",
        "iterations": iterations,
        "latency_ms": {"p50": samples[iterations // 2], "p95": p95, "max": samples[-1]},
        "throughput_per_second": iterations / elapsed,
        "peak_python_bytes": peak,
        "replay_mismatches": mismatches,
        "goals": goals,
        "passed": all(goals.values()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--output", type=Path, help="New local JSON result, never overwritten.")
    args = parser.parse_args(argv)
    try:
        report = run_probe(args.iterations)
        content = json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        print(content, end="")
        return 0 if report["passed"] else 1
    except (OSError, ValueError):
        print("Operational probe failed: invalid input or unavailable output.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

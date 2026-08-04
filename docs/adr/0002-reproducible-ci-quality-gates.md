# ADR 0002: Reproducible CI and quality gates

- Status: Accepted
- Date: 2026-08-04

## Context

The previous CI installed mutable dependency ranges with pip, covered only
Python 3.10-3.12 on a moving Ubuntu label, and had no lint, type, coverage,
security, packaging, clean-install, or composite-action gate. The source
repository's product workflow also referenced example inputs that did not exist.

## Options considered

| Option | Time | Signal and noise | Security and maintainability |
| --- | --- | --- | --- |
| Minimum: tests on one Linux/Python version | Low | Fast but misses packaging, platform and hygiene regressions | Low maintenance; weak release confidence |
| Balanced: frozen uv environment, focused quality job, supported Python matrix, Windows/macOS smoke and action contract | Medium | High signal with one intentional CRITICAL failure asserted in isolation | Audited dependencies, read-only jobs, manageable runtime |
| Enterprise: hermetic builders, signed provenance, policy engine, self-hosted runner tiers and organization-wide enforcement | High | Highest assurance but substantial operational noise for the current product stage | Strongest controls; premature ownership and platform cost |

## Decision

Adopt the balanced option. Pin uv itself and action versions, lock Python
dependencies, use explicit runner images, and separate mandatory CI from the
manual adoption example. Quality gates are formatting, lint, practical type
checking, 85% branch coverage, dependency audit, package metadata validation,
clean wheel installation and CLI smoke. Compatibility follows the declared
Python floor through 3.13, plus Windows and macOS smoke coverage.

The composite-action job proves that LOW is a successful action execution and
that CRITICAL is a deliberate risk-gate failure, not a hidden CI failure. All
jobs use read-only repository permissions, bounded timeouts and lock-derived
caching.

This change does not alter a public runtime contract, so the package remains at
0.1.2. A release version changes when the staged work is promoted, not merely
because CI implementation files changed.

## False positives

Security findings fail closed. Any temporary exception must identify the
advisory, owner, compensating control and expiry. Lint/type exceptions must be
the narrowest possible inline suppression with rationale. Coverage exclusions
cannot be added solely to satisfy the threshold.

## Consequences

- Pull requests receive distinct signals for code quality, compatibility and
  the product action contract.
- Dependency updates must regenerate and review `uv.lock`.
- CI runtime increases because the declared compatibility claim is now tested.
- Python 3.9 cannot run the quality toolchain itself; it remains covered as a
  runtime target in the compatibility job.
- Enterprise provenance and organizational policy enforcement remain future,
  separately reviewed work.

## Rollback

Revert this ADR together with `ci.yml`, the quality configuration in
`pyproject.toml`, `.python-version`, `uv.lock`, `scripts/package_smoke.py`, and
the CI contract tests. Restore the previous manual workflow separately only if
the adoption example must also be rolled back. No branch-protection or
repository-setting rollback is required because this decision changes neither.

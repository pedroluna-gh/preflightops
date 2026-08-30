# ADR 0003: Supported Python security floor

- Status: Accepted
- Date: 2026-08-29

## Context

The universal lockfile retained dependency forks for Python 3.9 even when the
primary quality job ran on Python 3.12. A single-interpreter `pip-audit` could
therefore pass while GitHub correctly reported vulnerabilities in packages
resolved for another declared runtime. Python 3.9 is end-of-life and Python
3.10 is close enough to end-of-life that introducing it into a new enterprise
deployment would create immediate migration and patch-management debt.

## Decision

Raise the package floor to Python 3.11 and support Python 3.11, 3.12 and 3.13.
The compatibility suite must exercise all supported versions. CI and release
workflows must also export the locked CLI and optional web dependency graph for
each supported interpreter and audit each export independently. The stable
`CI / Required` fan-in fails unless every audit succeeds.

Changing the Python floor is a public compatibility change and must ship in a
minor release with release notes. It must not be backported into an existing
tag.

## Consequences

- Vulnerable or stale dependency forks for unsupported interpreters leave the
  lockfile instead of remaining invisible behind environment markers.
- Every supported interpreter receives an explicit vulnerability result.
- Python 3.9 and 3.10 users must upgrade Python before adopting the next release.
- Adding a Python version requires updating compatibility and dependency-audit
  matrices together.

## Rollback

Do not lower the Python floor without a reviewed support and patching plan.
Rollback requires restoring the earlier package metadata, lockfile and CI
matrices together and documenting how vulnerabilities for the restored runtime
will be patched and audited.

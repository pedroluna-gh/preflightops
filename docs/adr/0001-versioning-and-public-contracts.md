# ADR 0001: Versioning and Public Contracts

- Status: Accepted
- Date: 2026-08-04

## Context

Package metadata reported version `0.1.2` while the Python module reported
`0.1.0`. Public inputs and outputs were documented but had no machine-readable
schemas or explicit compatibility policy.

## Options considered

| Option | Benefits | Costs and risks |
| --- | --- | --- |
| Keep duplicate versions and test equality | Smallest patch | Does not remove the source of drift |
| Use `_version.py` plus setuptools dynamic metadata | One source, source-tree friendly, reversible | Small packaging change |
| Derive versions from Git tags with `setuptools-scm` | Strong release automation | New build dependency and more release coupling |

## Decision

Use `preflightops/_version.py` as the single version source. Setuptools reads the
attribute dynamically; `preflightops.__version__`, CLI `--version`, and reports
import the same value.

Adopt Contract Set v1 and JSON Schema draft 2020-12 for existing file inputs and
JSON reports. Schemas allow additional properties to preserve organization-
specific extensions. Adopt the compatibility and deprecation policy in
`docs/COMPATIBILITY.md`.

## Consequences

- Version drift becomes testable and structurally less likely.
- Builds must support setuptools dynamic metadata.
- JSON Schema is a test-only dependency; runtime remains dependency-light.
- Future audit-grade assessment contracts will receive a new explicit schema
  version instead of silently redefining v1.

## Rollback

Restore a literal `project.version` in `pyproject.toml`, restore a literal
`preflightops.__version__`, remove `--version`/report metadata and schemas, and
revert the corresponding contract tests and documentation in the same change.


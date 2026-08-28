# Quality gates

PreflightOps uses one mandatory CI workflow for engineering confidence and a
separate manual workflow for demonstrating product adoption. A CRITICAL product
risk is an expected domain result; it is tested separately from infrastructure,
test, packaging, or dependency failures.

## Required pull-request checks

| Check | Purpose | Failure meaning |
| --- | --- | --- |
| Quality gates | Frozen lock, formatting, lint, types, coverage, dependency audit, build and clean install | The change is not releasable |
| Compatibility (matrix) | Full regression suite on Python 3.9-3.13 and smoke coverage on Linux, Windows and macOS | A declared platform is incompatible |
| Composite action contract | LOW passes; CRITICAL deliberately trips only the configured risk threshold | The public action contract regressed |

No mandatory quality step uses `continue-on-error`. The only tolerated failure
is the deliberately CRITICAL action-contract scenario, immediately followed by
assertions that verify both its domain result and its failed step outcome.

## Reproduce locally

Install uv 0.12.1 and Python 3.12, then run from the repository root:

```bash
uv sync --locked --all-extras --group quality
uv run ruff format --check .
uv run ruff check .
uv run mypy preflightops
uv run pytest --cov=preflightops --cov-report=term-missing --cov-fail-under=85
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file .runtime-requirements.txt
uv export --locked --no-dev --extra app --no-emit-project --format requirements-txt --output-file .dependency-audit.txt
uv run pip-audit --requirement .dependency-audit.txt
uv run python -m build --no-isolation
uv run twine check dist/*
uv run python scripts/package_smoke.py --requirements .runtime-requirements.txt dist
```

The 85% branch-coverage floor is deliberately below the measured 87%+ baseline.
It blocks material regressions while preserving a small margin for platform-
specific branches. Raising it requires tests, not exclusions of production code.

To validate another supported interpreter locally, create a separate uv
environment and run `uv sync --locked --all-extras --no-dev` followed by
`uv run --no-dev pytest`. CI remains the authoritative cross-platform matrix.

## Dependency and false-positive policy

- `uv.lock` is authoritative. CI uses frozen resolution and fails on drift.
- Runtime and optional application dependencies are audited from an export of
  that lockfile; the editable project itself is intentionally omitted. The clean
  wheel smoke installs only mandatory runtime dependencies, matching the CLI.
- A vulnerability finding fails the gate. Suppression requires a time-bounded,
  reviewed entry that names the advisory, affected path, compensating control,
  owner and expiry date. There are currently no suppressions.
- Lint and type-check suppressions must be narrow, inline and explain why the
  finding is false. Broad file or job exclusions are not accepted to make CI green.
- Cache keys derive from `uv.lock`; virtual environments and build outputs are
  never restored from cache.

## Permissions, diagnosis and rollback

Both workflows have only `contents: read`. CI has bounded timeouts, cancels stale
runs for the same pull request, and never writes comments, releases or repository
settings.

When a run fails, classify it first as quality, compatibility, packaging,
dependency/security, action execution, or expected risk-threshold behavior. Do
not relabel an infrastructure or parse failure as CRITICAL product risk.

Rollback is one atomic revert of the CI workflow, quality configuration,
lockfile, helper script and contract tests. The manual adoption workflow can be
reverted independently because it is not a required pull-request signal.


## Required check contract

Repository protection requires the stable `CI / Required` check. This fan-in job succeeds only when the quality, compatibility, and composite-action contract jobs all succeed. Matrix labels and runner versions may evolve without changing the protected check contract.

Treat required check names as a public release-management API. A rename or replacement must use a two-phase migration: publish and validate the new check first, then update the ruleset, and remove the previous requirement only after every open pull request has a reported replacement check. Never leave a ruleset waiting for a check that no active workflow emits.

`tests/test_ci_contract.py` enforces the stable job name, dependencies, always-run behavior, and fan-in assertions.

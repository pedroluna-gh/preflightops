# Quality gates

PreflightOps uses one mandatory CI workflow for engineering confidence and a
separate manual workflow for demonstrating product adoption. A CRITICAL product
risk is an expected domain result; it is tested separately from infrastructure,
test, packaging, or dependency failures.

## Required pull-request checks

| Check | Purpose | Failure meaning |
| --- | --- | --- |
| Quality gates | Frozen lock, formatting, lint, types, coverage, build and clean install | The change is not releasable |
| Compatibility (matrix) | Full regression suite on Python 3.11-3.13 and smoke coverage on Linux, Windows and macOS | A declared platform is incompatible |
| Dependency audit (matrix) | Audit both the locked runtime/web graph and the complete test/build toolchain independently for Python 3.11, 3.12 and 3.13 | A supported runtime or delivery tool resolves a known vulnerability |
| Composite action contract | LOW passes; CRITICAL deliberately trips only the configured risk threshold | The public action contract regressed |
| Evidence contract | DSSE/Ed25519 signature, schemas, policy/input/identity pins, tamper and replay rejection | Authenticated evidence is unsafe or incompatible |

Security controls run in a separate `Security` workflow so their permissions
remain isolated: CodeQL on pushes/pull requests/schedule, and dependency review
on pull requests. OpenSSF Scorecard continuously evaluates repository and
supply-chain posture. Enterprise rulesets require `CI / Required` and
`Security / CodeQL`; dependency review is required whenever the GitHub plan and
repository settings support it.

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
for py in 3.11 3.12 3.13; do
  uv export --python "$py" --locked --no-dev --extra app --no-emit-project --format requirements-txt --output-file ".dependency-audit-runtime-$py.txt"
  uv export --python "$py" --locked --all-groups --all-extras --no-emit-project --format requirements-txt --output-file ".dependency-audit-toolchain-$py.txt"
  uv tool run --python "$py" pip-audit --requirement ".dependency-audit-runtime-$py.txt"
  uv tool run --python "$py" pip-audit --requirement ".dependency-audit-toolchain-$py.txt"
done
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
- Runtime/application dependencies and the complete test/build toolchain are
  audited from separate interpreter-specific exports for every supported Python
  version; the editable project itself is intentionally omitted. This prevents
  a safe runtime graph from masking a vulnerable delivery dependency. The clean
  wheel smoke installs only mandatory runtime dependencies, matching the CLI.
- A vulnerability finding fails the gate. Suppression requires a time-bounded,
  reviewed entry that names the advisory, affected path, compensating control,
  owner and expiry date. There are currently no suppressions.
- Lint and type-check suppressions must be narrow, inline and explain why the
  finding is false. Broad file or job exclusions are not accepted to make CI green.
- Cache keys derive from `uv.lock`; virtual environments and build outputs are
  never restored from cache.

## Permissions, diagnosis and rollback

Assessment and CI workflows have only `contents: read`. Security workflows scope
`security-events: write` to jobs that publish SARIF. The tag-only release job has
the isolated write/OIDC permissions required to publish and attest a release.
All jobs have bounded timeouts and checkout steps disable persisted credentials.

When a run fails, classify it first as quality, compatibility, packaging,
dependency/security, action execution, or expected risk-threshold behavior. Do
not relabel an infrastructure or parse failure as CRITICAL product risk.

Rollback is one atomic revert of the CI workflow, quality configuration,
lockfile, helper script and contract tests. The manual adoption workflow can be
reverted independently because it is not a required pull-request signal.


## Required check contract

Repository protection requires the stable `CI / Required` check. This fan-in job succeeds only when quality, compatibility, every supported-runtime dependency audit, and the composite-action contract all succeed. Matrix labels and runner versions may evolve without changing the protected check contract.

Treat required check names as a public release-management API. A rename or replacement must use a two-phase migration: publish and validate the new check first, then update the ruleset, and remove the previous requirement only after every open pull request has a reported replacement check. Never leave a ruleset waiting for a check that no active workflow emits.

`tests/test_ci_contract.py` enforces the stable job name, dependencies, always-run behavior, and fan-in assertions.


# Release management

## Release contract

Releases are produced only by `.github/workflows/release.yml` from a protected
semantic-version tag whose value exactly matches `preflightops.__version__`.
The workflow re-runs quality/security gates, verifies two independent builds, creates
an SPDX SBOM and SHA-256 manifest, attests the bundle and publishes those exact
files to GitHub Releases.

## Reproducible packaging

`python scripts/release_build.py --output dist --epoch 1704067200` copies
explicit packaging inputs (`pyproject.toml`, README, LICENSE, package and tests)
to two clean temporary directories, excluding generated metadata and caches.
Each build produces an sdist, canonicalizes archive metadata, and builds its
wheel from that canonical sdist. Payload bytes are not normalized or rewritten.
Both final distributions must match byte for byte before one bundle is promoted.
An existing output directory is rejected rather than overwritten.

The fixed epoch is a packaging convention (2024-01-01 UTC), not a claim about
source commit or release time. Reproduction requires identical source bytes,
Python, OS and locked build tools. Cross-platform equivalence is not claimed.
`reproducible-build.json` records tool versions and artifact hashes; it is a
local reproducibility statement, not authenticated provenance. GitHub release
attestations separately establish the build workflow identity.

CI and release run the same builder. Twine checks only the wheel and sdist.
The clean-wheel smoke installs hash-pinned dependencies, runs outside the
checkout, and verifies LOW/CRITICAL exit codes and all four legacy reports.
Any build mismatch or smoke failure blocks promotion; no findings are ignored.

## Offline bundle integrity

The bundle includes two complementary SBOMs: the existing Syft-generated SPDX
inventory and `preflightops-lock.cdx.json`, exported offline by pinned uv 0.12.1
with every dependency group and extra. `scripts/lock_sbom.py` compares normalized
package names and exact versions against all registry entries in uv.lock,
rejecting missing/extra/duplicate identities and unsupported local dependencies.
This inventory is a cross-platform superset, not the list installed on one host.
uv labels this exporter experimental; contract tests and the pinned version
bound that risk. It does not supply license conclusions. SPDX/license review
remains separate, and neither SBOM timestamp is a reproducible artifact claim.

Syft is pinned to v1.52.0. `scripts/sbom_input.py` stages only the lockfile,
project metadata, wheel and its expanded .dist-info metadata; scanning the
developer checkout or credentials directories is prohibited. SPDX may contain
an additional UNKNOWN-version project record because the source version is
dynamic; the gate separately requires the exact built wheel version. Unknown
license conclusions remain visible and require review, not silent approval.

After SBOM generation, `python scripts/release_bundle.py create dist` produces
the SHA256SUMS manifest without overwriting an existing one. Before attestation,
`python scripts/release_bundle.py verify dist` requires exactly one matching
PreflightOps wheel/sdist pair, both SBOM inventories and reproducibility record.
It rejects missing, extra, empty or altered files, unsafe names, subdirectories,
symlinks and duplicate/oversized checksum manifests. It makes no network calls.
Run verification on a quiescent directory not writable by untrusted processes.

This check proves integrity relative to the supplied manifest, not authenticity,
SBOM completeness or correctness of the claimed build. An attacker replacing
both files and manifest can pass hashes; verify the GitHub attestation against
the expected repository/workflow identity through a separately trusted channel.
Do not use a verifier obtained only from the untrusted bundle as the trust root.

Repository administrators must configure:

1. A `main` ruleset requiring pull requests, code-owner review, conversation
   resolution and `CI / Required` plus `Security / CodeQL`.
2. A tag ruleset for `v*` preventing update/delete and restricting creation.
3. A `release` environment with independent required reviewers and self-review
   disabled where the plan supports it.
4. GitHub private vulnerability reporting and secret scanning.

Settings are verified after configuration; documentation is not evidence that a
ruleset exists.

### Current single-maintainer operating mode (2026-09-16)

The owner explicitly selected `pedroluna-gh` as the required release reviewer
and authorized self-review while the project has one maintainer. The configured
release environment requires that manual approval, retains its 15-minute wait
and `v*` tag restriction, and disallows administrator bypass of environment
rules. `Prevent self-review` is disabled: the initiating maintainer can approve.
This is manual owner approval, **not independent review or separation of duties**.
It does not change scanner failures, integrity gates or automated CAB boundaries.

This documented operating limitation supersedes the independent-review target
above for the current single-maintainer phase only. Review it before each release
and when a second maintainer joins; then assign another authorized reviewer and
enable prevention of self-review. No release is claimed independently approved
under the single-maintainer arrangement. Tag rules retain a separate owner bypass;
the environment setting does not remove that residual privilege.

Inspection on 2026-09-23 also confirmed the active `main` ruleset has no bypass
actors, requires a PR, signed commits, linear history, resolved conversations,
an up-to-date branch and the `Required` check, plus CodeQL scanning (high-or-higher
security alerts and error-level findings). It requires zero approving reviews
and does not require Code Owner approval. The independent-review target above
is therefore not achieved on main either; automated gates are not human review.
No branch protections were changed during this inspection.

## Promotion

1. Merge a compatible, green release PR.
2. Confirm version, changelog, support matrix and rollback version.
3. Create the protected tag on the reviewed `main` commit.
4. Approve the `release` environment.
5. Verify the published checksum and attestation:

```bash
gh attestation verify preflightops-<version>-py3-none-any.whl \
  --repo pedroluna-gh/preflightops
sha256sum --check SHA256SUMS
```

6. Run a clean-install smoke and the LOW/CRITICAL Action contract against the tag.

## Rollback and revocation

Consumers pin immutable release tags. Rollback means restoring the last
known-good tag in the consuming workflow; never retarget or rewrite a published
tag. A compromised release is documented, removed from recommended usage and
replaced by a new patch release. Evidence and advisories identify affected
versions, mitigation and verification steps.

## Release approval checklist

The license review in `security/license-review.json` is currently pending;
see `docs/LICENSE_REVIEW.md` for collected evidence and unresolved items.
CI may validate a pending tracking record without authorizing release. The
publishing step separately requires `scripts/license_review.py ... --publishing`,
which rejects pending/rejected, stale-lock, future-dated or expired approval.
This lets development and artifact verification proceed while blocking an
unreviewed public release. Do not change the status merely to pass this gate.

- Record reviewed source commit, version, changelog and migration notes.
- Require green quality, security, dependency and reproducibility gates on
  the exact candidate. Review the SBOM including optional/build dependencies,
  license obligations, unknown entries and unresolved findings.
- Validate the exception registry at current UTC; record each unresolved issue
  and mitigation. A valid record never turns a scanner failure into success.
- Verify protected tag/release environment settings and actual approver identity.
  Do not infer protection from workflow names. Where signed tags are available,
  use an authorized maintainer signing identity; never generate a release key
  as a build side effect. Record unavailable signing controls explicitly.
- Confirm artifact checksums, authenticated attestation identity and clean-install
  evidence for the exact bundle to publish; retain it without rebuilding.
- Identify affected supported versions, patch/backport status and EOL notices.
- Name the previous approved immutable release and consumer pin as rollback.
  Test its bundle verification and clean-install before enabling a canary.
- Abort rollout on integrity, install, risk-exit or report regressions. Restore
  the recorded consumer pin and approved policy/trust context. Preserve both
  candidate and previous evidence; never rewrite a published tag.

Stage 15 tooling is additive and does not change assessment contracts or require
consumer migration. Existing releases are not retroactively claimed reproducible
or attested; those assertions require their own evidence. No new version is
published merely by merging these gates.

### Local rollback rehearsal

The 2026-09-23 rehearsal installed the candidate wheel and then the retained
stage-14 wheel in separate empty environments with offline, hash-pinned runtime
dependencies. Both passed version/import checks, LOW exit 0, CRITICAL exit 1,
and Markdown/JSON/HTML/PR-summary output checks outside the checkout. The retained
wheel SHA-256 was
`c9e3b2f1ba8abdb2c151de01814064c338fe3e4fee7e13d8aa6d4ae1834ed210`.

This exercises returning to the prior local artifact without replacing either
artifact. It is not a production rollback, an authenticated release rehearsal,
or proof that the prior wheel has the new bundle metadata. Before an actual
rollout, repeat the checklist against the previous approved release and its
trusted checksums/attestation; do not manufacture a new manifest as its trust root.

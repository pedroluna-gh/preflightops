# Release management

## Release contract

Releases are produced only by `.github/workflows/release.yml` from a protected
semantic-version tag whose value exactly matches `preflightops.__version__`.
The workflow re-runs quality/security gates, builds distributions once, creates
an SPDX SBOM and SHA-256 manifest, attests the bundle and publishes those exact
files to GitHub Releases.

Repository administrators must configure:

1. A `main` ruleset requiring pull requests, code-owner review, conversation
   resolution and `CI / Required` plus `Security / CodeQL`.
2. A tag ruleset for `v*` preventing update/delete and restricting creation.
3. A `release` environment with independent required reviewers and self-review
   disabled where the plan supports it.
4. GitHub private vulnerability reporting and secret scanning.

Settings are verified after configuration; documentation is not evidence that a
ruleset exists.

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

# License review status

Status: **pending**, not cleared for release publication. Owner: `pedroluna-gh`.
This is a technical inventory/review process, not a legal compliance certificate.

The exact LF-normalized uv.lock SHA-256 is recorded in
`security/license-review.json`. CI verifies this binding and the record shape;
the release workflow additionally requires an explicit approved, unexpired
review (maximum 90 days). A changed lock invalidates prior review. A pending
record is permitted during development, never for publishing a release.

## Evidence collected on 2026-09-18

- Complete lock SBOM: 103 external package/version identities, including extras,
  build/test/audit tooling and alternative-platform dependencies.
- Syft SPDX over bounded inputs: lock packages found; built PreflightOps 0.4.2
  metadata declares MIT. Lock-only dependency licenses remain NOASSERTION.
- Installed Python 3.12 Windows environment provides matching metadata for 97
  of the 103 locked identities. Missing/different identities: backports-tarfile
  1.2.0, importlib-metadata 9.0.1, jeepney 0.9.0, numpy 2.4.6,
  secretstorage 3.5.0 and zipp 4.1.0. These are not treated as license-free.
- Some metadata uses legacy free-text licenses or generic BSD classifiers;
  these cannot be silently converted into precise SPDX expressions.
- docutils 0.23 advertises multiple classifiers including public domain, BSD
  and GPL. Review its actual distributed notices and scope before deciding;
  the classifier list alone does not establish the license for every file.

## Before approval

1. Review exact locked distributions/notices, including missing-platform packages
   and bundled code. Preserve identifiers, hashes and notice references.
2. Resolve unknown/ambiguous licenses and distribution obligations; document
   deviations using the security exception process without suppressing scanners.
3. Record the human disposition and evidence in a reviewed PR. Set status,
   reviewed_at and expires_at explicitly only after completing review.
4. Run the publication gate against the same lock and retain both SBOMs/notices.

The record is not a signature: reviewed repository history and actual owner
approval establish authority. Single-maintainer approval is not independent
review. No approval has been fabricated to make a pipeline green.

# Enterprise Definition of Done

A change is complete only when all applicable statements are true.

## Product and contracts

- Outcome and non-goals are documented.
- Public contracts remain compatible or a tested migration/dual-read exists.
- Offline behavior and CAB/ITSM authority boundaries remain intact.
- Failure modes distinguish product risk from tool/integration failure.

## Security and privacy

- Threat-model delta and least-privilege permissions were reviewed.
- No credential or restricted data is added to code, fixtures, logs or evidence.
- Dependency, SAST and vulnerability gates pass.
- External destinations and writes are allowlisted, previewable and verified.
- Any exception names advisory/rule, owner, approver, compensating control and expiry.

## Engineering quality

- Unit, contract, negative and regression tests cover the change.
- Formatting, lint, types, branch coverage, packaging and clean install pass.
- Cross-platform impact and performance budget are evaluated.
- Documentation and examples use sanitized data.

## Release and operations

- Canary scope, abort criteria, owner and rollback are documented.
- Release artifact is built once in protected CI, checksummed, accompanied by an
  SBOM and cryptographic attestation, and independently verifiable.
- Upgrade/rollback and operator runbooks are current.
- Required checks and rulesets are migrated in two phases when renamed.

Documentation-only changes may mark non-applicable items explicitly; they do not
silently bypass security or compatibility gates.

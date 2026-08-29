# Evidence Contract v2

Evidence Contract v2 makes a PreflightOps assessment portable and
cryptographically authenticatable without giving PreflightOps CAB authority.
It is an in-toto Statement inside a DSSE envelope, signed with Ed25519 and
verified offline against an explicitly trusted public key.

## Trust and authority model

- The deterministic assessment remains the technical result.
- The signature proves that the holder of the configured private key produced
  the exact envelope. Trust comes from the verifier's public-key distribution,
  not from a self-declared actor field.
- Repository, commit, workflow, run, actor, policy digest and input digests are
  signed claims. Enterprise consumers should pin the claims that matter to
  their control using the verification flags.
- ServiceNow or Jira remains the Change of Record. CAB, Change Management and
  authorized approvers retain approval, scheduling and closure authority.
- An evidence signature is not an approval and cannot change workflow state.

## Generate signed evidence

Generate the normal machine-readable assessment first. Then sign it. The
private key may be an unencrypted Ed25519 PEM file or the value/path in
`PREFLIGHTOPS_EVIDENCE_PRIVATE_KEY`. Do not pass private-key material on a
command line or store it in the repository.

```bash
preflightops \
  --services services.yaml \
  --change change.yaml \
  --policy policy.yaml \
  --json-output assessment.json \
  --output report.md

preflightops evidence generate \
  --assessment assessment.json \
  --change change.yaml \
  --policy policy.yaml \
  --input services=services.yaml \
  --input change=change.yaml \
  --input policy=policy.yaml \
  --output preflightops-evidence-v2.dsse.json \
  --legacy-output preflightops-evidence-v1.json \
  --classification internal
```

`--legacy-output` is the dual-output migration path. It preserves the existing
ServiceNow evidence v1 package while new consumers adopt the signed v2
envelope. Omitting it does not alter the v1 ServiceNow connector default.

## Verify offline and fail closed

The public key may be supplied by file or through
`PREFLIGHTOPS_EVIDENCE_PUBLIC_KEY`. A production verifier should pin policy and
execution identity, not merely check that *some* key signed the document.

```bash
preflightops evidence verify \
  --evidence preflightops-evidence-v2.dsse.json \
  --public-key trusted-preflightops-ed25519.pub.pem \
  --trusted-policy-digest sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --expected-repository acme/payments-api \
  --expected-commit "$GITHUB_SHA" \
  --expected-workflow "PreflightOps enterprise gate" \
  --expected-input services=services.yaml \
  --expected-input change=change.yaml \
  --max-age-seconds 3600 \
  --output evidence-verification.json
```

Exit codes are `0` for verified evidence, `3` for a cryptographic/trust-policy
rejection, and `2` for invalid input, key or file handling. The result file is
machine-readable when verification reaches a verdict.

## Signed content

The predicate includes organization, repository, commit, ref, workflow, run,
attempt, actor, service, environment, external change id, product version,
policy digest, assessment digest, named input digests, timestamp, classification
and the negative authority contract: no CAB approval and no workflow-state
write.

The envelope is limited to 1 MiB. Secret-like keys are removed, strings,
collections and nesting are bounded, and raw IaC/change input content is not
embedded. A caller must still classify the output and apply retention from
`DATA_GOVERNANCE.md`.

## Key lifecycle

For a pilot, keep the Ed25519 private key in a protected CI secret or HSM-backed
secret broker and expose it only to the protected evidence job. Distribute the
public key through an independently controlled repository or trust bundle.

For enterprise rollout:

1. assign key ownership to Security/Platform, separate from application teams;
2. record key id, owner, purpose, issuance, activation, expiry and revocation;
3. overlap old/new public keys during rotation without sharing private keys;
4. revoke on suspected exposure and reject evidence after the incident cutoff;
5. prefer short-lived keyless identity once its identity and transparency model
   has been approved by the organization.

The current Ed25519 mode is intentionally offline and portable. A later minor
contract revision can add Sigstore bundles without changing the signed v2
predicate.

## Compatibility and rollback

- Contract Set v1 is unchanged.
- Existing CLI assessment invocations and ServiceNow v1 attachments behave as
  before unless v2 output is explicitly requested.
- Consumers must not treat v1 hashes as signatures.
- Roll back by disabling v2 generation and continuing v1 output. Do not accept
  unverifiable v2 evidence as if it were v1.
- Retain dual output for at least the v0.6 compatibility window and remove v1
  only through the documented breaking-change process.

## Required negative tests

The shipped suite rejects a modified payload byte, a different signing key, an
untrusted policy digest, changed input content, wrong repository/commit/workflow
claims and evidence outside the accepted freshness window. These checks are
part of the public security contract, not presentation-only tests.

# Policy governance and verified exceptions

Policy Bundle v2 turns organizational risk rules into signed, diffable,
context-aware input while preserving the authority boundary: PreflightOps
recommends; CAB, Change Management, ServiceNow, or Jira decides.

## Contracts and trust

- `schemas/policy-bundle-v2.schema.json` defines the hierarchical policy.
- `schemas/waiver-contract-v1.schema.json` defines a scoped exception.
- Active policies require an Ed25519 signature and a separately trusted public
  key. Drafts may be linted, diffed, and simulated but cannot drive an
  assessment.
- Waivers require a different requester and approver, an active time window,
  exact policy digest, contextual scope, reason, evidence, compensating
  controls, and an independently trusted Ed25519 signature.
- Signatures authenticate the governance document; enterprise authorization
  still depends on protected key custody, CODEOWNERS/rulesets, and the named
  external authority.

Policy validation, signature failure, and overlay conflicts always fail closed.
Each bundle explicitly selects open or closed handling for unavailable
non-policy evidence. No policy default can approve a change.

## Hierarchy and precedence

The `base` policy is applied first. Matching overlays are ordered by ascending
`priority`, then stable `id`. Context fields are `environment`, `tier`,
`change_class` (`normal`, `standard`, or `emergency`) and technical
`change_type`. Two matching overlays at the same priority cannot assign
different values to the same field. Such ambiguity fails closed.

`mandatory_controls` must have a base weight. No overlay may lower that weight.
Emergency classification is context only: it does not bypass policy and does
not authorize break-glass. External Change Management owns emergency approval
and post-implementation review.

The resolved report records the policy digest, owner, context, and full overlay
lineage so a historical assessment can be reproduced without mutating old
results.

## Draft, diff, simulation, activation

Start from `policy-packs/enterprise-example-v2.yaml`:

```bash
preflightops policy lint \
  --policy policy-packs/enterprise-example-v2.yaml \
  --draft

preflightops policy diff \
  --base policy-v2-current.yaml \
  --candidate policy-v2-candidate.yaml \
  --context examples/policy-context-production.yaml \
  --output policy-diff.json

preflightops policy simulate \
  --base policy-v2-current.yaml \
  --candidate policy-v2-candidate.yaml \
  --services examples/services-high-risk.yaml \
  --change examples/change-high-risk.yaml \
  --output policy-simulation.json
```

Diff and simulation are explicitly non-authoritative. They report weakening,
score/level delta, candidate digest, and `automatic_approval: false`.

After independent review, sign the exact candidate offline. The private key is
read only from `PREFLIGHTOPS_POLICY_PRIVATE_KEY`; never pass it as a CLI or
Action input.

```bash
preflightops policy sign \
  --policy policy-v2-candidate.yaml \
  --output policy-v2-active.yaml \
  --key-id change-governance-2026-01

preflightops policy lint \
  --policy policy-v2-active.yaml \
  --public-key trusted-policy-ed25519.pub.pem
```

Use the active policy in an assessment:

```bash
preflightops \
  --services services.yaml \
  --change change.yaml \
  --policy policy-v2-active.yaml \
  --policy-public-key trusted-policy-ed25519.pub.pem \
  --json-output report.json
```

Rollback means restoring the last reviewed active bundle and its matching
public-key trust pin. Historical reports retain their original policy digest
and lineage; never edit an activated bundle in place.

## Waiver lifecycle

Copy `examples/waiver-example-v1.draft.yaml`, replace its demo policy digest and
scope, and obtain review from an identity other than the requester. Sign with
`PREFLIGHTOPS_WAIVER_PRIVATE_KEY`:

```bash
preflightops waiver sign \
  --waiver waiver-draft.yaml \
  --output waiver-signed.yaml \
  --key-id independent-risk-2026-01
```

An assessment verifies the waiver offline:

```bash
preflightops ... \
  --policy policy-v2-active.yaml \
  --policy-public-key trusted-policy.pub.pem \
  --waiver waiver-signed.yaml \
  --waiver-public-key trusted-waiver.pub.pem
```

A valid waiver annotates covered findings and the decision record. It never
changes the technical score, suppresses a finding, turns a failing gate green,
or claims human approval. Expired, incomplete, wrong-policy, wrong-context,
self-approved, malformed, or incorrectly signed waivers fail closed.

## Enterprise rollout gates

1. Lint every draft and require independent policy ownership.
2. Diff every affected context, including normal, standard, and emergency.
3. Simulate against a calibrated historical corpus in report-only mode.
4. Sign in a protected workflow after reviewed approval evidence exists.
5. Canary the active digest in five repositories; alert on signature,
   resolution, or false-positive regressions.
6. Expand only after an owner accepts calibration evidence and rollback has
   been exercised.

The repository contains no production signing key, regulatory assertion, or
autonomous approval path.

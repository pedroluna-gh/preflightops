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

When a simulation uses an active baseline or candidate, supply its separately
trusted key with `--base-public-key` or `--candidate-public-key`. Each active
document is verified independently; both options fall back to
`PREFLIGHTOPS_POLICY_PUBLIC_KEY` when omitted. Unsigned drafts do not require a
key and are never activated by simulation. A wrong or missing key fails the
command without writing a new simulation result.

The optional simulation argument `--at 2026-08-28T12:00:00Z` records the explicit
validation instant as `evaluated_at`, normalized to UTC. Simulation deliberately
permits structurally valid future or expired policies for comparison: this
timestamp is not an assertion that the policy is currently deployable. Active
assessment validation still enforces the effective window. Omitting `--at`
preserves the existing simulation output shape.

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

## Stage 14 runtime safeguards

Governance documents are limited to 1 MiB, 32 nesting levels and 20,000 value
nodes. Duplicate keys, YAML aliases/merge keys, non-string keys, implicit YAML
dates, non-finite numbers and non-JSON values are rejected. Quote timestamps.
The main policy-file loader uses the same boundary, including legacy v1 files;
valid v1 packs retain their scoring and exit semantics. Closed v2 object fields
are enforced at runtime; previously ignored misspellings must be corrected.
Parser errors do not echo source payloads. Trusted policy authors must still
exclude secrets from descriptions, aliases and references.

`policy diff` and `policy simulate` reject changed content under the same policy
name/version. Draft-to-active signing alone is not a content-version change.
Key custody and reviewed activation are external controls: an isolated signing
operation cannot prove that no other document has reused the version. Require
the diff against the approved predecessor in the protected release workflow.

For an authenticated v2 assessment, absent inventory that is required by the
resolved monitoring policy or explicit monitor references produces
`decision_record.failure_handling` (`governance-failure-v1`). Closed mode stops
the CLI with exit 2 after normal reports are written and before ticket generation
or live integrations. Open mode continues informatively without changing scores,
findings or the normal CRITICAL exit code. An empty but supplied inventory is
available evidence of insufficient coverage, not unavailable evidence. Neither
case proves live monitoring coverage. Policy validation, signature and context
conflicts continue to raise errors before assessment; malformed evidence is not
silently converted to availability or PASS. Other provider callers can use the
pure `evaluate_failure_modes` function with an authenticated resolved policy;
unknown error categories always stop and are recorded without raw error text.

Use `--governance-at <RFC3339>` on the main CLI for an offline historical replay.
One normalized UTC instant validates both policy and waivers and is included in
the v2 decision record. Historical replay refuses live ServiceNow/Jira requests;
dry-run remains possible. Without this option the CLI captures current UTC once.
Retain exact original inputs, trusted public keys, versioned distribution and
digests in access-controlled storage. Waiver annotations preserve failure
dispositions and evaluation time; no exception removes a policy stop.

Rollback is selection of the prior approved bundle and distribution, not editing
old reports. Replaying an expired bundle at its original instant is audit-only;
it does not make that bundle valid for a current deployment. No live production
rollout, regulatory certification or external identity attestation is claimed.

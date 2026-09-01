# Assessment Contract v1 and Trust Kernel

Assessment Contract v1 is the deterministic, machine-readable record of one
PreflightOps technical assessment. It complements the legacy risk report and
can be carried as the `assessment` inside the existing signed Evidence Contract
v2. It does not replace legacy JSON, change an external workflow state, or grant
approval.

## Contract boundary

The public schema is
[`assessment-contract-v1.schema.json`](../schemas/assessment-contract-v1.schema.json).
The runtime API is in `preflightops.assessment`:

- `AssessmentContext`, `PolicyIdentity`, and `InputDigest` define source and run
  identity without embedding input content;
- `ControlObservation`, `WaiverReference`, and `HumanDecision` are immutable
  input models;
- `TrustKernel.evaluate()` creates and strictly validates a native contract;
- `adapt_legacy_assessment()` creates the same contract from the existing risk
  result without modifying that result;
- `validate_assessment_v1()` enforces shape, cross-references, integrity, and
  fail-closed status invariants;
- `serialize_assessment_v1()` emits canonical UTF-8 JSON with one trailing
  newline.

There are no clock, random, network, provider, ServiceNow, Zabbix, or GCP calls
inside the module. Timestamps, policy identity, input digests, and context must
be supplied by the caller.

## Field semantics

| Field | Meaning |
| --- | --- |
| `schema_version` | Contract schema, fixed to `1.0` |
| `assessment_id` | Deterministic SHA-256 URN of the semantic contract |
| `change_id`, `timestamp` | External change identity and explicit UTC assessment time |
| `context` | Actor, run/attempt, repository, PR, commit, and pipeline identity |
| `producer`, `policy`, `inputs` | PreflightOps version plus pinned policy and input digests |
| `controls`, `evidence` | Executed controls and content-free provenance references |
| `scores.risk` | Exposure/severity of the proposed change |
| `scores.confidence` | Coverage by fresh, digest-pinned evidence |
| `verdict` | Technical result; never an approval |
| `blockers`, `warnings`, `passed_controls`, `errors` | Explicit status projections for consumers |
| `waivers` | Minimal verified exception references; risk and status are preserved |
| `recommendation` | Technical recommendation with `grants_approval: false` |
| `human_decision` | Independent external decision, defaulting to `NOT_RECORDED` |
| `compatibility` | Source contract and proof that legacy output remains preserved |
| `data`, `integrity` | Privacy profile and canonical semantic digest |

## Trust invariants

The status transition is deliberately asymmetric:

| Observed state | Evidence condition | Contract state |
| --- | --- | --- |
| `PASS` | Fresh and SHA-256 pinned | `PASS` |
| `PASS` | Missing, stale, or validity unknown | `UNKNOWN` plus `PASS_DOWNGRADED` |
| `PASS` | Collected after assessment timestamp | `ERROR` |
| `FAIL` | Any | `FAIL` |
| `ERROR` | Any | `ERROR` |
| `UNKNOWN` | Any | `UNKNOWN` |

Consequently, `ERROR` and `UNKNOWN` can never appear in `passed_controls`.
Either state produces `INDETERMINATE` and a `DO_NOT_PROCEED` technical
recommendation. `FAIL` remains a failure even when a verified waiver references
the control.

Risk and confidence are independent. Risk is supplied by the versioned risk
policy. Confidence is the percentage of control observations that are either
`PASS` or `FAIL` and have fresh digest-pinned evidence. A high-risk assessment
may have high confidence; a low-risk assessment may be indeterminate because
its evidence is incomplete.

## Determinism and integrity

The kernel sorts inputs, controls, evidence, issues, waiver references, links,
and passed-control identifiers. Canonical JSON uses UTF-8, sorted keys, compact
separators, and no platform-dependent whitespace. The semantic digest covers
every field except `assessment_id` and `integrity`; both then carry that digest.
Control execution and evidence IDs use the same canonical hashing rule over
their own semantic records.

Determinism includes time: the caller must reuse the same explicit UTC
`timestamp`, `collected_at`, and `valid_until` values. Reading the wall clock
inside an assessment is intentionally unsupported.

## Privacy and data minimization

- Raw input content, credentials, secret values, waiver justification, and full
  provider payloads are not contract fields.
- `InputDigest` accepts only caller-supplied SHA-256 values. Produce those from
  an approved non-sensitive artifact or redacted semantic projection. Do not
  hash passwords, tokens, small-domain personal data, or raw restricted content;
  a bare digest does not prevent correlation or dictionary attacks.
- The legacy adapter hashes a narrow allowlisted metadata projection for policy
  fallback and control evidence. Arbitrary legacy fields are not copied.
- Inline credential patterns in bounded summaries are deterministically
  replaced with `[redacted]`.
- Evidence URLs must use HTTPS and cannot contain userinfo, query strings, or
  fragments, preventing common token-bearing URL forms.
- Validation errors identify field paths and invariant failures without echoing
  rejected values.

## Legacy migration

1. Continue generating and distributing `risk-report-v1` exactly as before.
2. Pin the policy and calculate approved SHA-256 digests for each logical input.
3. Build an `AssessmentContext` from the immutable CI/run identity and call
   `adapt_legacy_assessment()` with an explicit UTC timestamp.
4. Validate the v1 contract against the public schema and retain golden bytes
   for a representative assessment.
5. Optionally carry the contract inside Evidence Contract v2 for signature and
   external trust verification.
6. Migrate consumers one at a time. Consumers must not interpret
   `READY_FOR_HUMAN_REVIEW` or recommendation `PROCEED` as human approval.

The adapter preserves the legacy risk score, risk level, recommendation text,
negative findings, missing controls, monitoring status, verified waiver
references, and explicit errors. It never mutates the supplied mapping. Because
legacy results do not enumerate every successful control, their confidence is
capped at 80.

## Rollback

Disable the new adapter/kernel call and continue publishing the legacy JSON and
Evidence Contract v2. The new contract is additive and has no external writes,
so rollback requires no data repair. Do not delete previously retained v1
assessment artifacts; mark their consumer path inactive and preserve them for
audit retention. Reintroducing the contract later with identical inputs will
reproduce the same bytes.



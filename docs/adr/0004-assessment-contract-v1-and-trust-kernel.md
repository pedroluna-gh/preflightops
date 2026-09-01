# ADR 0004: Assessment Contract v1 and deterministic Trust Kernel

- Status: Accepted
- Date: 2026-08-31

## Context

The legacy risk report is useful for operators but does not identify one
assessment reproducibly, inventory executed controls, measure evidence quality,
or distinguish a technical recommendation from an external human decision. The
new contract must remain offline, preserve all legacy outputs, and fail closed
when evidence is missing, stale, unknown, or erroneous.

## Options considered

| Design | Benefits | Costs and risks |
| --- | --- | --- |
| Conservative: strict wrapper around the legacy report | Smallest change and simplest migration | Carries forward ambiguous control coverage; risk and evidence confidence remain coupled; weak audit semantics |
| Balanced: immutable models, pure Trust Kernel, strict schema, canonical serialization, and explicit legacy adapter | Deterministic and testable; separates risk, confidence, recommendation, and human decision; additive and dependency-free | More contract fields and validation code; callers must supply timestamps and safe input digests |
| Enterprise: signed event graph with pluggable evidence providers and decision ledger | Strong multi-system lineage and long-term extensibility | Premature provider/ledger coupling, larger operational surface, and scope overlap with later stages |

## Decision

Adopt the balanced design. `preflightops.assessment` contains immutable input
models and a pure `TrustKernel`. It has no clock, random, filesystem, or network
dependency: callers provide the timestamp, execution context, policy identity,
input digests, and control observations.

The kernel emits `assessment-contract-v1.schema.json`, sorts unordered
collections, serializes with `preflightops-canonical-json-v1`, and derives both
the assessment URN and integrity digest from the complete semantic document
before the two self-referential fields are added. Evidence and control execution
URNs are derived from their canonical semantic records.

The v1 adapter consumes a legacy risk result without mutating it. Legacy
negative findings remain failures, explicit legacy errors remain errors, and
absence of an enumerated control set becomes unknown rather than pass. Legacy
outputs remain independently available and unchanged.

## Invariants

- `ERROR` and `UNKNOWN` are never promoted to `PASS`.
- Requested `PASS` becomes `UNKNOWN` unless its evidence is fresh and
  digest-pinned; evidence collected in the future becomes `ERROR`.
- A waiver records an exception reference but never changes a control result,
  risk score, technical verdict, or approval state.
- Risk measures assessed change exposure. Confidence measures the proportion of
  controls backed by fresh digest-pinned evidence. Neither is derived from the
  other.
- The recommendation is technical-only and always has
  `grants_approval: false`. A human decision is a separate record owned by the
  external CAB/change-management authority.
- The same semantic inputs, including the explicit timestamp, produce identical
  canonical bytes, IDs, hashes, ordering, and verdict.

## Consequences

- Consumers gain a strict, reproducible audit contract without changing the
  CLI, Action, JSON risk report, evidence v2 envelope, or ServiceNow attachment.
- Input content is never embedded. Callers must calculate approved SHA-256
  digests outside the contract boundary and must not submit secrets or raw
  sensitive values for hashing.
- The legacy adapter caps confidence at 80 because the legacy report does not
  prove a complete positive control inventory.
- Schema v1 is strict (`additionalProperties: false`). Extensions require a new
  optional namespaced field in a compatible schema release or a new schema
  version; silent reinterpretation is prohibited.

## Rollback

Stop invoking the adapter or kernel and continue emitting the unchanged legacy
risk report and Evidence Contract v2. Remove the additive Python exports,
assessment schema, tests, ADR, and assessment documentation together. No legacy
data migration or output restoration is required because this change neither
replaces nor mutates legacy artifacts.



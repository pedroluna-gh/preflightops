# ADR 0007: Auditable Assessment Contract reports

- Status: Accepted
- Date: 2026-09-03
- Scope: Stage 08 only

## Context

Existing report renderers consume `risk-report-v1`; changing them in place would
reinterpret a public contract. Assessment Contract v1 needs a deterministic pre-CAB
view that makes ERROR/UNKNOWN, provenance and the human authority boundary visible
without copying raw evidence or adding network behavior.

## Options

| Design | Benefit | Cost / risk |
| --- | --- | --- |
| Conservative: replace fields in legacy renderers | Small initial surface | Breaks consumers and mixes legacy risk with the strict assessment contract |
| Balanced: additive strict report projection and pure renderers | Deterministic, compatible, private by construction and easy to roll back | Requires an explicit valid Assessment Contract and migration paths |
| Enterprise: remote templates, live enrichment and automatic publication | Rich organization-specific presentation | Adds mutable state, credentials, privacy exposure and nondeterministic dependencies |

## Decision

Adopt the balanced design. Add a strict `assessment-report-v1` projection, canonical
serialization, pure Markdown/PR/ticket renderers and an opt-in local CLI/Action path.
Preserve all legacy functions and files.

The projection carries every control and permitted provenance record, but only bounded,
redacted metadata. Top blockers and actions have explicit omission counts. The PR and
ticket summaries use stable character budgets; the full JSON remains the audit source.

## Consequences

- Risk, confidence, technical recommendation and human decision remain independent.
- ERROR/UNKNOWN remains visibly indeterminate and can never render as PASS/approval.
- IDs, timestamps, versions, commit and hashes are available for audit correlation.
- The core remains offline; URLs are validated but never fetched.
- Consumers explicitly opt into output paths and publication permissions.
- Pattern redaction remains defense in depth; producer minimization and retention policy
  are still required.

## Rollback

Stop using the additive API/subcommand or remove optional Action inputs. Legacy
renderers are unchanged and no external or persistent state must be repaired.


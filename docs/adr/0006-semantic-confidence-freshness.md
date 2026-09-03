# ADR 0006: Semantic validation, confidence, and freshness

- Status: Accepted
- Date: 2026-09-03
- Scope: Stage 07 only

## Context

Legacy plan validators cannot express provenance, expiry, error, uncertainty or
non-applicability. Tightening them in place would reinterpret public behavior.
The new layer must remain offline and must not couple evidence confidence to risk
or human approval.

## Options

| Design | Benefit | Cost / risk |
| --- | --- | --- |
| Conservative: harden legacy booleans | Small patch | Breaking reinterpretation; no UNKNOWN/ERROR/N/A or auditable formula |
| Balanced: additive strict contract and pure evaluator | Deterministic, explainable, compatible, no network | Structured producers and explicit timestamps/digests are required |
| Enterprise: NLP plus live provider verification | Broader free-text/live coverage | Nondeterminism, credentials, privacy, network, and operational lifecycle |

## Decision

Adopt the balanced design. Add strict input/output schemas, immutable evidence
and policy models, a pure evaluator, canonical IDs/hashes, and an explicit
legacy adapter. Preserve the original validators and all existing outputs.

Confidence uses fixed determinability/freshness/provenance components and
nonlinear caps. It can be high for a demonstrated FAIL; it never depends on risk,
recommendation, waiver, or human decision. Freshness uses only explicit times and
the earlier of declared expiry and policy TTL.

## Consequences

- PASS/N/A requires fresh digest-pinned evidence from an available provider and
  successful parser.
- ERROR/UNKNOWN is never upgraded to PASS; stale PASS/N/A becomes UNKNOWN.
- Outputs contain metadata and fixed issue codes, never plan/provider content.
- Consumers can adopt in shadow mode without changing CLI, Action, report, or
  risk behavior.
- Free-text truth, URL reachability and undeclared contradictions remain outside
  this deterministic stage.

## Rollback

Stop invoking the additive API or pin the prior package. No persistent or remote
state exists. Existing legacy outputs and historical semantic contracts remain
unchanged.

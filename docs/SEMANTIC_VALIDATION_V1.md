# Semantic Validation Contract v1

Semantic Validation Contract v1 is an additive, deterministic layer for
rollback, monitoring, and post-change validation plans. It answers whether the
supplied evidence is semantically sufficient and trustworthy enough to support
a control conclusion. It does not calculate risk, approve a change, resolve an
external reference, or replace Assessment Contract v1.

## Boundary

The core receives all plans, evidence metadata, policy, and `evaluated_at` as
arguments. It never reads the clock, environment, filesystem, network, provider
API, dashboard, alert, ServiceNow, or Jira. Repeating the same semantic input and
context therefore produces the same canonical bytes, execution IDs, contract ID,
and integrity digest.

The two public schemas are:

- [`semantic-change-controls-v1.schema.json`](../schemas/semantic-change-controls-v1.schema.json):
  strict structured input;
- [`semantic-validation-v1.schema.json`](../schemas/semantic-validation-v1.schema.json):
  strict, content-free result.

## Semantic minima

Every plan declares `applicable`, `not_applicable_reason`, `owner`,
`duration_minutes`, `success_criteria`, `steps`, and `contradictions`. An
observable step has exactly `action`, `observable_signal`, and
`expected_result`.

Additional requirements are:

| Control | Required semantics when applicable |
| --- | --- |
| Rollback | action, trigger, owner, duration, success criteria, observable steps |
| Monitoring | owner, duration, success criteria, dashboard references, alert references, observable steps |
| Validation | owner, duration, success criteria, observable steps |

Length alone is never evidence. Empty lists, known placeholders (`todo`, `tbd`,
`qwerty`, etc.), repeated-character gibberish, malformed steps, unsafe URLs,
declared broken references, and declared contradictions produce stable issues.
Issue messages never interpolate rejected values.

References use `{id, url, state}`. Dashboard URLs must be HTTPS without
credentials, query, or fragment. Alert URLs are optional but obey the same rule
when present. `BROKEN` fails and `UNKNOWN` prevents PASS. This is syntactic and
declarative validation only; availability is not probed.

## State model

Controls produce exactly one state:

- `PASS`: structured semantics are complete and evidence is fresh and
  digest-pinned;
- `FAIL`: a semantic defect is demonstrated;
- `UNKNOWN`: evidence/provider/reference state is insufficient or expired;
- `ERROR`: parser/provider/metadata evaluation failed;
- `NOT_APPLICABLE`: the exclusion is explicit, meaningful, fresh, and
  digest-pinned.

Precedence is fail-closed: technical errors override all plan conclusions;
provider absence or missing provenance yields UNKNOWN; a demonstrated semantic
defect yields FAIL; uncertainty yields UNKNOWN. Expired evidence degrades PASS
and NOT_APPLICABLE to UNKNOWN. A demonstrated FAIL remains FAIL when stale, but
its confidence is capped. No ERROR or UNKNOWN path becomes PASS.

## Evidence and freshness

`SemanticEvidenceReference` contains only:

- source identifier;
- provider status: `AVAILABLE`, `ABSENT`, or `ERROR`;
- parser status: `OK` or `ERROR`;
- `collected_at` and `valid_until` RFC 3339 timestamps;
- an approved SHA-256 digest.

The effective expiry is:

```text
min(valid_until, collected_at + policy.max_age_seconds)
```

The default maximum age is 3,600 seconds. A missing timestamp is UNKNOWN. A
future collection time, malformed timestamp, inverted interval, invalid digest,
or provider/parser error is ERROR. All comparisons use the caller-supplied
`evaluated_at`; there is no implicit current time.

## Confidence calibration

Confidence describes how well the conclusion is supported. It is independent
from risk, technical recommendation, and human decision. A fresh,
digest-pinned, structurally clear FAIL can correctly have confidence 100.

| Component | Points |
| --- | ---: |
| Determinability | 60 for PASS/FAIL/N/A; 20 for semantic uncertainty; 0 for technical error |
| Freshness | 25 FRESH; 5 STALE; 0 UNKNOWN |
| Provenance | 15 when provider is available, parser is OK, and SHA-256 is valid |

The raw sum is subject to the lowest applicable nonlinear cap:

| Condition | Maximum |
| --- | ---: |
| ERROR | 20 |
| Provider absent | 25 |
| Freshness UNKNOWN | 40 |
| UNKNOWN or STALE | 49 |
| Fully supported | 100 |

Levels are LOW 0–49, MEDIUM 50–79, and HIGH 80–100. Overall confidence is the
integer average across the three controls. N/A remains in that average because
an exclusion also requires trustworthy evidence.

This first calibration is deliberately conservative. Recalibration must keep
the basis identifier and golden tests stable or introduce a new contract
version; it must never be changed silently.

## Privacy and integrity

The result does not embed plans, actions, triggers, owners, criteria, steps,
contradiction text, provider payloads, or arbitrary input. It contains fixed
issue text, bounded identifiers, timestamps, state, and digests only. The
`data.content_embedded` invariant is always false.

Canonical JSON uses UTF-8, sorted keys, compact separators, and one trailing LF.
Each control ID hashes its content-free result. The contract ID and integrity
hash cover the complete semantic result except those two self-referential
fields. Strict validation rejects unknown fields, tamper, inconsistent counts,
invalid confidence, invalid PASS/N/A evidence, or identity mismatch.

## Python API

```python
from preflightops import (
    SemanticEvidenceReference,
    SemanticValidator,
    serialize_semantic_validation_v1,
)

result = SemanticValidator().evaluate(
    plans=structured_plans,
    evidence={
        "rollback-plan": SemanticEvidenceReference(
            source="change-request-validator",
            collected_at="2026-09-03T12:00:00Z",
            valid_until="2026-09-03T13:00:00Z",
            sha256=approved_digest,
        ),
        # monitoring-plan and validation-plan follow the same metadata contract
    },
    evaluated_at="2026-09-03T12:30:00Z",
)
payload = serialize_semantic_validation_v1(result)
```

Callers must supply all three evidence references to obtain complete PASS/N/A
coverage. Missing entries are deliberately `PROVIDER_ABSENT` / UNKNOWN.

## Legacy migration

The original `is_bad_rollback_plan`, `is_monitoring_plan_incomplete`, and
`is_validation_plan_valid` functions, risk report, CLI, Action, and reports are
unchanged. `adapt_legacy_change_request` is an explicit parallel path: it reads
the three legacy fields, labels `source_contract=change-request-v1`, preserves
the source object and outputs, and never parses prose into invented structured
facts. Unstructured legacy values therefore fail semantic completeness or are
UNKNOWN when evidence is absent.

Recommended rollout:

1. generate the new contract in shadow mode and retain legacy outputs;
2. migrate producers to the structured schema field by field;
3. compare status/confidence and investigate every UNKNOWN/ERROR;
4. make the new result a gate only after consumer policy and retention are
   approved;
5. keep Assessment Contract risk and the external human decision independent.

## Rollback

Stop calling `SemanticValidator` or pin the previous package version. No schema
or output is removed and there is no external state to undo. Retain already
issued contracts as historical evidence; do not re-label their UNKNOWN/ERROR
states or recompute them with a later policy under the same version.

## Residual risks

- Lexical checks are deterministic but do not understand arbitrary language or
  verify that a statement is true.
- URL availability and monitor ownership are not verified in this offline stage.
- Producers must identify contradictions explicitly; prose contradictions are
  not inferred.
- Consumers remain responsible for approved non-sensitive digests, retention,
  classification, and compatible version evolution.

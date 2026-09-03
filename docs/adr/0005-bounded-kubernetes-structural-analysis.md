# ADR 0005: Bounded structural Kubernetes analysis

- Status: Accepted
- Date: 2026-09-03

## Context

The historical Kubernetes scanner combined permissive YAML loading, global
keyword matching and fallback behavior. A malformed document or comment could
therefore look like valid evidence, and fields from one workload could satisfy
checks for another. The assessment path needs reproducible per-object evidence
without cluster access or Secret disclosure.

## Options considered

### Conservative

Keep the implementation in `scanners.py`, add input-size checks and remove only
the parse-error fallback. This changes less code, but leaves parsing, privacy,
normalization and policy coupled and makes the object boundary difficult to
audit.

### Balanced

Use a dedicated module with immutable limit and object models, a strict safe
loader, bounded `List` expansion, sanitized Secret bodies and pure deterministic
rules. Preserve the old text scanner through a separately named adapter.

### Enterprise

Validate versioned Kubernetes OpenAPI/CRD schemas, run Rego or CEL policy,
render templates and query live inventory. This can improve semantic coverage,
but introduces external artifacts, credentials and lifecycle management beyond
this stage's offline evidence boundary.

## Decision

Adopt the balanced option. `scan_kubernetes` is the fail-closed structural path
used by the risk engine, CLI and Action. `scan_kubernetes_legacy` is explicit
and is never invoked as fallback. Each finding carries object identity, field
and predicate, and deterministic sorting removes document-order effects.

## Consequences

Complete valid manifests gain precise per-object evidence and bounded resource
use. Incomplete historical snippets must migrate to the legacy adapter or be
made valid. The implementation does not assert facts requiring a live cluster
and does not validate every Kubernetes or CRD schema.

Secret payload fields are discarded before rule evaluation and cannot enter
models, findings or sanitized errors. Rollback consists of pinning the previous
release or temporarily selecting the explicit legacy adapter; no external state
is created.

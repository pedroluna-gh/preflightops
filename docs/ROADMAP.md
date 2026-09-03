# PreflightOps Roadmap

This roadmap describes the planned direction for PreflightOps. It is intentionally
ambitious but constrained by the project's core principles: **no required
database, no required login, no external API calls on the default assessment
path, and no AI.** Optional integrations must remain explicit and the core must
keep running locally in a transparent and explainable way.

Priorities and timing may change based on community feedback — open an issue to
suggest or upvote an item.

## Recently completed for v0.4

- Bounded Terraform JSON 1.x parsing with sensitive-safe resource/action evidence.
- Bounded, fail-closed multi-document Kubernetes object and container
  validation with Secret-safe field evidence and an explicit legacy adapter.
- Versioned, customizable policy packs and risk weights.
- Secrets-free observability inventory validation for major providers.
- GitHub PR changed-file detection and scanner-scope inference.
- Compact, grouped GitHub comments with prioritized actions.
- Dependency-free static HTML reports for CAB stakeholders.
- Hardened ServiceNow destination validation and OAuth bearer support.
- Configurable evidence-only field mappings and versioned evidence schemas.
- Stable/legacy-aware idempotency, ambiguity detection, read-back verification,
  and deduplicated attachments.
- Manual dry-run-first ServiceNow demo behind a protected GitHub Environment.

## Enterprise maturity program

The sequenced enterprise program is defined by
[`ENTERPRISE_GOVERNANCE.md`](ENTERPRISE_GOVERNANCE.md),
[`THREAT_MODEL.md`](THREAT_MODEL.md), and
[`ENTERPRISE_DOD.md`](ENTERPRISE_DOD.md). Its first secure-SDLC baseline adds
immutable Action references, CodeQL, dependency review, Scorecard, SBOM,
checksums and release attestations. Subsequent compatible releases add Evidence
Contract v2, signed hierarchical policy/waiver verification, production-grade
CMDB context and organization-scale delivery. PreflightOps remains evidence-only
and never becomes the CAB or ITSM workflow authority.

## v0.6 — Authenticated Evidence Contract v2 (implemented, unreleased)

- Ed25519-signed DSSE envelope with an in-toto Statement.
- Signed organization, repository, commit, ref, workflow/run/actor, service,
  environment, product version, policy digest, assessment and input digests.
- Offline `evidence generate` and `evidence verify` commands with a
  machine-readable verdict.
- Deterministic redaction, 1 MiB bound, classification and no embedded raw
  input content.
- Optional Action output backed by a protected environment secret; no private
  key Action input.
- v1/v2 dual output, schemas, golden inputs, tamper/trust/input/replay tests,
  migration guidance and rollback.

## v0.1 — Initial release

- Rule-based risk engine with a `0–100` score and four risk levels.
- Service-control, change-type, Terraform, and Kubernetes rules.
- Markdown + JSON reports with a per-source score breakdown.
- Streamlit web app and `preflightops` CLI.
- Composite GitHub Action for consumer PR risk gates and a manual smoke/demo
  workflow in this source repository.

## v0.1.x — Change-ticket summaries & opt-in integrations

- Copy/paste-ready ServiceNow/Jira change ticket summary (`--ticket-output`).
- Configurable ticket templates (`--ticket-template`).
- Optional, opt-in ServiceNow and Jira live push (`--servicenow` / `--jira`),
  available from the CLI, GitHub Action, and web app. Credentials are read from
  the environment only, and nothing is sent unless explicitly enabled.

## v0.2 — Structured change evidence

- Parse `terraform show -json` plan output explicitly; retain keyword matching only as deprecated legacy input.
- Distinguish create / update / delete / replace per resource.
- Map provider resource types to risk weights.
- Parse Kubernetes manifests as objects (multi-document YAML).
- Inspect probes, resource limits, replicas, and exposure per workload.
- Detect risky `kind` + field combinations more precisely.
- User-supplied rule weights and thresholds via a config file.
- Enable / disable individual rules.
- Per-environment policy (e.g. stricter rules for `production`).

## v0.3 — Pull-request delivery context and reporting

- Static HTML dashboard export.
- Metadata-only changed-file detection for GitHub pull requests.
- Automatic selection of unambiguous structured plan/manifest inputs.
- Dedicated compact Markdown for idempotent PR comments.

## v0.4 — Verified ServiceNow evidence delivery (current)

- Enrich an existing Change and fail closed when its reference is missing.
- Keep ServiceNow workflow state, approvals, assignments, and closure outside
  the integration's writable contract.
- Attach structured evidence and verify both records and attachments.
- Support a network-free preview and environment-protected live demo.

## Designed next — ServiceNow enterprise adapter v2

- Default to enriching an existing Change by number/sys_id.
- Use an instance-side Evidence Gateway with field allowlist, unique delivery
  key and atomic concurrency control for production.
- Keep direct Change Management API for sandbox/pilot and Table API as a legacy
  read-only rollback path.
- Gate optional draft creation on an explicitly allowed change model and a
  separate enterprise policy decision.

This is an approved architecture design, not yet a runtime capability. See the
[enterprise golden path](SERVICENOW_ENTERPRISE_GOLDEN_PATH.md).

## Next — Policy governance and verified exceptions (implemented, unreleased)

- Signed hierarchical policy bundles with mandatory/non-reducible controls.
- Offline, scoped and expiring Waiver Contract v1 verification.
- Policy lint, test, diff, explain, lineage and rollback.
- Non-authoritative candidate simulation, explicit failure modes, context
  conflict rejection and an external-authority decision record.

## Ecosystem integrations (optional, opt-in)

- Basic ServiceNow / Jira change-record push — **available now** (see v0.1.x).
- Jira parity for destination validation, richer mapping, and verification.
- Audit-trail metadata on generated change records.
- Expanded, shareable ticket-template library.
- PagerDuty / Opsgenie incident-history context.
- Datadog / Grafana dashboard link validation.

> Integrations will be **opt-in** and must never become a hard runtime
> dependency — PreflightOps always works fully offline.

## Future / under consideration

- Policy-as-code approval workflows.
- Additional cloud providers and IaC tools (Pulumi, CloudFormation).
- Pre-commit hook packaging.
- PyPI distribution (`pip install preflightops`).

## Out of scope

- AI / ML scoring models.
- Acting as a security boundary or a replacement for human review.
- Storing assessment data in a hosted backend.

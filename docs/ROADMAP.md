# PreflightOps Roadmap

This roadmap describes the planned direction for PreflightOps. It is intentionally
ambitious but constrained by the project's core principles: **no required
database, no required login, no external API calls on the default assessment
path, and no AI.** Optional integrations must remain explicit and the core must
keep running locally in a transparent and explainable way.

Priorities and timing may change based on community feedback — open an issue to
suggest or upvote an item.

## Recently completed for v0.3

- Structured Terraform JSON plan parsing with resource/action evidence.
- Structured multi-document Kubernetes object and container validation.
- Versioned, customizable policy packs and risk weights.
- Secrets-free observability inventory validation for major providers.
- GitHub PR changed-file detection and scanner-scope inference.
- Compact, grouped GitHub comments with prioritized actions.
- Dependency-free static HTML reports for CAB stakeholders.

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

- Parse `terraform show -json` plan output instead of keyword matching.
- Distinguish create / update / delete / replace per resource.
- Map provider resource types to risk weights.
- Parse Kubernetes manifests as objects (multi-document YAML).
- Inspect probes, resource limits, replicas, and exposure per workload.
- Detect risky `kind` + field combinations more precisely.
- User-supplied rule weights and thresholds via a config file.
- Enable / disable individual rules.
- Per-environment policy (e.g. stricter rules for `production`).

## v0.3 — Pull-request delivery context and reporting (current)

- Static HTML dashboard export.
- Metadata-only changed-file detection for GitHub pull requests.
- Automatic selection of unambiguous structured plan/manifest inputs.
- Dedicated compact Markdown for idempotent PR comments.

## Next — Reporting depth

- Historical trend view across multiple assessments.
- SARIF output for code-scanning integrations.

## Ecosystem integrations (optional, opt-in)

- Basic ServiceNow / Jira change-record push — **available now** (see v0.1.x).
- Stronger ServiceNow / Jira API hardening (retries, error handling, field and
  richer workflow/state mapping).
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

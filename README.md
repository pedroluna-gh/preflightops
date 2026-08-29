# PreflightOps

> **Preflight checks for risky production changes.** Before production changes take off, check the operational risk. Use it during technical pre-CAB reviews to align on risk, rollback readiness, monitoring coverage, and implementation evidence before formal approval. 

PreflightOps is a pre-deployment risk assessment tool for SRE, DevOps, and Platform Engineering teams. It turns a service catalog and a proposed change into a clear **0–100 risk score**, a **risk level** (`LOW` / `MEDIUM` / `HIGH` / `CRITICAL`), a plain-English recommendation, and an actionable list of the exact gaps to fix — *before* the change ships.

## Try it in a pull request

```yaml
- uses: pedroluna-gh/preflightops@v0.4.2
  with:
    services: services.yaml
    change: change.yaml
    terraform: tfplan.txt
    k8s: k8s.yaml
    fail-on: critical
```

---


It runs as a **Streamlit web app** for interactive reviews and as a **CLI / GitHub Action** for automated pull-request gates. No database, no login, no AI — the risk assessment runs entirely locally. Network access is limited to metadata-only PR filename discovery in the Action and explicit [ServiceNow / Jira integrations](#opt-in-push-straight-into-servicenow--jira).

[![CI](https://github.com/pedroluna-gh/preflightops/actions/workflows/ci.yml/badge.svg)](https://github.com/pedroluna-gh/preflightops/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab?logo=python&logoColor=white)](#requirements)

![PreflightOps web app](docs/screenshots/app-overview.png)

## The problem

Most production incidents are triggered by changes — deployments, configuration updates, and infrastructure edits.

Teams invest heavily in CI/CD, Terraform, Kubernetes, and observability, yet the decision “is this change safe to ship?” is often still made through gut feel during a rushed review.

Common gaps include:

- Rollback plans that are missing, vague, or untested.
- Critical services without clear runbooks or named owners.
- Monitoring and post-deploy validation treated as afterthoughts.
- Risky Terraform changes — IAM, destroy/delete actions, security groups — slipping through review.
- Risky Kubernetes changes — exposed Secrets, missing probes, `replicas: 0` — reaching production too easily.

PreflightOps makes that judgment explicit, consistent, and auditable.

It encodes change-governance and production-readiness checks as transparent rules so every change receives the same operational scrutiny before it moves forward.

In real production environments, many of the most valuable change conversations happen before the formal CAB meeting — during technical pre-CAB reviews, when engineering, SRE, DevOps, platform, and operations teams are still validating impact, rollback readiness, monitoring coverage, and deployment risk.

PreflightOps is designed for that moment.

It gives technical reviewers a structured way to identify missing evidence, surface risky infrastructure changes, align on service ownership, and generate a change summary that can support ServiceNow, Jira, CAB notes, or internal approval workflows.

The goal is not to replace CAB, change leadership, or human judgment.

The goal is to help teams enter formal change approval with better context, clearer risk signals, and fewer blind spots.

## What it checks

- Production changes without a valid rollback plan
- Critical / high-criticality services
- Missing service ownership, runbooks, and business impact
- Incomplete monitoring plans and missing post-deploy validation
- Risky Terraform signals: IAM/role changes, security groups, firewalls, DNS, KMS, database instances, public IP exposure, and `destroy` / `delete` actions
- Risky Kubernetes signals: Ingress, Secret, NetworkPolicy, StatefulSet, LoadBalancer exposure, `replicas: 0`, and Deployments missing readiness / liveness probes
- Structured Terraform JSON resource/action evidence and multi-document Kubernetes object parsing
- Versioned policy packs for SaaS, fintech, ecommerce, healthcare, critical platforms, and lightweight startup governance
- Offline Datadog, Grafana, Prometheus, Zabbix, and GCP Cloud Monitoring inventory validation

## Quick demo

Try it in under a minute without writing any YAML:

```bash
# 1. Install (with the web UI extras)
pip install -e ".[app]"     # run from the preflightops/ directory

# 2. Launch the web app
streamlit run app.py
```

Then in the browser: click **Low / High / Critical Risk Example** to load a ready-made scenario, hit **Run Risk Assessment**, and explore the score, the per-category breakdown, the triggered rules, and the downloadable Markdown / JSON reports. Edit the YAML to match your own change and re-run.

Prefer the terminal? Score one of the bundled examples directly:

```bash
preflightops \
  --services examples/services-high-risk.yaml \
  --change examples/change-high-risk.yaml \
  --output report.md
```

![PreflightOps risk assessment results](docs/screenshots/risk-results.png)

## Installation

Install PreflightOps and its `preflightops` CLI with a single command:

```bash
pip install git+https://github.com/pedroluna-gh/preflightops.git@main
```

> Replace the URL with your own fork/repo. Once published to PyPI, this becomes `pip install preflightops`.

To also run the Streamlit web UI, add the optional `app` extras:

```bash
pip install "preflightops[app] @ git+https://github.com/pedroluna-gh/preflightops.git@main"
```

### Develop from a clone

```bash
git clone https://github.com/pedroluna-gh/preflightops.git
cd preflightops
pip install -e ".[app]"      # editable install with the web UI extras
```

`requirements.txt` does this for you: `pip install -r requirements.txt`.

### Requirements

- Python 3.9+
- Core dependencies: `pyyaml` and `cryptography` (Ed25519 authenticated
  evidence). The web UI extras add `streamlit` and `pandas`.

## Usage

### Web app

```bash
streamlit run app.py
```

Load an example, edit the **Service Catalog** and **Change Request** YAML, optionally paste a **Terraform plan** and a **Kubernetes manifest**, and click **Run Risk Assessment**. Download the result as Markdown or JSON.

### Command line

```bash
preflightops \
  --services examples/services-critical-risk.yaml \
  --change examples/change-critical-risk.yaml \
  --terraform examples/terraform-critical.txt \
  --terraform-json examples/tfplan.json \
  --k8s examples/k8s-risk.yaml \
  --policy fintech \
  --monitors examples/monitors.yaml \
  --changed-files changed-files.json \
  --output report.md \
  --json-output report.json \
  --html-output report.html \
  --github-comment-output pr-comment.md
```

(The equivalent `python -m preflightops.cli ...` also works.)

The CLI prints the score and level, writes Markdown plus optional JSON, static
HTML, and compact GitHub-comment reports, and **exits with code `1` when the risk
level is `CRITICAL`** (otherwise `0`) — so you can fail a pipeline on critical
risk. A newline/JSON `--changed-files` manifest records PR scope and safely
auto-loads unambiguous structured Terraform plans and Kubernetes manifests.

Structured inputs, policy packs, and the secrets-free observability inventory
are documented in [`docs/POLICY_AND_EVIDENCE.md`](docs/POLICY_AND_EVIDENCE.md).

### Governed policy and verified exceptions

Enterprise Policy Bundle v2 adds signed, effective-dated, hierarchical rules
for environment, service tier, normal/standard/emergency classification, and
technical change type. Teams can lint, diff, and simulate a draft before an
independent owner activates it. Mandatory controls cannot be weakened by an
overlay and ambiguous precedence fails closed.

Waiver Contract v1 verifies a scoped, expiring exception with separate
requester/approver identities, evidence, compensating controls, and an Ed25519
signature. A waiver never lowers the technical score or approves a change;
ServiceNow/Jira and CAB remain authoritative. See
[`docs/POLICY_GOVERNANCE_V2.md`](docs/POLICY_GOVERNANCE_V2.md).

### Authenticated pre-CAB evidence

Evidence Contract v2 signs the exact assessment and its repository, commit,
workflow, policy digest and named input digests as an in-toto Statement inside a
DSSE envelope. Verification is offline and machine-readable; it does not grant
approval or modify the authoritative ServiceNow/Jira workflow.

```bash
preflightops evidence generate \
  --assessment report.json \
  --change change.yaml \
  --policy policy.yaml \
  --input services=services.yaml \
  --input change=change.yaml \
  --output evidence-v2.dsse.json \
  --legacy-output evidence-v1.json

preflightops evidence verify \
  --evidence evidence-v2.dsse.json \
  --public-key trusted-ed25519.pub.pem \
  --expected-repository acme/payments-api \
  --expected-commit "$GITHUB_SHA" \
  --max-age-seconds 3600 \
  --output verification.json
```

Private-key material comes from a protected PEM file or
`PREFLIGHTOPS_EVIDENCE_PRIVATE_KEY`; the GitHub Action never accepts it as an
input. See [`docs/EVIDENCE_CONTRACT_V2.md`](docs/EVIDENCE_CONTRACT_V2.md) for
trust distribution, dual-output migration, verification pins and rollback.

### GitHub Action (PR risk gate)

PreflightOps ships a composite Action that consuming repositories can configure
as a pull-request gate. The workflow in
[`.github/workflows/preflightops.yml`](.github/workflows/preflightops.yml) is a
manually dispatched adoption example using the LOW, HIGH, and CRITICAL inputs
shipped in `examples/`. Engineering quality gates run separately in
`.github/workflows/ci.yml`.
The complete pull-request workflow for consuming repositories is documented in
[`docs/GITHUB_ACTION.md`](docs/GITHUB_ACTION.md).

A completed public example is available in
[`pedroluna-gh/preflightops-demo` PR #1](https://github.com/pedroluna-gh/preflightops-demo/pull/1).
It shows `v0.3.0` detecting the changed Terraform/Kubernetes inputs, returning
`HIGH 75/100`, publishing the grouped bot comment, uploading all report formats,
and passing the configured `CRITICAL` gate.

![PreflightOps v0.3.0 in a real pull request](docs/screenshots/preflightops-demo-pr.png)

Run the manual source workflow and choose a scenario to inspect the result in
the job summary. It has only `contents: read`; it does not comment on pull
requests or write repository state.

You can also call the bundled composite action directly with `uses:`. It detects
changed PR filenames, infers relevant scanners, generates a compact comment,
runs the assessment, and gates the job on `fail-on`. Add `html-output` for a
self-contained CAB artifact or `ticket-output` for a copy/paste-ready change
summary:

```yaml
- uses: pedroluna-gh/preflightops@v0.4.2
  with:
    services: services.yaml
    change: change.yaml
    terraform: tfplan.txt
    k8s: k8s.yaml
    output: preflightops-report.md
    html-output: preflightops-report.html
    ticket-output: preflightops-ticket.md
    fail-on: critical
```

Live ServiceNow/Jira push is optional and should only be enabled in trusted workflows, with credentials provided through GitHub Actions secrets — see [Opt-in: push from the GitHub Action](#opt-in-push-from-the-github-action) and the [GitHub Action guide](docs/GITHUB_ACTION.md).

## ServiceNow / Jira-ready change summaries

PreflightOps can generate a copy/paste-friendly Markdown change summary for ServiceNow, Jira, CAB reviews, or internal approval workflows.

It does **not** require ServiceNow or Jira API access, authentication, tokens, or any network call. It simply turns the risk assessment into a structured change-record-style ticket you can paste into your change-management tool of choice.

Add `--ticket-output` to write the summary alongside the normal report:

```bash
preflightops \
  --services examples/services-critical-risk.yaml \
  --change examples/change-critical-risk.yaml \
  --terraform examples/terraform-critical.txt \
  --k8s examples/k8s-risk.yaml \
  --output report.md \
  --ticket-output ticket.md
```

The ticket includes the change title, service, environment, business impact, risk level and score, a risk-level-aware approval recommendation and deployment window, the rollback / monitoring / validation plans (with fallback text when missing), the risk findings, and recommended actions. See a full sample in [`examples/ticket-critical.md`](examples/ticket-critical.md) and the [ticket generator guide](docs/TICKET_GENERATOR.md).

> `--ticket-output` is a copy/paste summary generator: it makes **no network calls** and needs **no credentials**.

### Customize the ticket layout

The change summary uses a built-in layout, but you can tailor it with
`--ticket-template` — a YAML or JSON file that controls the section order,
headings, and the approval / deployment-window wording. The template shapes the
summary everywhere it is produced (the `--ticket-output` file and any opt-in
ServiceNow / Jira push below), and any sections you leave out fall back to the
built-in defaults.

```bash
preflightops \
  --services examples/services-critical-risk.yaml \
  --change examples/change-critical-risk.yaml \
  --output report.md \
  --ticket-output ticket.md \
  --ticket-template my-cab-template.yaml
```

### Opt-in: push straight into ServiceNow / Jira

If you want the assessment to flow directly into your change-management tool, add
the opt-in `--servicenow` and/or `--jira` flags. These take the **non-secret**
instance/base URL; every credential is read from the environment only and is
never accepted on the command line or hard-coded.

```bash
# Credentials via environment/secrets only — never on the command line.
export SERVICENOW_TOKEN=...       # preferred OAuth bearer token
# Or, for an isolated test user only:
# export SERVICENOW_USER=...
# export SERVICENOW_PASSWORD=...
export JIRA_EMAIL=...             # Jira
export JIRA_API_TOKEN=...
export JIRA_PROJECT_KEY=OPS

preflightops \
  --services examples/services-critical-risk.yaml \
  --change examples/change-critical-risk.yaml \
  --output report.md \
  --servicenow https://dev12345.service-now.com \
  --jira https://example.atlassian.net
```

This **creates or updates** a ServiceNow `change_request` and/or a Jira issue
using the generated change summary as the record body. A second run for the same
change updates the existing record instead of creating a duplicate (a
deterministic correlation id is stored on the record). Set `JIRA_ISSUE_TYPE` to
override the default issue type (`Task`).

Before any live push, PreflightOps prints the target instance/base URL, the
deterministic correlation id, and that a matching record is updated if it exists
(otherwise created), then asks for an explicit confirmation — so a typo or a
copy-pasted command never silently reaches a production change-management system.
Pass `--yes` (alias `--assume-yes`) to skip the prompt for CI/automation. When
there is no interactive terminal and `--yes` was not given, the push is skipped
(no API call) and the run exits cleanly.

The integration is **strictly opt-in**: when you omit both flags, PreflightOps
makes no outbound network calls and the offline `--ticket-output` path keeps
working exactly as before. An integration misconfiguration (missing credentials,
bad URL, API error) is reported to stderr and exits non-zero **without** touching
the offline report paths.

For controlled enterprise adoption, prefer enriching an existing Change and
attaching evidence:

```bash
preflightops \
  --services examples/services-high-risk.yaml \
  --change examples/change-high-risk.yaml \
  --output report.md \
  --servicenow https://dev12345.service-now.com \
  --servicenow-change CHG0030001 \
  --servicenow-mapping examples/servicenow-field-map.yaml \
  --servicenow-attach-evidence \
  --servicenow-dry-run
```

Dry-run reads no credentials and makes no API calls. Remove
`--servicenow-dry-run`, review the preview, and explicitly confirm to publish.
An existing Change reference is fail-closed: PreflightOps never creates a
replacement when that reference is missing. Every live write is read back and
verified, while evidence attachments are deduplicated by semantic SHA-256.
See [ServiceNow pre-change evidence integration](docs/SERVICENOW_INTEGRATION.md).

The protected reference workflow validates the request, renders a credential-free
preview, and publishes only after the `servicenow-demo` GitHub Environment is
approved:

![Protected ServiceNow evidence workflow](docs/screenshots/servicenow-protected-workflow.png)

The run summary makes the governance boundary explicit: PreflightOps enriches and
verifies an existing test Change, but cannot write approval, assignment, schedule,
workflow state, or closure fields. A second identical controlled run also verified
idempotency and attachment deduplication.

![ServiceNow publication guardrails](docs/screenshots/servicenow-publication-guardrails.png)

### Opt-in: push from the GitHub Action

The composite action can run the same opt-in push. ServiceNow publication should
be separated from pull-request assessment and placed behind a protected GitHub
Environment; the included `ServiceNow pre-change evidence demo` workflow is the
reference implementation.

It stays **off by default**: the Action behaves exactly as it does today until
you pass a non-secret `servicenow` and/or `jira` URL as an action input. Because
a CI runner has no interactive terminal, set `assume-yes: true` to waive the
confirmation prompt. Provide credentials as **environment-scoped secrets**, never
on the command line. The example below is the lower-level Action contract;
prefer the protected manual workflow for real publication:

```yaml
jobs:
  risk-review:
    runs-on: ubuntu-latest
    env:
      SERVICENOW_TOKEN: ${{ secrets.SERVICENOW_TOKEN }}
      JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
      JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
      JIRA_PROJECT_KEY: ${{ secrets.JIRA_PROJECT_KEY }}
    steps:
      - uses: actions/checkout@v4
      - uses: pedroluna-gh/preflightops@v0.4.2
        with:
          services: services.yaml
          change: change.yaml
          ticket-output: preflightops-ticket.md
          servicenow: https://dev12345.service-now.com  # enables --servicenow
          servicenow-change: CHG0030001
          servicenow-mapping: examples/servicenow-field-map.yaml
          servicenow-attach-evidence: true
          jira: https://example.atlassian.net           # enables --jira
          assume-yes: true
```

The secrets above map to the environment variables the CLI reads:

| Secret | Used by | Required |
| --- | --- | --- |
| `SERVICENOW_TOKEN` | ServiceNow | preferred bearer authentication |
| `SERVICENOW_USER` | ServiceNow | test-only alternative when no bearer token is set |
| `SERVICENOW_PASSWORD` | ServiceNow | test-only alternative when no bearer token is set |
| `JIRA_EMAIL` | Jira | when the `jira` input is set |
| `JIRA_API_TOKEN` | Jira | when the `jira` input is set |
| `JIRA_PROJECT_KEY` | Jira | when the `jira` input is set |
| `JIRA_ISSUE_TYPE` | Jira | optional (defaults to `Task`) |

Omit `servicenow` / `jira` (or leave them blank) to keep both integrations
disabled — no secrets are needed and no network call is made. Because re-runs are
matched by a deterministic correlation id, repeated pushes for the same change
update the existing record instead of creating duplicates.

### Opt-in: send from the web app

The Streamlit app exposes the same opt-in integration. After running an
assessment, the **Send to ServiceNow / Jira (live)** section lets you create or
update a real ServiceNow `change_request` and/or Jira issue from the generated
summary. To prevent an accidental push to a production system, each send is
gated behind a **Review before sending** step: expand it to see the target
instance/base URL and the create-or-update action, tick the confirmation
checkbox, and only then does the **Send** button become enabled.

As with the CLI, credentials are read from the environment only (the same
`SERVICENOW_TOKEN` or `SERVICENOW_USER` / `SERVICENOW_PASSWORD`, and `JIRA_EMAIL` / `JIRA_API_TOKEN` /
`JIRA_PROJECT_KEY` variables). The send controls stay hidden — with guidance on
which variables to set — until the integration is configured, so the app makes
no outbound network calls unless you opt in.

## Example output

A `HIGH`-risk production deployment produces a report like this:

```markdown
# PreflightOps Risk Report

## Summary

Service: checkout-api
Environment: production
Change Type: deployment
Risk Score: 80/100
Risk Level: HIGH

## Recommendation

Senior review recommended before deployment. Address missing controls before proceeding.

## Score Breakdown

### Service Controls — +80 pts (100%, 4 findings)

- production-change | medium | +20 | Change targets production environment
- critical-service | high | +25 | Service is marked as high or critical
- missing-monitoring-plan | medium | +20 | No monitoring plan defined
- missing-validation-plan | medium | +15 | Post-deploy validation plan is missing

## Missing Controls

- monitoring_plan
- validation_plan

## Business Impact

Customers may be unable to complete checkout
```

The JSON report (`--json-output`) contains the same data plus a grouped `score_breakdown` summary, ready for tooling and auditing.

## How scoring works

PreflightOps sums the points from every triggered rule and scanner finding, capping the total at 100:

| Score   | Level      | What it means                                                        |
| ------- | ---------- | ------------------------------------------------------------------- |
| 0–30    | `LOW`      | Proceed with the normal deployment process.                         |
| 31–60   | `MEDIUM`   | Proceed with caution; ensure owner review and post-deploy checks.   |
| 61–80   | `HIGH`     | Senior review recommended; address missing controls first.          |
| 81–100  | `CRITICAL` | Block until rollback, monitoring, ownership, or validation gaps close. |

Findings are grouped by source — **Service Controls**, **Change Type**, **Terraform**, and **Kubernetes** — so you can see exactly where the risk comes from.

> **Note:** Final risk score is capped at 100. Breakdown values show raw contributing points before the cap is applied.

## Project structure

```
preflightops/
├── app.py                     # Streamlit web app (UI, example loader, results)
├── preflightops/               # Core package
│   ├── risk_engine.py         # Rules, scoring, levels, recommendations
│   ├── validators.py          # Rollback / monitoring / validation plan checks
│   ├── scanners.py            # Terraform & Kubernetes keyword risk scanners
│   ├── report.py              # Markdown & JSON report generators
│   ├── sample_data.py         # Built-in low/high/critical scenarios
│   └── cli.py                 # Command-line entry point (exit 1 on CRITICAL)
├── examples/                  # Example YAML / text inputs for each scenario
├── tests/                     # pytest suite (engine, validators, scanners, CLI, UI)
├── .github/workflows/         # Mandatory CI + manual adoption example
├── scripts/                   # Reproducible packaging smoke checks
├── pyproject.toml             # Packaging + console script + optional extras
└── requirements.txt           # Editable install for local development
```

## Running the tests

PreflightOps ships with a `pytest` suite covering the risk-engine rules, the rollback/monitoring/validation validators, the Terraform/Kubernetes scanners (including the readiness/liveness probe checks), the CLI and report generators, the web UI, and the documented LOW / HIGH / CRITICAL scenarios.

```bash
uv sync --locked --all-extras --group quality
uv run pytest
```

Run from the `preflightops/` directory. Tests live under `tests/`; all mandatory
local commands are documented in [`docs/QUALITY_GATES.md`](docs/QUALITY_GATES.md).

## Public contracts and compatibility

Machine-readable schemas live under [`schemas/`](schemas/). The CLI, Python API,
Action, exit codes, reports, and offline/integration behavior are inventoried in
[`docs/CONTRACTS.md`](docs/CONTRACTS.md). Compatibility and deprecation rules are
defined in [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md).

## Contributing

Contributions are welcome — bug reports, new risk rules, scanner signals, and docs all help.

1. Fork the repo and create a feature branch.
2. Make your change and **add or update tests** under `tests/`.
3. Run `pytest` and make sure the full suite passes.
4. Keep the project's constraints intact: **no database, no login, no AI, and an offline assessment core**. Network access is limited to explicit ServiceNow/Jira integrations and the Action's bounded GitHub PR filename discovery.
5. Open a pull request with a clear description of the change and the risk it addresses.

New risk rules should be transparent and explainable: a stable rule id, a severity, a point value, and a human-readable description. Please open an issue first for larger changes so we can align on direction.

## Security

Enterprise adoption and release governance are defined in
[`docs/ENTERPRISE_GOVERNANCE.md`](docs/ENTERPRISE_GOVERNANCE.md), with the
corresponding [`threat model`](docs/THREAT_MODEL.md),
[`data-governance policy`](docs/DATA_GOVERNANCE.md),
[`Definition of Done`](docs/ENTERPRISE_DOD.md), and
[`release-management runbook`](docs/RELEASE_MANAGEMENT.md). These controls keep
PreflightOps in the evidence-assurance role: ServiceNow, Jira and the CAB remain
authoritative for workflow and approval.

PreflightOps' **risk assessment is offline by default**: it makes no outbound
network calls, stores no data, and requires no credentials. Your service
catalogs, change requests, Terraform plans, and Kubernetes manifests never leave
your machine or CI runner unless you explicitly enable ServiceNow/Jira. In a PR
workflow, automatic scope detection separately reads only filename/status
metadata from GitHub using the run-scoped token; disable it with
`auto-detect-changes: false` for a fully offline Action run.

- Treat any input you paste as sensitive — Terraform plans and Kubernetes manifests can contain infrastructure details. The bundled examples use placeholder data only.
- PreflightOps is a **decision-support aid, not a security boundary.** It surfaces risk signals to inform human review; it does not guarantee a change is safe.
- Found a vulnerability? Please report it privately via a GitHub security advisory rather than a public issue.

## Roadmap

- Copy/paste ServiceNow/Jira-ready change ticket summary (`--ticket-output`) — **available now**
- Opt-in ServiceNow API integration and Jira API integration (`--servicenow` / `--jira`), from the CLI, GitHub Action, and web app — **available now**
- Configurable / custom ticket templates (`--ticket-template`) — **available now**
- Compact GitHub PR comments and changed-file scanner inference — **available now**
- Static HTML dashboard export (`--html-output`) — **available now**
- Live provider adapters layered on the offline observability evidence contract
- PagerDuty / Opsgenie incident-history connector
- Policy-as-code approval workflows

## Suggested GitHub topics

When publishing, add topics like:

`sre` · `devops` · `platform-engineering` · `site-reliability-engineering` · `change-management` · `risk-assessment` · `production-readiness` · `rollback` · `observability` · `terraform` · `kubernetes` · `ci-cd` · `pre-deployment` · `streamlit` · `python`

## License

Released under the [MIT License](LICENSE).

---

_Built for SRE, DevOps, Platform Engineering and Cloud Operations teams._

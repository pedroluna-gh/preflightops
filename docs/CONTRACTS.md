# Public Contracts

This document inventories the public interfaces shipped by PreflightOps.
The contract inventory itself is versioned as **Contract Set v1**. The JSON
schemas under [`schemas/`](../schemas/) are the machine-readable definitions for
the current file inputs and JSON report.

## Compatibility promise

PreflightOps follows the rules in [`COMPATIBILITY.md`](COMPATIBILITY.md). In
short: patch and minor releases may add optional fields, flags, inputs, outputs,
or rules, but must not remove or reinterpret an existing public contract without
a documented deprecation and migration path.

## CLI

Console command: `preflightops` (equivalent to `python -m preflightops.cli`).

| Flag | Required | Default | Contract |
| --- | --- | --- | --- |
| `--services` | yes | — | Service catalog YAML/JSON path |
| `--change` | yes | — | Change request YAML/JSON path |
| `--terraform` | no | none | Terraform plan/diff text path |
| `--terraform-json` | no | none | Structured `terraform show -json` plan path |
| `--k8s` | no | none | Kubernetes manifest text path |
| `--policy` | no | `default` | Built-in policy name or versioned policy YAML path |
| `--monitors` | no | none | Offline monitor inventory YAML path |
| `--changed-files` | no | none | Newline/JSON changed-file manifest for scanner inference |
| `--repository-root` | no | `.` | Checkout root for safely resolving changed paths |
| `--output` | no | `report.md` | Markdown report path |
| `--json-output` | no | none | JSON report path |
| `--html-output` | no | none | Dependency-free static HTML report path |
| `--github-comment-output` | no | none | Compact GitHub PR comment path |
| `--full-report-url` | no | none | HTTP(S) workflow/artifact link for human reports |
| `--ticket-output` | no | none | Offline Markdown ticket path |
| `--ticket-template` | no | none | YAML/JSON ticket template path |
| `--servicenow` | no | none | Opt-in ServiceNow base URL |
| `--servicenow-mapping` | no | built-in v1 | Versioned evidence-field mapping path |
| `--servicenow-change` | no | none | Existing Change number/sys_id; missing record fails closed |
| `--servicenow-attach-evidence` | no | false | Attach and deduplicate versioned JSON evidence |
| `--servicenow-dry-run` | no | false | Validate/render without credentials or network calls |
| `--servicenow-preview-output` | no | `servicenow-preview.json` | Dry-run payload path |
| `--jira` | no | none | Opt-in Jira base URL |
| `--yes`, `--assume-yes` | no | false | Waive interactive live-push confirmation |
| `--version` | no | — | Print the package version and exit |

Authenticated evidence uses a non-breaking subcommand namespace:

| Command | Contract |
| --- | --- |
| `preflightops evidence generate` | Create a signed DSSE/in-toto Evidence Contract v2 envelope; optional `--legacy-output` preserves v1 in parallel |
| `preflightops evidence verify` | Verify signature, policy/input digests, execution identity and freshness; write a machine-readable verdict |

Evidence verification exits `0` when verified, `3` when cryptographic or trust
checks reject the envelope, and `2` for invalid arguments, files or keys.

Exit codes:

- `0`: assessment completed and level is not `CRITICAL`;
- `1`: assessment completed and level is `CRITICAL`;
- `2`: input, parsing, template, integration, or report-writing error.

## Python API

The symbols exported by `preflightops.__all__` are public in Contract Set v1:

`assess_risk`, `find_service`, `RISK_LEVELS`, `RECOMMENDATIONS`,
`score_to_level`, `is_bad_rollback_plan`, `is_monitoring_plan_incomplete`,
`is_validation_plan_valid`, `scan_terraform`, `scan_kubernetes`,
`scan_terraform_json`, `load_policy_pack`, `validate_monitoring_evidence`,
`generate_markdown_report`, `generate_json_report`,
`generate_github_comment`, `generate_html_report`, `classify_changed_files`,
`load_changed_files`,
`generate_ticket_markdown`, `push_to_servicenow`, `push_to_jira`,
`prepare_servicenow_payload`, `build_servicenow_evidence`,
`load_servicenow_mapping`, `validate_servicenow_instance_url`,
`correlation_id`, `IntegrationError`, `EvidenceError`, `build_statement_v2`,
`generate_evidence_v2`, and `verify_evidence_v2`.

`preflightops.__version__` is also public. It is sourced from
`preflightops._version` and drives package metadata, CLI output, and reports.

## File schemas

- [`service-catalog-v1.schema.json`](../schemas/service-catalog-v1.schema.json)
- [`change-request-v1.schema.json`](../schemas/change-request-v1.schema.json)
- [`risk-report-v1.schema.json`](../schemas/risk-report-v1.schema.json)
- [`ticket-template-v1.schema.json`](../schemas/ticket-template-v1.schema.json)
- [`policy-pack-v1.schema.json`](../schemas/policy-pack-v1.schema.json)
- [`monitor-inventory-v1.schema.json`](../schemas/monitor-inventory-v1.schema.json)
- [`servicenow-mapping-v1.schema.json`](../schemas/servicenow-mapping-v1.schema.json)
- [`servicenow-evidence-v1.schema.json`](../schemas/servicenow-evidence-v1.schema.json)
- [`evidence-statement-v2.schema.json`](../schemas/evidence-statement-v2.schema.json)
- [`evidence-dsse-v1.schema.json`](../schemas/evidence-dsse-v1.schema.json)

Schemas intentionally allow additional properties so existing organization-
specific metadata remains valid. Fields documented as recommended rather than
required are not promoted to schema requirements in v1.

## GitHub Action

The composite action's inputs and outputs are defined in [`action.yml`](../action.yml).
Existing required inputs are `services` and `change`. All live integrations are
opt-in. The action's `fail-on` setting is independent from the CLI's fixed exit
semantics.

Structured Terraform JSON, policy packs, and monitor inventories are optional
Action inputs. They remain offline and add no credential requirements.

Changed-file detection is enabled by default only in pull-request contexts. It
uses the run-scoped GitHub token for metadata-only `filename` / `status` reads,
requires `pull-requests: read`, is bounded to 3,000 files, and degrades to the
explicit scanner inputs if the API is unavailable.

Outputs: `risk-level`, `risk-score`, `report-path`, `json-report-path`,
`ticket-path`, `html-report-path`, `github-comment-path`,
`changed-files-path`, `scanner-scope`, and `servicenow-preview-path`.

Optional authenticated-evidence outputs are `evidence-v2-path` and
`evidence-v1-path`. The Action never accepts a private key as an input; an
explicit v2 output requires `PREFLIGHTOPS_EVIDENCE_PRIVATE_KEY` in the protected
step environment.

The workflow in `.github/workflows/preflightops.yml` belongs to this source
repository and is a manually dispatched smoke/demo workflow. A consuming
repository can configure the composite action as a pull-request gate after it
adds its own service and change files.

`.github/workflows/servicenow-demo.yml` is manual-only. Its preview job has no
credentials or network calls. Its live job requires CAB-boundary acknowledgement,
an existing Change reference, and the `servicenow-demo` GitHub Environment.

## Reports

The Markdown report is a human-readable interface. The JSON report is the
machine-readable interface described by `risk-report-v1.schema.json`. In 0.2.0
both include the PreflightOps version. When changed-file inference is enabled,
JSON also contains optional `change_scope` evidence. New optional metadata may be added in
future compatible releases; consumers must ignore unknown fields.

## Offline and integration behavior

Assessment, report, and ticket generation are offline by default. Network calls
occur only when `--servicenow` or `--jira` is explicitly supplied, or their
equivalent application/Action configuration is enabled. Credential environment
variables are not part of report output and must not be logged.

Evidence v2 generation and verification are offline. See
[`EVIDENCE_CONTRACT_V2.md`](EVIDENCE_CONTRACT_V2.md) for the trust model,
migration window and fail-closed verification contract.

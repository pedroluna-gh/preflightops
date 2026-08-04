# Public Contracts

This document inventories the public interfaces shipped by PreflightOps 0.1.x.
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
| `--k8s` | no | none | Kubernetes manifest text path |
| `--output` | no | `report.md` | Markdown report path |
| `--json-output` | no | none | JSON report path |
| `--ticket-output` | no | none | Offline Markdown ticket path |
| `--ticket-template` | no | none | YAML/JSON ticket template path |
| `--servicenow` | no | none | Opt-in ServiceNow base URL |
| `--jira` | no | none | Opt-in Jira base URL |
| `--yes`, `--assume-yes` | no | false | Waive interactive live-push confirmation |
| `--version` | no | — | Print the package version and exit |

Exit codes:

- `0`: assessment completed and level is not `CRITICAL`;
- `1`: assessment completed and level is `CRITICAL`;
- `2`: input, parsing, template, integration, or report-writing error.

## Python API

The symbols exported by `preflightops.__all__` are public in Contract Set v1:

`assess_risk`, `find_service`, `RISK_LEVELS`, `RECOMMENDATIONS`,
`score_to_level`, `is_bad_rollback_plan`, `is_monitoring_plan_incomplete`,
`is_validation_plan_valid`, `scan_terraform`, `scan_kubernetes`,
`generate_markdown_report`, `generate_json_report`,
`generate_ticket_markdown`, `push_to_servicenow`, `push_to_jira`,
`correlation_id`, and `IntegrationError`.

`preflightops.__version__` is also public. It is sourced from
`preflightops._version` and drives package metadata, CLI output, and reports.

## File schemas

- [`service-catalog-v1.schema.json`](../schemas/service-catalog-v1.schema.json)
- [`change-request-v1.schema.json`](../schemas/change-request-v1.schema.json)
- [`risk-report-v1.schema.json`](../schemas/risk-report-v1.schema.json)
- [`ticket-template-v1.schema.json`](../schemas/ticket-template-v1.schema.json)

Schemas intentionally allow additional properties so existing organization-
specific metadata remains valid. Fields documented as recommended rather than
required are not promoted to schema requirements in v1.

## GitHub Action

The composite action's inputs and outputs are defined in [`action.yml`](../action.yml).
Existing required inputs are `services` and `change`. All live integrations are
opt-in. The action's `fail-on` setting is independent from the CLI's fixed exit
semantics.

Outputs: `risk-level`, `risk-score`, `report-path`, `json-report-path`, and
`ticket-path`.

The workflow in `.github/workflows/preflightops.yml` belongs to this source
repository and is a manually dispatched smoke/demo workflow. A consuming
repository can configure the composite action as a pull-request gate after it
adds its own service and change files.

## Reports

The Markdown report is a human-readable interface. The JSON report is the
machine-readable interface described by `risk-report-v1.schema.json`. In 0.1.2
both include the PreflightOps version. New optional metadata may be added in
future compatible releases; consumers must ignore unknown fields.

## Offline and integration behavior

Assessment, report, and ticket generation are offline by default. Network calls
occur only when `--servicenow` or `--jira` is explicitly supplied, or their
equivalent application/Action configuration is enabled. Credential environment
variables are not part of report output and must not be logged.


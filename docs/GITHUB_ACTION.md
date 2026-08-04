# GitHub Action Usage

PreflightOps can run as a pull-request risk gate.

The workflow bundled in this source repository is intentionally manual because
the source repository has no application-specific service catalog or change
request. Copy the example below into a consuming repository, or invoke the
composite action directly, to run on pull requests.

It can:

- read a service catalog;
- read a change request;
- optionally scan a Terraform plan;
- optionally scan Kubernetes manifests;
- generate a Markdown report;
- upload the report as an artifact;
- comment the report on the pull request;
- fail the workflow when risk is `CRITICAL`.

---

## Example workflow

Create this file:

```text
.github/workflows/preflightops.yml
```

Example:

```yaml
name: PreflightOps

on:
  pull_request:
    branches:
      - main

permissions:
  contents: read
  pull-requests: write

jobs:
  risk-review:
    name: Risk review
    runs-on: ubuntu-latest

    env:
      PREFLIGHTOPS_INSTALL: "git+https://github.com/pedroluna-gh/preflightops.git@main"
      PREFLIGHTOPS_SERVICES: services.yaml
      PREFLIGHTOPS_CHANGE: change.yaml
      PREFLIGHTOPS_TERRAFORM: tfplan.txt
      PREFLIGHTOPS_K8S: k8s.yaml
      PREFLIGHTOPS_REPORT: preflightops-report.md

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install PreflightOps
        run: pip install "$PREFLIGHTOPS_INSTALL"

      - name: Run PreflightOps risk assessment
        id: preflightops
        run: |
          set -uo pipefail

          args=(--services "$PREFLIGHTOPS_SERVICES" --change "$PREFLIGHTOPS_CHANGE")

          if [ -n "${PREFLIGHTOPS_TERRAFORM:-}" ] && [ -f "$PREFLIGHTOPS_TERRAFORM" ]; then
            args+=(--terraform "$PREFLIGHTOPS_TERRAFORM")
          fi

          if [ -n "${PREFLIGHTOPS_K8S:-}" ] && [ -f "$PREFLIGHTOPS_K8S" ]; then
            args+=(--k8s "$PREFLIGHTOPS_K8S")
          fi

          args+=(--output "$PREFLIGHTOPS_REPORT")

          set +e
          preflightops "${args[@]}"
          exit_code=$?
          set -e

          echo "exit_code=$exit_code" >> "$GITHUB_OUTPUT"

      - name: Upload risk report
        if: always() && hashFiles(env.PREFLIGHTOPS_REPORT) != ''
        uses: actions/upload-artifact@v4
        with:
          name: preflightops-report
          path: ${{ env.PREFLIGHTOPS_REPORT }}

      - name: Comment risk report on pull request
        if: always() && github.event_name == 'pull_request' && hashFiles(env.PREFLIGHTOPS_REPORT) != ''
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const marker = '<!-- preflightops-report -->';
            const body = `${marker}\n` + fs.readFileSync(process.env.PREFLIGHTOPS_REPORT, 'utf8');

            const { owner, repo } = context.repo;
            const issue_number = context.issue.number;

            const comments = await github.paginate(
              github.rest.issues.listComments,
              { owner, repo, issue_number },
            );

            const existing = comments.find((c) => c.body && c.body.includes(marker));

            if (existing) {
              await github.rest.issues.updateComment({
                owner,
                repo,
                comment_id: existing.id,
                body,
              });
            } else {
              await github.rest.issues.createComment({
                owner,
                repo,
                issue_number,
                body,
              });
            }

      - name: Fail on CRITICAL risk
        if: always()
        run: |
          if [ "${{ steps.preflightops.outputs.exit_code }}" != "0" ]; then
            echo "PreflightOps reported CRITICAL risk."
            exit 1
          fi

          echo "PreflightOps risk check passed."
```

---

## Using the composite action

Instead of the hand-rolled workflow above, you can call the bundled composite
action directly with `uses:`. It sets up Python, installs PreflightOps, runs the
assessment, and gates the job on `fail-on`.

### Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `services` | yes | — | Path to the service catalog YAML file. |
| `change` | yes | — | Path to the change request YAML file. |
| `terraform` | no | `""` | Optional Terraform plan/diff text file. |
| `k8s` | no | `""` | Optional Kubernetes manifest YAML file. |
| `output` | no | `preflightops-report.md` | Path to write the Markdown report. |
| `json-output` | no | `preflightops-report.json` | Path to write the JSON report. |
| `ticket-output` | no | `""` | Optional path to write a ServiceNow/Jira-ready change ticket summary. |
| `ticket-template` | no | `""` | Optional path to a YAML or JSON ticket template. |
| `servicenow` | no | `""` | Optional ServiceNow instance URL for opt-in live ticket push. |
| `jira` | no | `""` | Optional Jira base URL for opt-in live ticket push. |
| `assume-yes` | no | `"false"` | Skip confirmation prompts for an explicitly requested live push. |
| `fail-on` | no | `critical` | Minimum risk level that fails the action: `none`, `low`, `medium`, `high`, `critical`. |
| `python-version` | no | `3.11` | Python version to set up. |

### Outputs

`risk-level`, `risk-score`, `report-path`, `json-report-path`, and `ticket-path`
(the path of the generated ticket summary, empty when `ticket-output` was not
set).

### Safe example (offline ticket summary)

This stays fully offline — it generates the report and a copy/paste-ready change
ticket summary, with no outbound calls:

```yaml
- uses: pedroluna-gh/preflightops@v0.1.2
  with:
    services: services.yaml
    change: change.yaml
    terraform: tfplan.txt
    k8s: k8s.yaml
    output: preflightops-report.md
    json-output: preflightops-report.json
    ticket-output: preflightops-ticket.md
    fail-on: critical
```

### Advanced example (opt-in live ServiceNow / Jira push)

Live push is **opt-in** and should only be enabled in trusted workflows.
Pass the non-secret instance/base URL as an input, and provide credentials as
GitHub Actions secrets through the job's `env` block — never inline. Set
`assume-yes: true` because a CI runner has no interactive terminal to confirm the
push:

```yaml
jobs:
  risk-review:
    runs-on: ubuntu-latest
    env:
      SERVICENOW_USER: ${{ secrets.SERVICENOW_USER }}
      SERVICENOW_PASSWORD: ${{ secrets.SERVICENOW_PASSWORD }}
      JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
      JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
      JIRA_PROJECT_KEY: ${{ secrets.JIRA_PROJECT_KEY }}
    steps:
      - uses: actions/checkout@v4
      - uses: pedroluna-gh/preflightops@v0.1.2
        with:
          services: services.yaml
          change: change.yaml
          ticket-output: preflightops-ticket.md
          servicenow: https://example.service-now.com
          jira: https://example.atlassian.net
          assume-yes: true
```

Omit `servicenow` / `jira` (or leave them blank) to keep the integrations
disabled — no credentials are needed and no network call is made.

---

## Recommended repository files

Your application repository should include:

```text
services.yaml
change.yaml
tfplan.txt      # optional
k8s.yaml        # optional
```

---

## Exit codes

| Exit code | Meaning |
|---:|---|
| 0 | Risk level is not CRITICAL. |
| 1 | Risk level is CRITICAL. |
| 2 | Input, YAML, or runtime error. |

---

## Recommended workflow behavior

For early adoption, use PreflightOps as an advisory comment first.

After teams trust the scoring model, enable blocking behavior for `CRITICAL` risk.

Recommended rollout:

1. Week 1: report only.
2. Week 2: fail on CRITICAL.
3. Later: fail on HIGH for tier-0 services.

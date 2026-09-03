# Auditable Assessment Reports v1

Assessment Report v1 converts a valid Assessment Contract v1 into deterministic,
reviewer-oriented outputs. It does not calculate a new risk score, change confidence,
approve a change, contact an evidence source, or publish to a pull request or ticket.

## Outputs

The same report contract drives four views:

- canonical `assessment-report-v1` JSON for machines and audit retention;
- a complete Markdown pre-CAB review;
- a bounded pull-request summary with an optional full-artifact link;
- a bounded copy/paste ticket summary.

The legacy `risk-report-v1`, Markdown, HTML, GitHub comment and ticket renderers remain
unchanged. Consumers choose the new surface explicitly.

## 30-second review order

The complete Markdown report presents, in order:

1. technical recommendation, verdict, risk, confidence and human-decision status;
2. top blockers;
3. ERROR and UNKNOWN controls;
4. failed and passed controls;
5. freshness and provenance;
6. deterministic next actions;
7. optional Automation Details;
8. audit IDs, versions, commit and hashes.

Every human view states that a technical recommendation does not grant CAB or human
approval. A report containing ERROR or UNKNOWN remains `INDETERMINATE` with
`DO_NOT_PROCEED`; rendering cannot promote it to PASS.

## Canonical report contract

[`assessment-report-v1.schema.json`](../schemas/assessment-report-v1.schema.json) is a
strict JSON Schema 2020-12 contract. `build_auditable_report_v1` first validates the
source Assessment Contract and then produces a content-free projection with:

- source assessment identity, timestamp, producer, policy and canonical digest;
- repository, commit, run and pipeline context;
- all input hashes and all control states;
- bounded top blockers and next actions with explicit omission counts;
- evidence IDs, hashes, freshness and provenance metadata, never raw payloads;
- rendering/redaction settings and a canonical integrity hash.

`serialize_auditable_report_v1` emits stable UTF-8 canonical JSON with one trailing LF.
The report ID is a SHA-256 URN over every semantic report field except its own ID and
integrity wrapper. Repeating the same assessment and configuration produces identical
bytes.

## Python API

```python
from preflightops import (
    AuditableReportConfig,
    build_auditable_report_v1,
    render_assessment_markdown_v1,
    render_pr_summary_v1,
    render_ticket_summary_v1,
    serialize_auditable_report_v1,
)

config = AuditableReportConfig(include_automation_details=True)
report = build_auditable_report_v1(assessment_contract, config)

json_bytes = serialize_auditable_report_v1(report)
markdown = render_assessment_markdown_v1(report)
pr_summary = render_pr_summary_v1(
    report,
    "https://github.example.test/acme/service/actions/runs/42",
)
ticket_summary = render_ticket_summary_v1(report)
```

These functions perform no filesystem or network I/O.

## Offline CLI

Use explicit destinations. Existing files are refused unless `--overwrite` is supplied:

```bash
preflightops report render \
  --assessment assessment-v1.json \
  --json-output assessment-report-v1.json \
  --markdown-output assessment-report-v1.md \
  --pr-summary-output assessment-pr-summary.md \
  --ticket-summary-output assessment-ticket-summary.md \
  --full-report-url https://github.example.test/acme/service/actions/runs/42
```

At least one output path is required. Paths must be unique. The command never posts the
PR summary, writes an ITSM record or calls an API. `--without-automation-details`
removes that human section while preserving risk, confidence and decision fields.

The following bounds can be adjusted within schema-enforced ranges:

- `--max-text-length`;
- `--top-blockers-limit`;
- `--next-actions-limit`;
- `--pr-summary-max-characters`;
- `--ticket-summary-max-characters`.

## GitHub Action migration

The Action can render the new outputs after an upstream step creates Assessment
Contract v1. Set `assessment-contract` and one or more explicit
`assessment-*-output` paths. If outputs are requested without the contract, or the
contract is supplied without an output, the Action fails closed. It does not publish
the files; consumers upload or comment them under their own explicit permissions.

Existing `output`, `json-output`, `github-comment-output` and `ticket-output` behavior
is preserved.

## Redaction and Markdown safety

The versioned `preflightops-report-redaction-v1` profile normalizes control characters,
flattens embedded newlines and redacts common secret assignments, Bearer values, JWTs,
AWS access-key forms and GitHub token forms. Dynamic Markdown values escape pipes,
backticks, backslashes and HTML metacharacters. Unsafe artifact URLs are omitted; only
HTTPS URLs without credentials, query or fragment are accepted.

This is defense in depth, not a replacement for producer-side data minimization.
Callers must continue supplying only approved, non-sensitive digests and bounded
summaries.

## Privacy and retention

Raw evidence, provider payloads, plan bodies and secret values are never included.
Hashes and stable IDs can still correlate activity, so retention and access must follow
the assessment's classification. The report copies that classification and declares
`content_embedded: false`.

## Migration

1. Produce Assessment Contract v1 in shadow mode.
2. Render the new JSON and Markdown alongside existing files.
3. Validate golden/snapshot stability and downstream schema handling.
4. Move PR/ticket consumers to their new explicit paths.
5. Retain legacy outputs until each consumer has migrated.

Schema or semantic changes that are not backward compatible require a new report
version. Historical reports must not be re-sealed or silently reinterpreted.

## Rollback

Stop invoking `build_auditable_report_v1` or `preflightops report render`, and remove the
optional Action inputs. The legacy files remain available. No database, remote record,
credential or external state requires repair.

## Residual risks

- Pattern-based redaction cannot semantically identify every organization-specific
  secret; producers remain responsible for minimization.
- Approved hashes and IDs are content-free but may be correlatable.
- Scan time depends on the number of controls even though headings and compact-output
  budgets preserve the decision-first layout.
- Artifact publication, retention and access control belong to the consuming workflow.


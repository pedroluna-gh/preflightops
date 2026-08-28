# ServiceNow pre-change evidence integration

PreflightOps enriches a `change_request` with deterministic technical evidence.
It does not replace ServiceNow Change Management, authorize implementation, or
act as a CAB approver.

## Safety boundary

- Network access remains opt-in.
- Only HTTPS `*.service-now.com` origins are trusted by default. Exact custom
  domains require `SERVICENOW_ALLOWED_HOSTS`.
- Cross-origin redirects are refused.
- Mappings can write a small allowlist of evidence fields plus `u_` custom
  fields. Workflow state, approvals, assignments, scheduling, and closure fields
  are not in the allowlist. Journal fields such as `work_notes` are also rejected
  because ServiceNow cannot provide a reliable value for idempotent read-back.
- `--servicenow-change` makes the operation enrich-only: a missing record fails
  closed instead of creating a second Change.
- Lookups request at most two records and fail when identity is ambiguous.
- A manifest `change.id` is the preferred stable identity. The previous
  title-based identity remains discoverable so existing records migrate safely.
- Every write is read back and verified.
- JSON evidence is bounded, secret-scrubbed, hashed, attached, and deduplicated.
- Identical record content returns `unchanged` instead of creating write churn.

## Authentication

For a test-only demo, configure either:

1. `SERVICENOW_TOKEN` with an externally acquired OAuth bearer token; or
2. `SERVICENOW_USER` and `SERVICENOW_PASSWORD` for a dedicated, least-privilege
   integration user.

Bearer authentication is preferred. Never use a personal or administrator
account for CI. Credentials are read from the environment and are never accepted
as command-line arguments.

## Network-free preview

```bash
preflightops \
  --services examples/services-high-risk.yaml \
  --change examples/change-high-risk.yaml \
  --output report.md \
  --servicenow https://dev12345.service-now.com \
  --servicenow-change CHG0030001 \
  --servicenow-mapping examples/servicenow-field-map.yaml \
  --servicenow-attach-evidence \
  --servicenow-dry-run \
  --servicenow-preview-output servicenow-preview.json
```

Dry-run validates the target and mapping, renders the exact payload and evidence,
does not read credentials, and makes no API call.

## Protected live publication

The manual `ServiceNow pre-change evidence demo` workflow always produces a
preview first. A live run additionally requires:

- `dry_run` set to false;
- explicit CAB-boundary acknowledgement;
- approval of the `servicenow-demo` GitHub Environment;
- an existing test Change number or sys_id;
- environment secrets for bearer or Basic authentication.

Configure the `servicenow-demo` Environment with required reviewers and disable
self-review where the repository plan supports it. Do not add ServiceNow secrets
as repository-wide secrets when environment-scoped secrets are available.

The workflow is manual-only and has `contents: read`; pull requests and forks
cannot invoke its live job with secrets.

## Field mapping contract

Mapping files are versioned YAML or JSON:

```yaml
version: "1"
table: change_request
fields:
  short_description:
    source: summary
    required: true
  backout_plan:
    source: change.rollback_plan
  u_preflightops_hash:
    source: evidence_hash
```

Supported source namespaces are `result.*`, `change.*`, `source.*`, and
`evidence.*`. Built-in sources include `summary`, `ticket_markdown`,
`correlation_id`, `evidence_hash`, and `evidence_summary`. Literal values use
`value` instead of `source`.

Choice fields such as `risk` and `impact` must only be mapped after validating
their values in the target instance. PreflightOps intentionally does not guess
instance-specific choices.

## Evidence and idempotency

The attachment filename includes the first 16 characters of a semantic SHA-256.
A repeated assessment finds the existing attachment and does not upload it
again. Volatile run identifiers and timestamps do not change the semantic hash.

ServiceNow does not guarantee uniqueness of `correlation_id` by default. The
client detects ambiguity before and after a write, but a production integration
should additionally enforce a unique external Change identifier through the
organization's ServiceNow data model.

## Production-readiness boundary

This implementation is suitable for a controlled test-instance demo and a
limited enterprise pilot. Production adoption still requires instance-specific
ACL review, OAuth lifecycle automation, rate-limit sizing, data-retention review,
and an end-to-end test against the customer's ServiceNow release and business
rules.

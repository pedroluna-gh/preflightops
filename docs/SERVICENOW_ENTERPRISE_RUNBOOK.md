# ServiceNow enterprise adapter v2 runbook

## Operating boundary

The v2 adapter publishes technical assessment evidence. ServiceNow and CAB remain the
authority for Change creation policy, approval, assignment, schedule, implementation
and closure. Production live writes require the Evidence Gateway, OAuth client
credentials, a unique `u_preflightops_delivery_id`, explicit confirmation and a current
capability attestation. `create_draft` is off by default.

The current supported integration surface is the public Python API in
`preflightops.servicenow_enterprise`. The existing CLI, Action and web integration keep
their legacy v1 behavior for compatibility; they do not silently opt into v2.

## Required instance controls

Before any live use, the ServiceNow owner must provide and independently review:

1. an Evidence Gateway exposing only capability, delivery and reconciliation routes;
2. a dedicated Application User, REST API Auth Scope and field-scoped ACL/role;
3. an atomic CAS check against `sys_mod_count` for enrich operations;
4. a unique index on `u_preflightops_delivery_id`;
5. a denylist for state, approval, assignment, schedule, closure, journals and tasks;
6. a capability response bound to the approved mapping digest and allowed operations;
7. bounded rate limits, audit history, retention and alert ownership.

Basic Auth is not a v2 option. Store client credentials in an approved secret manager
or protected workload environment. Never pass them as arguments, plan data or mapping.

## Deployment sequence

1. Validate the Assessment Report v1, mapping and capability digest offline.
2. Construct the v2 plan with `dry_run=True` and retain its canonical bytes/digests.
3. Compare v1/v2 previews with `compare_servicenow_previews_v1_v2`; explain every
   deliberate field difference and confirm no workflow field exists.
4. Follow the separate sandbox procedure and obtain ServiceNow/Change owner sign-off.
5. Start production canary with enrich-only, one non-critical cohort and
   `create_draft=false`.
6. Set `dry_run=False`, `write_enabled=True`, use `evidence_gateway_v1`, then call
   `execute(plan, confirm_write=True)`. Confirmation is per execution boundary.
7. Treat only `UNCHANGED`, `UPDATED` or `CREATED_DRAFT` with `verified=true` as a
   verified delivery. Preserve every other result for reconciliation.

The caller must inject the approved host allowlist and resolver policy. Private CIDRs
are denied by default; where a private ServiceNow endpoint is intentional, allow only
the exact reviewed CIDRs. Ambient proxy variables are ignored. An explicit proxy must
be HTTPS, allowlisted and configured by the operator.

## Monitoring and incident response

Monitor outcome/error code, attempt count, duration, 429 rate, conflicts, replay
mismatches and read-back mismatches by content-free request ID. Events intentionally
contain only a target hash, not the full Change number/sys_id, tokens, headers, response
bodies or report content.

- `CONCURRENCY_CONFLICT`: do not retry blindly; obtain a fresh assessment/plan against
  the current Change version.
- `REPLAY_MISMATCH`: stop the cohort and inspect the unique delivery record and digests.
- `RATE_LIMITED`: retry only within the approved attempt/elapsed budget.
- `PARTIAL_FAILURE_UNKNOWN`: freeze retries, query reconciliation by delivery key and
  escalate to the integration owner. Never create a replacement Change.
- `VERIFICATION_MISMATCH`: disable writes immediately and preserve the gateway audit.
- auth/capability failure: do not fall back to Table API or Basic Auth.

## Abort and rollback

Abort on wrong-record evidence, forbidden-field mutation, digest/capability mismatch,
secret canary detection, unknown partial failure, error rate above the agreed canary
threshold or SLO breach.

1. Set the caller write flag and deployment policy to false.
2. Revoke/rotate the OAuth credential and disable gateway write while retaining reads.
3. Stop queued retries and reconcile all delivery keys with unknown state.
4. Preserve Change/attachment history; corrections are explicit human records.
5. Use legacy v1 only for dry-run/read-only continuity.
6. Resume only with new approved mapping/capability digests and a fresh canary decision.

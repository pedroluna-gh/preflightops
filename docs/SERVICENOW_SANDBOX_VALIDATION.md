# ServiceNow v2 sandbox validation procedure

This procedure is intentionally separate from automated repository tests. Stage 10 did
not contact a sandbox or production instance. Execute it only after a ServiceNow owner
authorizes the exact non-production instance, test Changes, identity and cleanup plan.

## Preconditions

- Dedicated non-production instance and disposable Change records.
- Evidence Gateway v1 installed with reviewed ACL, field denylist, atomic CAS and unique
  `u_preflightops_delivery_id` index.
- Dedicated OAuth Application User and REST scope; no admin, personal or Basic account.
- Approved origin/DNS/private-CIDR/proxy policy, mapping v2 digest and capability digest.
- `create_draft=false` for the first run; no real operational evidence or secrets in
  fixtures.

## ATF and contract checks

1. Prove the role can read the selected Change fields and cannot write state, approval,
   assignment, schedule, closure, journals, tasks or arbitrary `u_*` fields.
2. Prove gateway capability returns the expected mapping digest, delivery field,
   CAS/uniqueness flags and enrich-only operation set.
3. Prove one exact number/sys_id resolves to one record; missing and ambiguous lookups
   fail without gateway POST.
4. Deliver one enrich plan, verify field values, attachment/link digest, delivery key,
   target identity and incremented `sys_mod_count` by read-back and audit history.
5. Replay it and prove `UNCHANGED` with no second mutation or attachment.
6. Race two writers, change the payload under the same delivery key, and inject 429,
   503 and timeout-after-commit. Verify conflict/replay/unknown outcomes fail closed.
7. Exercise same- and cross-origin redirects, forbidden DNS/IP answers and log canaries;
   prove no credential, remote body or sensitive target appears in artifacts.
8. Only under a separate policy approval, enable both draft gates for one allowlisted
   change model. Prove the model sets initial state and the request contains no workflow
   field. Disable the flags after the test.

## Evidence to retain

Record sanitized ATF/E2E execution IDs, release/plugin versions, mapping and capability
digests, disposable Change references, result/request IDs, gateway audit IDs, reviewer,
date and rollback drill outcome. Do not retain tokens, client secrets, signed URL query
parameters, raw sensitive provider payloads or full remote response bodies.

## Exit gate

The sandbox gate is green only when ACL/denylist, target pinning, CAS, uniqueness,
read-back, replay, rate-limit, timeout reconciliation and secret-redaction checks pass.
Sandbox success does not authorize production; a protected canary decision is separate.

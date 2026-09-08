# ADR 0009: ServiceNow enterprise adapter runtime

- Status: accepted
- Date: 2026-09-03
- Scope: stage 10 only

## Context

PreflightOps must deliver Assessment Report v1 evidence to ServiceNow without taking
ownership of CAB approval or Change workflow. The legacy v1 connector is public and
must remain compatible, but its broad Table API surface is not sufficient for guarded
production writes, atomic compare-and-set, or server-enforced delivery uniqueness.

## Options considered

| Option | Benefits | Costs and risk |
| --- | --- | --- |
| Conservative: harden Table API v1 | Smallest change and easiest rollback | Retains broad records API, client-side races and legacy implicit creation |
| Balanced: call Change Management API directly | Better domain API and fewer components | Still exposes a wider write surface and cannot enforce all invariants atomically |
| Enterprise: additive v2 adapter plus Evidence Gateway | Server-side field allowlist, atomic CAS, unique delivery and auditable capability contract | Requires a scoped gateway, ACLs and unique field in each instance |

## Decision

Adopt the enterprise option. The public v2 Python API builds deterministic offline
plans and executes live writes only through `evidence_gateway_v1`. Change Management
API is used for exact read-only target lookup. `create_draft` is implemented but remains
disabled unless both the mapping and an explicit runtime feature flag allow it; it also
requires an allowlisted model and external authorization.

OAuth client credentials is the only concrete v2 authentication flow. Basic Auth stays
inside deprecated legacy v1 compatibility and is not accepted by v2. The adapter never
writes state, approval, assignment, scheduling, closure, journal or task fields.

## Consequences

- Identical report, mapping and explicit context produce identical plan bytes, request
  ID, delivery key and digests.
- Dry-run performs no DNS, credential or transport call. Missing confirmation fails
  before credential acquisition.
- A production write requires a capability attestation proving CAS, unique
  `u_preflightops_delivery_id`, mapping digest and operation/model allowlists.
- Timeout or 5xx after a possible write is reconciled before retry; unverifiable state is
  `PARTIAL_FAILURE_UNKNOWN`, never success.
- V1 remains unchanged and there is no implicit v1-to-v2 or gateway-to-Table fallback.

## Rollback

Disable v2 writes and revoke the Application User credential, preserve delivery and
reconciliation evidence, and use v1 only in dry-run/read-only mode. Do not delete an
attachment or mutate a Change automatically to undo already-audited evidence.

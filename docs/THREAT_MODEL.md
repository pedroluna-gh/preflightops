# Threat model

## Scope and trust boundaries

The model covers repository inputs, GitHub Actions, policy packs, generated
reports, optional ServiceNow/Jira calls and released packages. GitHub, ITSM and
future governance services are separate trust boundaries. Pull-request content
and all parsed manifests are untrusted.

## Protected assets

- ServiceNow/Jira credentials and integration identity.
- Policy integrity and rule ownership.
- Evidence authenticity, confidentiality and retention.
- Release artifacts and their provenance.
- CAB/Change workflow authority.
- Availability and deterministic behavior of the risk gate.

## Principal threats and required controls

| Threat | Control | Verification |
| --- | --- | --- |
| Untrusted PR executes with secrets | No `pull_request_target`; live publication is manual/environment protected | Workflow contract tests |
| Policy weakened by evaluated team | Signed central bundle, independent CODEOWNERS and mandatory rules | Policy lineage and negative tests |
| Evidence altered after assessment | Digest plus signed attestation bound to commit/workflow/policy | Offline verification and tamper tests |
| Replay against another Change | Change/service/environment scope and issued/expiry metadata | Replay fixtures |
| SSRF or credential forwarding | HTTPS origin validation, custom-host allowlist and cross-origin redirect refusal | Integration security tests |
| Unauthorized CAB mutation | Evidence-field allowlist and explicit denylist | Negative mapping tests and ServiceNow ATF/E2E |
| Duplicate/racing publication | Stable external id, ambiguity rejection, read-back and attachment digest | Concurrent integration tests |
| Sensitive plan/report leakage | Key redaction, bounded payloads, classification and retention policy | DLP fixtures and log tests |
| Compromised dependency/action | Frozen lock, dependency review, audit and immutable action SHAs | CI and Scorecard |
| Compromised release | Protected tag, build-once workflow, SBOM, checksums and GitHub attestation | `gh attestation verify` |
| Gate unavailable | Explicit failure classification, timeouts, retry policy and emergency external break-glass | Resilience exercises |

## Assumptions and residual risks

PreflightOps is decision support, not a security boundary and cannot prove a
change is safe. A malicious repository administrator can alter local workflows;
enterprise enforcement therefore belongs in organization rulesets and reusable
workflows. Hashes provide integrity comparison but not producer authenticity;
Evidence Contract v2 must add signed attestations. Basic Auth remains test-only.

Review this document for every change involving parsing, policy, workflow
permissions, credentials, external writes, evidence or release infrastructure.

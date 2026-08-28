# Enterprise governance baseline

## Product charter

PreflightOps is an enterprise pre-CAB technical evidence assurance layer. It
evaluates change readiness and produces deterministic evidence for existing
change-management systems. It is not the Change of Record and it never acts as
an approver.

Success is measured by evidence completeness, reduced CAB rework, lower escaped
change failure, explainable policy decisions and zero unauthorized ITSM writes.

## Authority boundary

PreflightOps may read technical context and enrich an existing Change with
allowlisted evidence. ServiceNow or Jira remains authoritative for approval,
assignment, scheduling, state transitions and closure. CAB, Change Management
or an explicitly authorized automated policy retains the decision.

Standard, Normal and Emergency Change classifications are accepted as context;
PreflightOps does not reclassify or authorize them. Emergency break-glass must
be granted by an external authority, expire and require post-implementation
review.

## Minimum RACI

| Capability | Responsible | Accountable | Consulted |
| --- | --- | --- | --- |
| Roadmap and outcome metrics | Product Owner | Platform/SRE leader | Change, Security, Audit |
| Engine and delivery | Platform Engineering | Engineering lead | SRE and application teams |
| Secure SDLC and release | DevSecOps | Security/Engineering lead | Product and Audit |
| Policy definition | SRE/Change policy owners | Change Enablement lead | Security and service owners |
| Waiver authorization | Independent risk authority | Change/Risk owner | Security and service owner |
| ServiceNow/CMDB | ServiceNow platform team | ITSM owner | SRE, Change and Security |

The author of an evaluated change must not be the sole approver of the policy,
waiver or external publication that affects that change. The repository's
initial individual CODEOWNERS entries are a bootstrap control, not sufficient
segregation for enterprise GA; replace them with independent organization teams.

## Adoption gates

1. Report-only and offline baseline.
2. Signed central policy in non-blocking comparison mode.
3. Blocking only after false-positive review and named ownership.
4. ServiceNow test-instance preview and enrich-only publication.
5. Canary across 5, then 25 repositories.
6. Business-unit rollout only after SLO and rollback exercises.

Every gate needs an abort signal, previous known-good version and evidence of
approval by the accountable owner.

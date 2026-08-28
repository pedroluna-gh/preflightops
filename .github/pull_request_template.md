## Outcome

Describe the operational or product result, not only the implementation.

## Risk and compatibility

- [ ] Public Contract Set v1 remains compatible, or migration/dual-read is documented.
- [ ] Offline/default execution remains free of unrequested network calls.
- [ ] ServiceNow/Jira/CAB authority boundaries remain unchanged.
- [ ] Threat-model delta has been reviewed.
- [ ] Sensitive-data and log-output impact has been reviewed.

## Verification

- [ ] Tests cover success, failure and fail-closed behavior.
- [ ] Local quality gates pass.
- [ ] Security/dependency findings are resolved or have a reviewed, expiring exception.
- [ ] Documentation and operator runbooks are updated.

## Rollout and rollback

State the canary scope, abort signal, rollback procedure and last known-good version.

## External writes

List every external system and field this change may write. Write `none` when it
is read-only/offline. Changes to approval, assignment, schedule, workflow state
or closure are prohibited for the PreflightOps ServiceNow evidence profile.

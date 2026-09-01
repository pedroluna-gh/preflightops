# Compatibility and Deprecation Policy

PreflightOps uses Semantic Versioning for package releases and separately
versions its machine-readable contracts.

## Supported surfaces

Compatibility applies to documented CLI flags and exit codes, exported Python
symbols, valid v1 input documents, JSON report fields, composite Action inputs
and outputs, and the offline-by-default behavior.

Evidence Contract v2 is additive. During the v0.6 compatibility window,
`--legacy-output` can emit the existing v1 package beside the signed v2 DSSE
envelope. Existing ServiceNow v1 attachment behavior remains the default.

Policy Pack v1 remains valid and preserves its historical scoring behavior.
Policy Bundle v2 is additive and opt-in. Active v2 bundles require an Ed25519
trust pin; unsigned drafts are accepted only by lint/diff/simulation. Waiver
Contract v1 adds annotations and a decision record but never changes the risk
score, the CLI critical-risk exit code, or the Action `fail-on` result.

Assessment Contract v1 is additive. `adapt_legacy_assessment()` consumes but
does not mutate `risk-report-v1`; the legacy JSON, CLI, Action outputs,
ServiceNow evidence, and Evidence Contract v2 remain available. The assessment
adapter has its own version and records `legacy_output_preserved: true`.
Consumers may migrate independently and roll back by disabling only the new
contract path.

## Compatible changes

Patch or minor releases may:

- add optional fields, flags, Action inputs/outputs, rules, or report metadata;
- accept new input forms while retaining existing valid forms;
- fix a false positive or false negative when the behavioral change is called
  out in the changelog and covered by regression tests;
- add opt-in integrations that do not alter the offline path.

Consumers of JSON contracts must ignore unknown fields.

## Breaking changes

Removing or renaming a public field, flag, output, exit code, exported symbol, or
valid input form is breaking. Reinterpreting an existing value in a way that can
change a deployment decision is also breaking unless shipped as a new policy or
schema version.

Before a breaking change:

1. document the replacement and operational impact;
2. provide a compatibility adapter where practical;
3. emit a deprecation warning that does not expose sensitive data;
4. retain the old behavior for at least one documented release window;
5. add migration and rollback instructions;
6. test old and new contracts side by side.

Because the project is still in `0.x`, a minor version may contain a planned
breaking change, but the migration requirements above still apply. Patch
releases must remain backward compatible.

## Security exception

A vulnerable interface may be disabled sooner when continued compatibility
would expose credentials, sensitive evidence, or unsafe remote writes. The
release must document the security reason, affected versions, mitigation, and
rollback limitations.


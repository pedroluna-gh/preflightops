# Security workflow maintenance — 2026-11-21

## Scope

Refresh the immutable action pins proposed in PRs #26, #27 and #29 as a
separate change after dependency remediation in PR #53. No workflow receives
additional permissions, no quality gate is removed, and no release is run.

| Action | Version | Immutable commit | Reason |
| --- | --- | --- | --- |
| astral-sh/setup-uv | 10.1.0 | bec219d24cd3e171d82865faccec33120bb574f4 | Download checksum verification and upstream security improvements |
| actions/dependency-review-action | 5.0.0 | a1d282b36b6f3519aa1f3fc636f609c47dddb294 | Upstream security fixes and supported Node 24 runtime |
| ossf/scorecard-action | 2.4.4 | 2d1146689b8cda280b9bc96326124645441f03bc | Updated Scorecard 5.5.0 analysis |

The uv executable remains pinned to 0.12.1, independently of its setup action.
The dependency review action requires an Actions runner at least 2.327.1;
GitHub-hosted runners are verified through the PR workflow execution.
Self-hosted users must check their runner version before adopting this pin.

Upstream evidence: [setup-uv release](https://github.com/astral-sh/setup-uv/releases/tag/v10.1.0),
[dependency-review release](https://github.com/actions/dependency-review-action/releases/tag/v5.0.0),
[Scorecard release](https://github.com/ossf/scorecard-action/releases/tag/v2.4.4).

## Verification and boundaries

Local immutable-pin, least-privilege, release, CI and composite Action contracts:
54 tests passed. Full remote CI and security checks on the final head remain
the merge gate; record their URLs in the PR closure evidence. A release-path
configuration check is not evidence of a production release execution.

These action updates do not resolve governance findings by themselves.
At inspection time, five open Scorecard alerts concern Code-Review,
Branch-Protection, SAST, Security-Policy and CII-Best-Practices. No alert is
dismissed merely to obtain a clean dashboard. Single-maintainer review remains
distinct from independent review; existing access and approval settings stay
unchanged.

Other major tooling upgrades require their own compatibility review. In
particular, PR #38's setuptools 84.0.0 proposal predates the patched 84.1.0
pin and must not downgrade it. This change does not adopt that proposal.

## Rollback

Revert only the workflow pin changes through a reviewed PR, retaining the
patched Python dependency lock and license binding from PR #53. Repeat
workflow contract tests and CI; record any restored upstream security
limitations. Do not restore mutable refs, weaken permissions or disable
scanning to accommodate a runner incompatibility.

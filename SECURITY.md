# Security Policy

PreflightOps is designed to help teams identify risky production changes before deployment.

Because it may process operational metadata, Terraform plans, Kubernetes manifests, service catalogs, and change requests, users should treat inputs carefully.

---

## Supported versions

PreflightOps is currently in early development.

| Version | Supported |
|---|---|
| 0.4.x | Yes |
| 0.3.x | Yes |
| 0.2.x | Security fixes only |
| 0.1.x | No |

### Support and end-of-life process

This matrix is the current maintenance commitment, not proof that every patch
has been backported. A security release checklist must name each affected
supported line and its patch, mitigation or explicitly unresolved status.
Do not silently remove an older line from support to avoid a finding.

The maintainer announces EOL at least 90 calendar days before withdrawing an
existing support commitment, with the replacement line, migration notes and
last available patch. Until that notice completes, the matrix remains binding.
Unsupported versions receive upgrade guidance rather than a promise of fixes.
Emergency mitigation and disclosure follow the response targets below.

### Security and license exceptions

`security/exceptions.json` starts with no exceptions. Any proposed exception
requires a reviewed PR with finding identifier, exact affected component/version
scope, responsible owner, independent approver, reason, compensating control,
non-sensitive evidence reference, creation and expiry timestamps. Maximum life
is 90 days; renewals require a new review, not a silent date extension.

CI and release validate this registry at current UTC time. An expired,
incomplete, future-dated or self-approved record fails validation. The optional
`--at` argument is for historical audit, never current release eligibility.
Names in a record do not prove reviewer identity: protected review and evidence
must establish that separately. Registry validity does not suppress pip-audit,
CodeQL, secret-scanning or dependency-review findings. Any narrowly scoped
scanner exception would require a separate reviewed change; none is enabled.

The current dependency-review policy rejects the listed AGPL variants in
`.github/workflows/security.yml`. This is a project distribution policy, not
legal advice about those licenses. New or changed dependencies require SPDX
license identification and review of distribution obligations. Unknown or
ambiguous licenses must be resolved or explicitly reviewed before release;
dependency-review success alone does not prove the complete inventory is clear.
Retain license notices and inventory with the release evidence. Optional and
build dependencies are included in the review, not only default runtime packages.

---

## Reporting a vulnerability

Please report security issues privately.

Use GitHub private vulnerability reporting / Security Advisories for this
repository when available. Do not include live credentials or customer evidence
in the initial report; arrange a protected transfer channel with the maintainer
when a reproducer requires sensitive material.

Otherwise, contact the maintainer directly.

Do not open public issues for vulnerabilities involving:

- credential exposure;
- secret handling;
- unsafe parsing;
- command execution;
- sensitive report output;
- workflow permission abuse.

## Response targets

| Severity | Initial acknowledgement | Target mitigation or published plan |
| --- | --- | --- |
| Critical | 1 business day | 7 calendar days |
| High | 2 business days | 14 calendar days |
| Medium | 5 business days | 30 calendar days |
| Low | 10 business days | Next planned release |

Targets begin after a report can be reproduced and classified. When a safe fix
cannot be shipped within the target, the maintainer publishes an interim
mitigation, affected-version range and next update date without exposing an
active exploit.

---

## Sensitive data warning

Do not paste real secrets into PreflightOps.

Avoid uploading:

- API keys
- tokens
- passwords
- private keys
- kubeconfigs
- cloud credentials
- customer data
- internal URLs
- incident data with confidential details

Terraform plans and Kubernetes manifests can contain sensitive values. Review before sharing or committing them.

---

## Current security model

PreflightOps currently:

- runs locally;
- does not require a database;
- does not call external APIs during the default offline assessment path;
- can read bounded filename/status metadata from GitHub in pull-request Action
  runs; it never requests patches and can be disabled with
  `auto-detect-changes: false`;
- calls ServiceNow or Jira only when a live integration is explicitly enabled;
- validates ServiceNow HTTPS origins before reading credentials, refuses
  cross-origin redirects, and requires an explicit allowlist for custom hosts;
- restricts ServiceNow mappings to pre-change evidence fields, verifies live
  writes, and never maps workflow state or approvals;
- requires the v2 Evidence Gateway, server CAS, unique delivery identity, OAuth,
  explicit confirmation and read-back for production v2 writes; v2 never falls
  back to Table API or Basic Auth;
- can generate an opt-in Ed25519-signed DSSE Evidence Contract v2 locally and
  verify its signature, policy/input digests, identity pins and freshness
  without a network call;
- does not send data to AI services;
- does not require authentication;
- produces local Markdown, JSON, static HTML, and PR-comment reports.

This makes it simple to audit, but it also means users are responsible for controlling where input files and reports are stored.

---

## GitHub Actions permissions

The example GitHub Action requests:

```yaml
permissions:
  contents: read
  pull-requests: write
```

`pull-requests: read` is enough for changed-file detection. `write` is needed
only when the consuming workflow publishes the generated comment.

If you do not need PR comments, remove `pull-requests: write`.

The source repository additionally runs CodeQL, dependency review and OpenSSF
Scorecard. Release jobs alone receive `contents: write`, `id-token: write` and
`attestations: write`; they are environment-protected and execute only for
semantic-version tags. External actions are pinned to full commit SHAs and kept
current through reviewed dependency pull requests.

---

## Recommended safe usage

- Run PreflightOps on sanitized examples first.
- Avoid committing generated reports if they contain sensitive information.
- Review Terraform plans before storing them in the repository.
- Avoid using production secrets in Kubernetes examples.
- Prefer placeholder values in documentation and tests.
- Keep ServiceNow credentials in a protected GitHub Environment and use a
  dedicated least-privilege integration identity.
- Preview ServiceNow payloads with `--servicenow-dry-run` before live publication.
- For v2, inject an exact host/DNS policy and short-lived OAuth provider only after
  plan validation; deploy and attest the gateway/ACL/unique index independently.
- Treat generated evidence as operational data and apply appropriate retention
  and access controls in ServiceNow.
- Keep `PREFLIGHTOPS_EVIDENCE_PRIVATE_KEY` only in a protected environment or
  approved secret broker, restrict it to the signing job, rotate it, and
  distribute the public trust key independently from evaluated repositories.
- Pin repository, commit, workflow, policy digest and freshness when verifying
  evidence; signature validity alone does not authorize CAB approval.

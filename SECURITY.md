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
- Treat generated evidence as operational data and apply appropriate retention
  and access controls in ServiceNow.
- Keep `PREFLIGHTOPS_EVIDENCE_PRIVATE_KEY` only in a protected environment or
  approved secret broker, restrict it to the signing job, rotate it, and
  distribute the public trust key independently from evaluated repositories.
- Pin repository, commit, workflow, policy digest and freshness when verifying
  evidence; signature validity alone does not authorize CAB approval.

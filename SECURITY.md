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

If this project is hosted on GitHub, use GitHub Security Advisories when available.

Otherwise, contact the maintainer directly.

Do not open public issues for vulnerabilities involving:

- credential exposure;
- secret handling;
- unsafe parsing;
- command execution;
- sensitive report output;
- workflow permission abuse.

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

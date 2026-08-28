# Evidence data governance

## Classification

| Class | Examples | Default treatment |
| --- | --- | --- |
| Public | Product version, public schema ids, generic rule ids | May appear in public documentation |
| Internal | Service name, repository, owner group, risk score | Limit to engineering/ITSM participants |
| Confidential | Internal URLs, topology, business impact, plan details | Redact/minimize and store only where required |
| Secret/Restricted | Tokens, passwords, private keys, customer data | Reject or scrub; never include in evidence |

Terraform plans, Kubernetes manifests and change descriptions are untrusted and
may contain Confidential or Restricted data even when their filename appears
safe.

## Collection and minimization

- Collect metadata needed to explain a finding, not complete source documents.
- Preserve stable ids and hashes when raw content is not required.
- Use allowlists for external payloads and logs.
- Never place credentials, authorization headers or secret environment values in
  reports, exceptions, workflow summaries or errors.
- Future central storage references evidence by digest and ITSM id by default;
  it must not duplicate full plans without explicit policy.

## Retention and access

Local reports inherit repository/workflow controls. GitHub artifacts and ITSM
attachments require explicit retention agreed with Security, Change and Audit.
The reference workflows use finite retention and sanitized examples. Production
deployments must define data owner, retention, deletion, legal hold, export and
regional-residency requirements before live adoption.

## Incident handling

If evidence exposes Restricted data: stop publication, revoke affected
credentials, restrict or remove the exposed artifact through the authoritative
platform, preserve incident evidence, notify the data owner and complete a root
cause correction. Do not paste exposed values into an issue.

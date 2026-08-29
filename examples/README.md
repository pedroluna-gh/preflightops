# PreflightOps Examples

This directory contains example inputs for three risk scenarios:

| Scenario | Files | Expected level |
|---|---|---|
| Low risk | `services-low-risk.yaml`, `change-low-risk.yaml` | LOW |
| High risk | `services-high-risk.yaml`, `change-high-risk.yaml` | HIGH |
| Critical risk | `services-critical-risk.yaml`, `change-critical-risk.yaml`, `terraform-critical.txt`, `k8s-risk.yaml` | CRITICAL |

---

## Low risk example

A staging deployment for a medium-criticality internal reporting service.

```bash
preflightops \
  --services examples/services-low-risk.yaml \
  --change examples/change-low-risk.yaml \
  --output report.md
```

---

## High risk example

A production deployment for a high-criticality checkout API.

The rollback plan exists, but monitoring is incomplete and validation steps are missing.

```bash
preflightops \
  --services examples/services-high-risk.yaml \
  --change examples/change-high-risk.yaml \
  --output report.md
```

---

## Critical risk example

A production infrastructure change for a critical payments service.

Risk signals include:

- missing rollback plan;
- missing runbook;
- missing monitoring plan;
- missing validation plan;
- Terraform IAM changes;
- Terraform database destroy action;
- Kubernetes Secret change;
- Deployment missing readiness/liveness probes.

```bash
preflightops \
  --services examples/services-critical-risk.yaml \
  --change examples/change-critical-risk.yaml \
  --terraform examples/terraform-critical.txt \
  --k8s examples/k8s-risk.yaml \
  --output report.md \
  --json-output report.json
```

The CLI should return exit code `1` for `CRITICAL` risk.

---

## Policy governance examples

`policy-context-production.yaml` is a sanitized overlay-resolution context.
The governed draft bundle is under
`policy-packs/enterprise-example-v2.yaml`; lint, diff and simulate it before
signing. `waiver-example-v1.draft.yaml` is intentionally unsigned and contains
only demo identities, references and a placeholder policy digest. Replace every
scope value, obtain an independent approver, then sign and verify it as
documented in `docs/POLICY_GOVERNANCE_V2.md`.

# PreflightOps Risk Model

PreflightOps calculates deployment risk by combining:

1. Service catalog controls
2. Change request completeness
3. Change type
4. Terraform risk signals
5. Kubernetes risk signals

The result is a score from `0` to `100`.

---

## Risk levels

| Score | Level | Meaning |
|---:|---|---|
| 0–30 | LOW | Normal deployment process is usually acceptable. |
| 31–60 | MEDIUM | Proceed with caution and owner review. |
| 61–80 | HIGH | Senior review recommended before deployment. |
| 81–100 | CRITICAL | Deployment should be blocked until gaps are resolved. |

---

## Philosophy

PreflightOps is not trying to replace human judgment.

It helps SRE, DevOps, and Platform teams make change risk visible before production impact happens.

The goal is to reduce ambiguity before deployment by asking:

- Is the service critical?
- Is there a clear owner?
- Is there a valid rollback plan?
- Is monitoring ready?
- Is post-deploy validation defined?
- Is the change touching risky infrastructure?
- Is Kubernetes exposing risky runtime behavior?
- Is there enough evidence to proceed safely?

---

## Service controls

PreflightOps checks whether the service has basic operational controls:

| Rule | Risk |
|---|---|
| Production change | Production changes are inherently higher risk. |
| Critical service | High/critical services have stronger business impact. |
| Missing owner | No clear accountable team/person. |
| Missing runbook | Operators may not know how to respond. |
| Missing business impact | Stakeholders may not understand the consequence of failure. |
| Missing rollback plan | Recovery path is unclear. |
| Missing monitoring plan | Teams may not detect failure quickly. |
| Missing validation plan | Teams may not know if the change succeeded. |

---

## Change type rules

Some change types carry higher risk by default:

| Change type | Reason |
|---|---|
| `database` | Data integrity and rollback are often complex. |
| `security` | Access, identity, and exposure risks. |
| `network` | Connectivity and blast radius risks. |
| `infrastructure` | Foundational platform changes can affect many systems. |

---

## Terraform scanners

The deprecated legacy scanner accepts human-readable plan/diff text.
`--terraform-json` selects bounded, fail-closed resource/action parsing for saved
plans generated with `terraform show -json`. The parser validates JSON format 1.x,
distinguishes both ordered replacement variants from irreversible destroy, removes
sensitive/unknown leaves before evaluation, and emits deterministic resource-level
evidence. JSON failures never fall back silently to keyword scanning. See the
[Terraform Plan JSON contract](TERRAFORM_PLAN_JSON.md).

Examples:

| Signal | Why it matters |
|---|---|
| IAM policy / role changes | Can expand access or break permissions. |
| Security group / firewall changes | Can expose services or block traffic. |
| Database resources | May affect persistence or availability. |
| Destroy / delete actions | Can remove production resources. |
| Public IP exposure | May create external exposure. |
| DNS changes | Can affect routing and availability. |
| KMS changes | Can affect encryption, secrets, or access. |

---

## Kubernetes object scanner

The Kubernetes scanner parses multi-document YAML and checks each object and
container independently for signals such as:

| Signal | Why it matters |
|---|---|
| Deployment changes | Runtime behavior may change. |
| StatefulSet changes | Stateful workloads are harder to roll back. |
| Ingress changes | External routing exposure. |
| NetworkPolicy changes | Connectivity or isolation changes. |
| Secret changes | Sensitive configuration risk. |
| LoadBalancer exposure | Public exposure risk. |
| Replicas set to zero | Availability risk. |
| Missing readinessProbe | Traffic may be sent before the app is ready. |
| Missing livenessProbe | Failed containers may not self-heal. |

---

## Current limitations

PreflightOps provides structured Terraform/Kubernetes parsing, but it is not a
full infrastructure graph, admission controller, or policy engine.

It does not yet:

- Resolve Terraform provider schemas or cross-resource dependency graphs.
- Resolve Kubernetes overlays, Helm templates, or cluster admission state.
- Connect to GitHub, PagerDuty, Datadog, or Grafana directly.
- Use historical incident data.
- Use AI to generate rollback or validation plans.
- Replace CAB, change advisory, or production readiness approval processes.

Those are good future roadmap items.

PreflightOps can generate ServiceNow/Jira-ready change summaries and can optionally push them to ServiceNow or Jira when explicitly enabled.

It does not yet provide full ITSM workflow orchestration, advanced field mapping, enterprise approval-state modeling, or deep ServiceNow/Jira workflow customization.

---

## Suggested future improvements

- Terraform provider-schema-aware semantic analysis
- Kubernetes overlay and admission-state analysis
- GitHub PR comment integration
- Stronger ServiceNow / Jira workflow mapping and API hardening
- PagerDuty / Opsgenie incident history lookup
- Optional live monitor-provider verification (offline inventory validation is available)
- OpenTelemetry signal validation
- AI-assisted risk explanation
- Policy-as-code support
- Organization-specific governance packs beyond the shipped industry baselines

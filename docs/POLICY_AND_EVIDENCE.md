# Structured infrastructure, policy packs, and observability evidence

PreflightOps can evaluate machine-readable infrastructure changes and apply an
explicit organizational risk policy without making network calls.

## Terraform JSON

Generate the saved plan and structured representation:

```bash
terraform plan -out=tfplan
terraform show -json tfplan > tfplan.json
preflightops --services services.yaml --change change.yaml \
  --terraform-json tfplan.json --output report.md
```

The parser validates Terraform JSON format 1.x and evaluates each
`resource_changes` entry, its address/type/provider, ordered lifecycle actions,
and allowlisted post-change predicates. It distinguishes both replacement orders
from an irreversible destroy and reports deterministic resource-level evidence
for IAM, firewall, database, public exposure, DNS, and encryption-key changes.
Sensitive and unknown leaves are removed before rule evaluation. Invalid,
oversized, excessively deep, errored or semantically unknown plans fail the
assessment with exit code 2 and never fall back to text. Full limits, migration
and evidence fields are documented in
[`TERRAFORM_PLAN_JSON.md`](TERRAFORM_PLAN_JSON.md).

## Kubernetes objects

`--k8s` parses multi-document Kubernetes YAML and `List` objects. Each workload
and each container is evaluated independently for probes and resource
requests/limits. Service LoadBalancers, Ingress, Secrets, NetworkPolicies,
StatefulSets, DaemonSets, Jobs/CronJobs, PodDisruptionBudgets, dangerous pod
settings, and zero replicas produce explainable object/field-level findings.
Invalid or incomplete YAML fails closed with exit code 2 and never activates
text matching. Secret payloads are removed before rules execute. Limits,
invariants, migration, the explicit `scan_kubernetes_legacy` adapter and
rollback are documented in
[`KUBERNETES_MANIFESTS.md`](KUBERNETES_MANIFESTS.md).

## Policy packs

Use a built-in pack:

```bash
preflightops ... --policy fintech
```

Available packs are `saas`, `fintech`, `ecommerce`, `healthcare`,
`critical-platform`, and `startup`. Copy the examples under `policy-packs/` to
customize them. A policy pack uses the versioned
`schemas/policy-pack-v1.schema.json` format:

```yaml
version: "1"
name: payments
risk_weights:
  missing-rollback-plan: 45
  terraform-iam-policy-change: 40
risk_level_thresholds: {low: 30, medium: 60, high: 80}
monitoring:
  minimum_enabled_monitors: 2
  required_providers: [prometheus]
```

Overrides are keyed by stable finding id. The report preserves the original
weight as `default_score` when an override applies. Invalid weights or unordered
thresholds fail closed with exit code 2. Omitting `--policy` selects `default`,
which preserves the historical scoring model.

Policy Pack v1 remains the compatibility format. Enterprises that need signed
ownership, effective dates, hierarchical context, mandatory controls,
pre-activation diff/simulation, or independently verified waivers should use
the additive [Policy Bundle v2 governance contract](POLICY_GOVERNANCE_V2.md).

## Offline monitor inventory

Reference monitor ids from the change request:

```yaml
change:
  monitoring_plan:
    dashboards: [https://grafana.example.com/d/checkout]
    alerts: [CheckoutHighErrorRate]
    monitor_ids: [checkout-latency, checkout-error-rate]
```

Then provide `--monitors examples/monitors.yaml`. Inventory providers include
Datadog, Grafana, Prometheus, Zabbix, and GCP Cloud Monitoring. PreflightOps
checks dashboard URL syntax, referenced monitor existence/enabled state, policy
minimums, and required providers. It does not contact provider APIs or require
secrets; future live adapters can consume the same stable ids without changing
the offline contract.

## Safe adoption

1. Add structured inputs in report-only mode.
2. Compare results against existing CAB/change-review outcomes.
3. Select or customize a policy pack and version it with the service repository.
4. Add monitor inventory ids from authoritative IaC/observability catalogs.
5. Enable blocking only after false-positive review and ownership are defined.

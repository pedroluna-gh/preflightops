# PreflightOps Input Schema

PreflightOps uses two required YAML files:

1. `services.yaml` — describes the service catalog.
2. `change.yaml` — describes the proposed production change.

Optional inputs:

3. Terraform plan or diff text.
4. Kubernetes manifest YAML.

---

## Service Catalog

Example:

```yaml
services:
  - name: checkout-api
    description: Handles customer checkout flow
    owner: payments-team
    criticality: high
    tier: tier-1
    environment: production
    cloud_provider: aws
    runtime: kubernetes
    runbook: runbooks/checkout-api.md
    rollback_required: true
    monitoring_required: true
    approval_required: true
    dependencies:
      - auth-service
      - postgres
      - redis
    business_impact: Customers may be unable to complete checkout
```

### Fields

| Field | Required | Description |
|---|---:|---|
| `name` | Yes | Unique service name. Must match `change.service`. |
| `description` | No | Short description of the service. |
| `owner` | Recommended | Team or person accountable for the service. |
| `criticality` | Recommended | `low`, `medium`, `high`, or `critical`. |
| `tier` | No | Internal tier such as `tier-0`, `tier-1`, etc. |
| `environment` | Recommended | Usual environment where the service runs. |
| `cloud_provider` | No | AWS, GCP, Azure, on-prem, hybrid, etc. |
| `runtime` | No | Kubernetes, VM, serverless, bare metal, etc. |
| `runbook` | Recommended | Path or URL to the operational runbook. |
| `rollback_required` | No | Whether rollback evidence is expected. |
| `monitoring_required` | No | Whether monitoring evidence is expected. |
| `approval_required` | No | Whether senior approval is required. |
| `dependencies` | No | List of upstream/downstream dependencies. |
| `business_impact` | Recommended | Plain-English description of business impact. |

---

## Change Request

Example:

```yaml
change:
  id: CHG-200
  title: Update checkout API deployment
  service: checkout-api
  environment: production
  change_type: deployment
  change_class: normal
  requested_by: pedro
  description: Deploy new checkout API version with payment timeout improvements
  rollback_plan: >-
    Roll back to checkout-api:3.1.0 using the production deploy pipeline if the
    5xx rate exceeds 1% in the first 30 minutes. Owner: payments-team.
    Estimated rollback time: 10 minutes.
  monitoring_plan:
    dashboards:
      - https://grafana.example.com/d/checkout
    alerts:
      - checkout-api-5xx-rate
    validation_window: 30 minutes
    success_criteria:
      - 5xx rate below 1%
      - p95 latency below 500ms
  validation_plan:
    - Confirm smoke tests pass
    - Confirm error rate remains below threshold
    - Confirm rollback pipeline is available
```

### Fields

| Field | Required | Description |
|---|---:|---|
| `id` | Recommended | Change identifier. |
| `title` | Recommended | Human-readable change title. |
| `service` | Yes | Must match a service in `services.yaml`. |
| `environment` | Recommended | `production`, `staging`, etc. |
| `change_type` | Recommended | `deployment`, `infrastructure`, `database`, `security`, or `network`. |
| `change_class` | Recommended for Policy v2 | External ITSM classification: `normal`, `standard`, or `emergency`. PreflightOps does not reclassify or approve it. |
| `requested_by` | Recommended | Person or team requesting the change. |
| `description` | Recommended | What is being changed and why. |
| `rollback_plan` | Required for production quality | Clear rollback action, trigger, owner, and estimated time. |
| `monitoring_plan` | Recommended | Dashboards, alerts, validation window, logs, success criteria. |
| `validation_plan` | Recommended | Post-deploy validation steps. |

---

## Good rollback plan

A useful rollback plan should answer:

- What exact action will be taken?
- What condition triggers rollback?
- Who owns the rollback?
- How long should rollback take?
- How will success be validated?

Example:

```yaml
rollback_plan: >-
  Redeploy previous container image checkout-api:3.1.0 using the production
  deploy pipeline if 5xx rate exceeds 1% during the first 30 minutes.
  Owner: payments-team. Estimated rollback time: 10 minutes.
```

---

## Monitoring plan

A complete monitoring plan should include at least two of:

- dashboards
- alerts
- validation window
- success criteria
- logs

Example:

```yaml
monitoring_plan:
  dashboards:
    - https://grafana.example.com/d/checkout
  alerts:
    - checkout-api-5xx-rate
  validation_window: 30 minutes
  success_criteria:
    - 5xx rate below 1%
    - p95 latency below 500ms
```

---

## Validation plan

Validation steps should be explicit and observable.

Example:

```yaml
validation_plan:
  - Confirm deployment completed successfully
  - Confirm application health endpoint returns 200
  - Confirm 5xx rate remains below 1%
  - Confirm p95 latency remains below 500ms
  - Confirm no new critical alerts fired
```

---

## Structured semantic controls v1

The legacy fields above remain accepted unchanged. Consumers that need
deterministic semantic sufficiency, evidence confidence, and expiry can adopt the
strict additive schema
[`semantic-change-controls-v1.schema.json`](../schemas/semantic-change-controls-v1.schema.json).
It requires explicit applicability, owner, duration, success criteria,
observable steps, and plan-specific action/trigger or dashboard/alert references.

The content-free result follows
[`semantic-validation-v1.schema.json`](../schemas/semantic-validation-v1.schema.json).
See [`SEMANTIC_VALIDATION_V1.md`](SEMANTIC_VALIDATION_V1.md) for the status model,
confidence formula, privacy boundary, migration, and rollback.

---

## Assessment Report v1

[`assessment-report-v1.schema.json`](../schemas/assessment-report-v1.schema.json)
defines the strict canonical output derived from Assessment Contract v1. It contains
audit metadata, separated decision concepts, all control states, freshness,
content-free provenance, next actions, rendering limits and integrity. See
[`AUDITABLE_REPORTS_V1.md`](AUDITABLE_REPORTS_V1.md).

---

## ServiceNow enterprise adapter v2

The strict design schemas
[`servicenow-mapping-v2.schema.json`](../schemas/servicenow-mapping-v2.schema.json),
[`servicenow-adapter-request-v2.schema.json`](../schemas/servicenow-adapter-request-v2.schema.json),
and
[`servicenow-adapter-result-v2.schema.json`](../schemas/servicenow-adapter-result-v2.schema.json),
plus the strict
[`servicenow-adapter-plan-v2.schema.json`](../schemas/servicenow-adapter-plan-v2.schema.json)
and
[`servicenow-gateway-capability-v1.schema.json`](../schemas/servicenow-gateway-capability-v1.schema.json),
define the implemented enterprise boundary. They keep enrich-existing
separate from model-authorized draft creation and reject live writes without the
production Evidence Gateway profile. The public Python API implements plan validation,
execution and reconciliation; existing v1 runtime surfaces remain unchanged.

See [`SERVICENOW_ENTERPRISE_GOLDEN_PATH.md`](SERVICENOW_ENTERPRISE_GOLDEN_PATH.md).

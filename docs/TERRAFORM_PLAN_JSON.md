# Terraform Plan JSON contract

PreflightOps evaluates the machine-readable output produced by:

```bash
terraform plan -out=tfplan
terraform show -json tfplan > tfplan.json
preflightops --services services.yaml --change change.yaml \
  --terraform-json tfplan.json --output report.md
```

The parser is offline and follows the Terraform JSON 1.x compatibility rule: minor
versions are accepted and unknown properties are ignored, while an unsupported major
version is rejected. See HashiCorp's
[JSON output format](https://developer.hashicorp.com/terraform/internals/json-format).

## Input contract

A file/string input must be a Terraform plan object containing:

- `format_version` with supported major `1`;
- `resource_changes` as a list;
- for every resource: bounded non-empty `address` and `type`, optional
  `provider_name`, and a `change` object;
- `change.actions` equal to exactly one supported ordered sequence: `no-op`, `create`,
  `read`, `update`, `delete`, `delete/create`, or `create/delete`.

Mappings already decoded by legacy Python consumers may temporarily omit
`format_version`; they are recorded internally as `1.0-legacy-mapping`. New integrations
must provide it. A state representation without `resource_changes`, a plan with
`errored: true`, malformed resources or unknown actions fails closed with
`TerraformPlanError`, which remains a `ValueError` for API compatibility.

## Evidence contract

Every finding contains the stable legacy fields plus:

| Field | Meaning |
| --- | --- |
| `resource` | Opaque absolute Terraform address |
| `resource_type` | Provider resource type |
| `provider` | Declared provider name or conservative inference |
| `action` | Ordered canonical action string |
| `evidence.kind` | Action, resource-type or attribute-predicate evidence |
| `evidence.attribute_path` | Relative structural path, never a value |
| `evidence.predicate` | Stable content-free predicate identifier |

Findings are sorted by resource, action, rule ID and evidence. Reordering equivalent
`resource_changes` therefore does not alter the serialized result.

Initial structured rules cover IAM, security groups, firewall/network controls, public
exposure, DNS, KMS/encryption keys, databases and destructive/replace actions for common
AWS, Azure and GCP resource types. Matching uses explicit types and allowlisted attribute
paths, not arbitrary substring search across the plan.

## Privacy

`before_sensitive` and `after_sensitive` are applied before rule evaluation. Unknown
leaves from `after_unknown` are also excluded. Findings, exceptions and logs never copy
`before`, `after`, variables, outputs or complete provider payloads. Public exposure
evidence states only the attribute path and matched predicate; it never includes a CIDR,
credential or source value.

Terraform marks sensitivity; it does not remove the underlying value from JSON. Treat the
input plan as sensitive operational material, use ephemeral CI storage, restrict access,
and retain only the minimized assessment evidence required by policy.

## Defensive limits

`TerraformPlanLimits` defaults are applied before findings are emitted:

| Budget | Default |
| --- | ---: |
| Raw/decoded input | 16 MiB |
| JSON depth | 64 |
| JSON nodes | 500,000 |
| Resource changes | 20,000 |
| Individual string/key | 1 MiB |

Consumers may pass stricter positive limits. Exceeding any budget returns a stable error
code and path without partial findings. Non-finite JSON numbers are rejected.

## Precision and limitations

`tests/fixtures/terraform/precision-matrix-v1.json` is a sanitized known-answer corpus
covering GCP public firewall, IAM, database replacement, DNS, KMS, generic delete and
negative/no-op cases. CI requires 100% precision and recall on this corpus. That metric
describes only the versioned corpus, not every possible provider resource.

The parser does not download provider schemas, evaluate HCL, reconstruct unknown values,
or resolve cross-resource dependency graphs. Sensitive or unknown exposure attributes
cannot safely support a positive assertion; the later confidence/freshness layer must
represent that evidence gap instead of inventing PASS.

## Migration and rollback

1. Generate `terraform show -json` and select `--terraform-json` explicitly.
2. Run in report-only mode and compare with current review outcomes.
3. Expand the known-answer corpus before adding provider resource rules.
4. Keep `--terraform` only for legacy human-readable inputs during migration.

JSON parse errors never fall back to text. Rollback restores the previous
`scan_terraform_json` implementation or disables the JSON input while leaving
`scan_terraform`, CLI outputs, reports and global thresholds unchanged.


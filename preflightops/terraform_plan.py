"""Bounded, deterministic parser and scanner for ``terraform show -json`` plans.

The module never calls Terraform or a provider.  It accepts an already-produced
plan, validates its structural contract, removes sensitive/unknown values before
rule evaluation, and returns content-free evidence about risky changes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Final

SOURCE_TERRAFORM: Final = "Terraform"


class TerraformPlanError(ValueError):
    """Fail-closed Terraform plan error with a stable code and safe path."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


@dataclass(frozen=True)
class TerraformPlanLimits:
    """Resource budgets applied before any finding is emitted."""

    max_input_bytes: int = 16 * 1024 * 1024
    max_depth: int = 64
    max_nodes: int = 500_000
    max_resource_changes: int = 20_000
    max_string_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        for field_name in (
            "max_input_bytes",
            "max_depth",
            "max_nodes",
            "max_resource_changes",
            "max_string_bytes",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")


DEFAULT_TERRAFORM_PLAN_LIMITS: Final = TerraformPlanLimits()


@dataclass(frozen=True)
class TerraformResourceChange:
    """Validated resource change with sensitive and unknown leaves removed."""

    address: str
    resource_type: str
    provider: str
    actions: tuple[str, ...]
    before: Any
    after: Any
    action_reason: str | None

    @property
    def action(self) -> str:
        return "/".join(self.actions)


@dataclass(frozen=True)
class TerraformPlan:
    """Validated plan projection used by the rule engine."""

    format_version: str
    terraform_version: str | None
    resource_changes: tuple[TerraformResourceChange, ...]


@dataclass(frozen=True)
class _ResourceRule:
    rule_id: str
    score: int
    severity: str
    description: str
    exact_types: frozenset[str] = frozenset()
    type_prefixes: tuple[str, ...] = ()

    def matches(self, resource_type: str) -> bool:
        return resource_type in self.exact_types or any(
            resource_type.startswith(prefix) for prefix in self.type_prefixes
        )


_SUPPORTED_ACTIONS: Final = frozenset(
    {
        ("no-op",),
        ("create",),
        ("read",),
        ("update",),
        ("delete",),
        ("delete", "create"),
        ("create", "delete"),
    }
)
_NON_MUTATING_ACTIONS: Final = {("no-op",), ("read",)}
_FORMAT_VERSION_RE: Final = re.compile(r"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)$")
_SAFE_PATH_SEGMENT_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
_IDENTITY_LIMIT: Final = 2048
_REDACTED: Final = object()


_RESOURCE_RULES: Final = (
    _ResourceRule(
        "terraform-iam-policy-change",
        30,
        "high",
        "IAM policy change detected",
        frozenset(
            {
                "aws_iam_policy",
                "aws_iam_policy_attachment",
                "aws_iam_role_policy",
                "aws_iam_role_policy_attachment",
                "aws_iam_user_policy",
                "aws_iam_user_policy_attachment",
                "aws_iam_group_policy",
                "aws_iam_group_policy_attachment",
            }
        ),
    ),
    _ResourceRule(
        "terraform-iam-role-change",
        30,
        "high",
        "IAM role or definition change detected",
        frozenset(
            {
                "aws_iam_role",
                "aws_iam_service_linked_role",
                "google_project_iam_custom_role",
                "google_organization_iam_custom_role",
                "azurerm_role_definition",
            }
        ),
    ),
    _ResourceRule(
        "terraform-cloud-iam-change",
        30,
        "high",
        "Cloud IAM membership change detected",
        frozenset(
            {
                "google_project_iam_member",
                "google_project_iam_binding",
                "google_project_iam_policy",
                "google_folder_iam_member",
                "google_folder_iam_binding",
                "google_folder_iam_policy",
                "google_organization_iam_member",
                "google_organization_iam_binding",
                "google_organization_iam_policy",
                "google_service_account_iam_member",
                "google_service_account_iam_binding",
                "google_service_account_iam_policy",
                "azurerm_role_assignment",
            }
        ),
    ),
    _ResourceRule(
        "terraform-security-group-change",
        25,
        "high",
        "Security group change detected",
        frozenset(
            {
                "aws_security_group",
                "aws_security_group_rule",
                "aws_vpc_security_group_egress_rule",
                "aws_vpc_security_group_ingress_rule",
                "azurerm_network_security_group",
                "azurerm_network_security_rule",
            }
        ),
    ),
    _ResourceRule(
        "terraform-firewall-change",
        25,
        "high",
        "Firewall rule change detected",
        frozenset(
            {
                "google_compute_firewall",
                "google_compute_firewall_policy",
                "google_compute_firewall_policy_rule",
                "google_compute_network_firewall_policy",
                "google_compute_network_firewall_policy_rule",
                "azurerm_firewall",
                "azurerm_firewall_network_rule_collection",
            }
        ),
        ("aws_networkfirewall_",),
    ),
    _ResourceRule(
        "terraform-db-instance-change",
        25,
        "high",
        "Database infrastructure change detected",
        frozenset(
            {
                "aws_db_instance",
                "aws_rds_cluster",
                "aws_rds_cluster_instance",
                "google_sql_database_instance",
                "google_spanner_instance",
                "google_bigtable_instance",
                "azurerm_mssql_server",
                "azurerm_mssql_database",
                "azurerm_postgresql_flexible_server",
                "azurerm_mysql_flexible_server",
                "azurerm_cosmosdb_account",
            }
        ),
    ),
    _ResourceRule(
        "terraform-public-ip-exposure",
        25,
        "high",
        "Public IP resource change detected",
        frozenset(
            {
                "aws_eip",
                "google_compute_address",
                "google_compute_global_address",
                "azurerm_public_ip",
                "azurerm_public_ip_prefix",
            }
        ),
    ),
    _ResourceRule(
        "terraform-dns-change",
        25,
        "high",
        "DNS change detected",
        frozenset(
            {
                "aws_route53_record",
                "aws_route53_zone",
                "google_dns_managed_zone",
                "google_dns_record_set",
                "azurerm_dns_a_record",
                "azurerm_dns_aaaa_record",
                "azurerm_dns_cname_record",
                "azurerm_dns_mx_record",
                "azurerm_dns_txt_record",
                "azurerm_dns_zone",
                "azurerm_private_dns_zone",
            }
        ),
        ("aws_route53_", "google_dns_", "azurerm_private_dns_"),
    ),
    _ResourceRule(
        "terraform-kms-change",
        25,
        "high",
        "Encryption key change detected",
        frozenset(
            {
                "azurerm_key_vault_key",
                "azurerm_key_vault_managed_hardware_security_module_key",
            }
        ),
        ("aws_kms_", "google_kms_"),
    ),
)

_PUBLIC_CIDRS: Final = {"0.0.0.0/0", "::/0"}
_CIDR_PATH_SEGMENTS: Final = {
    "cidr_blocks",
    "ipv6_cidr_blocks",
    "source_ranges",
    "source_range",
    "source_address_prefix",
    "source_address_prefixes",
    "authorized_networks",
    "allowed_ip_ranges",
    "ip_rules",
}
_PUBLIC_BOOLEAN_FIELDS: Final = {
    "associate_public_ip_address",
    "assign_public_ip",
    "enable_public_ip",
    "public_network_access_enabled",
    "publicly_accessible",
}
_PUBLIC_ENUM_FIELDS: Final = {
    "network_access": {"public", "enabled"},
    "public_network_access": {"public", "enabled"},
}


def _error(code: str, path: str, message: str) -> TerraformPlanError:
    return TerraformPlanError(code, path, message)


def _reject_json_constant(_: str) -> None:
    raise _error("TF_PLAN_JSON", "$", "non-finite JSON numbers are unsupported")


def _validate_limits(value: Any, limits: TerraformPlanLimits) -> None:
    stack: list[tuple[Any, int, str]] = [(value, 0, "$")]
    nodes = 0
    scalar_bytes = 0
    while stack:
        current, depth, path = stack.pop()
        nodes += 1
        if nodes > limits.max_nodes:
            raise _error("TF_PLAN_NODE_LIMIT", path, "JSON node limit exceeded")
        if depth > limits.max_depth:
            raise _error("TF_PLAN_DEPTH_LIMIT", path, "JSON depth limit exceeded")
        if isinstance(current, dict):
            if nodes + len(stack) + len(current) > limits.max_nodes:
                raise _error("TF_PLAN_NODE_LIMIT", path, "JSON node limit exceeded")
            for key, child in current.items():
                if not isinstance(key, str):
                    raise _error("TF_PLAN_JSON_TYPE", path, "object keys must be strings")
                encoded_key = len(key.encode("utf-8"))
                if encoded_key > limits.max_string_bytes:
                    raise _error("TF_PLAN_STRING_LIMIT", path, "object key is too large")
                scalar_bytes += encoded_key
                stack.append((child, depth + 1, f"{path}.*"))
        elif isinstance(current, list):
            if nodes + len(stack) + len(current) > limits.max_nodes:
                raise _error("TF_PLAN_NODE_LIMIT", path, "JSON node limit exceeded")
            stack.extend(
                (child, depth + 1, f"{path}[{index}]") for index, child in enumerate(current)
            )
        elif isinstance(current, str):
            encoded = len(current.encode("utf-8"))
            if encoded > limits.max_string_bytes:
                raise _error("TF_PLAN_STRING_LIMIT", path, "string value is too large")
            scalar_bytes += encoded
        elif current is None or isinstance(current, bool | int | float):
            scalar_bytes += 16
        else:
            raise _error("TF_PLAN_JSON_TYPE", path, "unsupported JSON value type")
        if scalar_bytes > limits.max_input_bytes:
            raise _error("TF_PLAN_SIZE_LIMIT", path, "decoded JSON size limit exceeded")


def _require_text(value: Any, path: str, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > _IDENTITY_LIMIT:
        raise _error("TF_PLAN_FIELD", path, "must be a non-empty bounded string")
    return value


def _validate_mask(value: Any, mask: Any, path: str, label: str) -> None:
    if mask is None or mask == {} or mask == [] or isinstance(mask, bool):
        return
    if isinstance(value, dict) and isinstance(mask, dict):
        for key, child_mask in mask.items():
            if not isinstance(key, str):
                raise _error("TF_PLAN_MASK", path, f"{label} mask keys must be strings")
            if key in value:
                _validate_mask(value[key], child_mask, f"{path}.*", label)
        return
    if isinstance(value, list) and isinstance(mask, list):
        for index, child_mask in enumerate(mask[: len(value)]):
            _validate_mask(value[index], child_mask, f"{path}[{index}]", label)
        return
    raise _error("TF_PLAN_MASK", path, f"{label} mask does not match the value shape")


def _mask_value(value: Any, sensitive: Any, unknown: Any = None, *, path: str) -> Any:
    _validate_mask(value, sensitive, path, "sensitive")
    _validate_mask(value, unknown, path, "unknown")
    if sensitive is True or unknown is True:
        return _REDACTED
    if isinstance(value, dict):
        sensitive_map = sensitive if isinstance(sensitive, dict) else {}
        unknown_map = unknown if isinstance(unknown, dict) else {}
        result: dict[str, Any] = {}
        for key, child in value.items():
            projected = _mask_value(
                child,
                sensitive_map.get(key),
                unknown_map.get(key),
                path=f"{path}.*",
            )
            if projected is not _REDACTED:
                result[key] = projected
        return result
    if isinstance(value, list):
        sensitive_list = sensitive if isinstance(sensitive, list) else []
        unknown_list = unknown if isinstance(unknown, list) else []
        result_list = []
        for index, child in enumerate(value):
            sensitive_child = sensitive_list[index] if index < len(sensitive_list) else None
            unknown_child = unknown_list[index] if index < len(unknown_list) else None
            projected = _mask_value(
                child,
                sensitive_child,
                unknown_child,
                path=f"{path}[{index}]",
            )
            if projected is not _REDACTED:
                result_list.append(projected)
        return result_list
    return value


def _infer_provider(resource_type: str) -> str:
    prefix = resource_type.split("_", 1)[0]
    return {
        "aws": "registry.terraform.io/hashicorp/aws",
        "google": "registry.terraform.io/hashicorp/google",
        "google-beta": "registry.terraform.io/hashicorp/google-beta",
        "azurerm": "registry.terraform.io/hashicorp/azurerm",
    }.get(prefix, "unknown")


def _parse_format_version(plan: dict[str, Any], *, version_required: bool) -> str:
    raw = plan.get("format_version")
    if raw is None:
        if version_required:
            raise _error("TF_PLAN_FORMAT_VERSION", "$.format_version", "field is required")
        return "1.0-legacy-mapping"
    if not isinstance(raw, str):
        raise _error("TF_PLAN_FORMAT_VERSION", "$.format_version", "must be a string")
    match = _FORMAT_VERSION_RE.fullmatch(raw)
    if match is None:
        raise _error("TF_PLAN_FORMAT_VERSION", "$.format_version", "must use major.minor")
    if int(match.group("major")) != 1:
        raise _error("TF_PLAN_FORMAT_VERSION", "$.format_version", "unsupported major version")
    return raw


def _parse_resource_change(raw: Any, index: int) -> TerraformResourceChange:
    path = f"$.resource_changes[{index}]"
    if not isinstance(raw, dict):
        raise _error("TF_PLAN_RESOURCE", path, "resource change must be an object")
    address = _require_text(raw.get("address"), f"{path}.address")
    resource_type = _require_text(raw.get("type"), f"{path}.type")
    assert address is not None and resource_type is not None
    provider = _require_text(raw.get("provider_name"), f"{path}.provider_name", required=False)
    if provider is None:
        provider = _infer_provider(resource_type)
    change = raw.get("change")
    if not isinstance(change, dict):
        raise _error("TF_PLAN_CHANGE", f"{path}.change", "change must be an object")
    raw_actions = change.get("actions")
    if not isinstance(raw_actions, list) or not all(isinstance(item, str) for item in raw_actions):
        raise _error("TF_PLAN_ACTION", f"{path}.change.actions", "actions must be strings")
    actions = tuple(raw_actions)
    if actions not in _SUPPORTED_ACTIONS:
        raise _error("TF_PLAN_ACTION", f"{path}.change.actions", "unsupported action sequence")
    reason = _require_text(raw.get("action_reason"), f"{path}.action_reason", required=False)
    return TerraformResourceChange(
        address=address,
        resource_type=resource_type.lower(),
        provider=provider.lower(),
        actions=actions,
        before=_mask_value(
            change.get("before"),
            change.get("before_sensitive"),
            path=f"{path}.change.before",
        ),
        after=_mask_value(
            change.get("after"),
            change.get("after_sensitive"),
            change.get("after_unknown"),
            path=f"{path}.change.after",
        ),
        action_reason=reason,
    )


def parse_terraform_plan_json(
    plan: Any, *, limits: TerraformPlanLimits = DEFAULT_TERRAFORM_PLAN_LIMITS
) -> TerraformPlan:
    """Validate and project a Terraform plan without retaining sensitive leaves."""

    version_required = isinstance(plan, str)
    if isinstance(plan, str):
        if len(plan.encode("utf-8")) > limits.max_input_bytes:
            raise _error("TF_PLAN_SIZE_LIMIT", "$", "input byte limit exceeded")
        try:
            plan = json.loads(plan, parse_constant=_reject_json_constant)
        except TerraformPlanError:
            raise
        except (json.JSONDecodeError, RecursionError) as exc:
            code = "TF_PLAN_DEPTH_LIMIT" if isinstance(exc, RecursionError) else "TF_PLAN_JSON"
            raise _error(code, "$", "invalid Terraform JSON plan") from None
    if not isinstance(plan, dict):
        raise _error("TF_PLAN_OBJECT", "$", "Terraform JSON plan must be an object")
    _validate_limits(plan, limits)
    format_version = _parse_format_version(plan, version_required=version_required)
    if plan.get("errored") is True:
        raise _error("TF_PLAN_ERRORED", "$.errored", "Terraform reported an errored plan")
    if "resource_changes" not in plan:
        raise _error(
            "TF_PLAN_RESOURCE_CHANGES",
            "$.resource_changes",
            "plan resource_changes field is required",
        )
    changes = plan["resource_changes"]
    if not isinstance(changes, list):
        raise _error("TF_PLAN_RESOURCE_CHANGES", "$.resource_changes", "must be a list")
    if len(changes) > limits.max_resource_changes:
        raise _error(
            "TF_PLAN_RESOURCE_LIMIT",
            "$.resource_changes",
            "resource change limit exceeded",
        )
    terraform_version = _require_text(
        plan.get("terraform_version"), "$.terraform_version", required=False
    )
    parsed = tuple(
        _parse_resource_change(resource, index) for index, resource in enumerate(changes)
    )
    return TerraformPlan(format_version, terraform_version, parsed)


def _finding(
    rule: _ResourceRule | None,
    resource: TerraformResourceChange,
    *,
    rule_id: str | None = None,
    description: str | None = None,
    severity: str | None = None,
    score: int | None = None,
    evidence_kind: str,
    attribute_path: str,
    predicate: str,
) -> dict[str, Any]:
    if rule is not None:
        rule_id = rule.rule_id
        description = rule.description
        severity = rule.severity
        score = rule.score
    assert rule_id is not None and description is not None
    assert severity is not None and score is not None
    return {
        "id": rule_id,
        "description": f"{description}: {resource.address}",
        "severity": severity,
        "score": score,
        "source": SOURCE_TERRAFORM,
        "resource": resource.address,
        "resource_type": resource.resource_type,
        "provider": resource.provider,
        "action": resource.action,
        "evidence": {
            "kind": evidence_kind,
            "attribute_path": attribute_path,
            "predicate": predicate,
        },
    }


def _walk_leaves(value: Any) -> list[tuple[tuple[str, ...], Any]]:
    leaves: list[tuple[tuple[str, ...], Any]] = []
    stack: list[tuple[Any, tuple[str, ...]]] = [(value, ())]
    while stack:
        current, path = stack.pop()
        if isinstance(current, dict):
            stack.extend((child, path + (str(key),)) for key, child in current.items())
        elif isinstance(current, list):
            stack.extend((child, path + (str(index),)) for index, child in enumerate(current))
        else:
            leaves.append((path, current))
    return leaves


def _public_exposures(after: Any) -> list[tuple[str, str]]:
    matches: set[tuple[str, str]] = set()
    for path, value in _walk_leaves(after):
        named_segments = {segment.lower() for segment in path if not segment.isdigit()}
        leaf = path[-1].lower() if path else ""
        attribute_path = "after" + "".join(
            (
                f"[{segment}]"
                if segment.isdigit()
                else f".{segment if _SAFE_PATH_SEGMENT_RE.fullmatch(segment) else '*'}"
            )
            for segment in path
        )
        if isinstance(value, str) and value.strip() in _PUBLIC_CIDRS:
            if named_segments & _CIDR_PATH_SEGMENTS:
                matches.add((attribute_path, "contains-public-cidr"))
        elif value is True and leaf in _PUBLIC_BOOLEAN_FIELDS:
            matches.add((attribute_path, "public-access-enabled"))
        elif isinstance(value, str) and leaf in _PUBLIC_ENUM_FIELDS:
            if value.strip().lower() in _PUBLIC_ENUM_FIELDS[leaf]:
                matches.add((attribute_path, "public-access-enum"))
    return sorted(matches)


def scan_terraform_plan(plan: TerraformPlan) -> list[dict[str, Any]]:
    """Evaluate a validated plan and return deterministic structured findings."""

    findings: list[dict[str, Any]] = []
    for resource in plan.resource_changes:
        if "delete" in resource.actions:
            replacement = "create" in resource.actions
            findings.append(
                _finding(
                    None,
                    resource,
                    rule_id=(
                        "terraform-replace-action" if replacement else "terraform-destroy-action"
                    ),
                    description=("Replacement action" if replacement else "Destroy action"),
                    severity="high" if replacement else "critical",
                    score=30 if replacement else 40,
                    evidence_kind="terraform-action",
                    attribute_path="change.actions",
                    predicate=("ordered-replace" if replacement else "delete"),
                )
            )
        if resource.actions not in _NON_MUTATING_ACTIONS:
            for rule in _RESOURCE_RULES:
                if rule.matches(resource.resource_type):
                    findings.append(
                        _finding(
                            rule,
                            resource,
                            evidence_kind="resource-type",
                            attribute_path="type",
                            predicate=f"matches-{rule.rule_id}",
                        )
                    )
            for attribute_path, predicate in _public_exposures(resource.after):
                findings.append(
                    _finding(
                        None,
                        resource,
                        rule_id="terraform-public-exposure",
                        description="Public network exposure detected",
                        severity="critical",
                        score=35,
                        evidence_kind="attribute-predicate",
                        attribute_path=attribute_path,
                        predicate=predicate,
                    )
                )
    return sorted(
        findings,
        key=lambda item: (
            item["resource"],
            item["action"],
            item["id"],
            item["evidence"]["attribute_path"],
            item["evidence"]["predicate"],
        ),
    )


def scan_terraform_json(
    plan: Any, *, limits: TerraformPlanLimits = DEFAULT_TERRAFORM_PLAN_LIMITS
) -> list[dict[str, Any]]:
    """Parse and evaluate Terraform Plan JSON, returning no partial results on error."""

    if plan is None or plan == "":
        return []
    return scan_terraform_plan(parse_terraform_plan_json(plan, limits=limits))


__all__ = [
    "DEFAULT_TERRAFORM_PLAN_LIMITS",
    "TerraformPlan",
    "TerraformPlanError",
    "TerraformPlanLimits",
    "TerraformResourceChange",
    "parse_terraform_plan_json",
    "scan_terraform_json",
    "scan_terraform_plan",
]

"""Adversarial and contract tests for Terraform Plan JSON analysis."""

import json
from pathlib import Path

import pytest

from preflightops.scanners import scan_terraform, scan_terraform_json
from preflightops.terraform_plan import (
    TerraformPlanError,
    TerraformPlanLimits,
    parse_terraform_plan_json,
)

FIXTURE = Path(__file__).parent / "fixtures" / "terraform" / "precision-matrix-v1.json"


def _resource(
    *,
    address="aws_instance.web",
    resource_type="aws_instance",
    provider="registry.terraform.io/hashicorp/aws",
    actions=("update",),
    before=None,
    after=None,
    before_sensitive=None,
    after_sensitive=None,
    after_unknown=None,
):
    return {
        "address": address,
        "type": resource_type,
        "provider_name": provider,
        "change": {
            "actions": list(actions),
            "before": {} if before is None else before,
            "after": {} if after is None else after,
            "before_sensitive": {} if before_sensitive is None else before_sensitive,
            "after_sensitive": {} if after_sensitive is None else after_sensitive,
            "after_unknown": {} if after_unknown is None else after_unknown,
        },
    }


def _plan(*resources, **overrides):
    result = {
        "format_version": "1.0",
        "terraform_version": "1.9.8",
        "resource_changes": list(resources),
    }
    result.update(overrides)
    return result


def _ids(findings):
    return {finding["id"] for finding in findings}


def test_precision_matrix_has_no_known_false_positives_or_negatives():
    matrix = json.loads(FIXTURE.read_text(encoding="utf-8"))
    true_positives = false_positives = false_negatives = 0
    for case in matrix["cases"]:
        actual = _ids(scan_terraform_json(case["plan"]))
        expected = set(case["expected_ids"])
        true_positives += len(actual & expected)
        false_positives += len(actual - expected)
        false_negatives += len(expected - actual)
        assert actual == expected, case["name"]
    precision = true_positives / (true_positives + false_positives)
    recall = true_positives / (true_positives + false_negatives)
    assert precision == 1.0
    assert recall == 1.0


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.99"])
def test_supported_format_versions(version):
    parsed = parse_terraform_plan_json(_plan(format_version=version))
    assert parsed.format_version == version


@pytest.mark.parametrize("version", ["2.0", "0.1", "1", "v1.0", 1])
def test_unsupported_or_malformed_format_version_fails_closed(version):
    with pytest.raises(TerraformPlanError, match="TF_PLAN_FORMAT_VERSION"):
        scan_terraform_json(_plan(format_version=version))


def test_string_input_requires_explicit_version_but_legacy_mapping_remains_compatible():
    mapping = {"resource_changes": []}
    assert scan_terraform_json(mapping) == []
    with pytest.raises(TerraformPlanError, match="format_version"):
        scan_terraform_json(json.dumps(mapping))


def test_errored_plan_and_state_shape_cannot_become_low_risk():
    with pytest.raises(TerraformPlanError, match="TF_PLAN_ERRORED"):
        scan_terraform_json(_plan(errored=True))
    with pytest.raises(TerraformPlanError, match="resource_changes"):
        scan_terraform_json({"format_version": "1.0", "values": {}})


@pytest.mark.parametrize(
    "actions,normalized",
    [
        (("create",), "create"),
        (("read",), "read"),
        (("update",), "update"),
        (("delete",), "delete"),
        (("delete", "create"), "delete/create"),
        (("create", "delete"), "create/delete"),
        (("no-op",), "no-op"),
    ],
)
def test_supported_actions_are_modeled_in_order(actions, normalized):
    parsed = parse_terraform_plan_json(_plan(_resource(actions=actions)))
    assert parsed.resource_changes[0].actions == actions
    assert parsed.resource_changes[0].action == normalized


@pytest.mark.parametrize(
    "actions",
    [(), ("replace",), ("update", "delete"), ("delete", "create", "read"), (1,)],
)
def test_unknown_action_sequences_fail_closed(actions):
    with pytest.raises(TerraformPlanError, match="TF_PLAN_ACTION"):
        scan_terraform_json(_plan(_resource(actions=actions)))


@pytest.mark.parametrize(
    "resource",
    [None, {}, {"address": "x", "type": "aws_instance", "change": []}],
)
def test_malformed_resource_changes_fail_without_partial_findings(resource):
    with pytest.raises(TerraformPlanError, match="TF_PLAN_(RESOURCE|FIELD|CHANGE)"):
        scan_terraform_json(_plan(_resource(resource_type="aws_iam_role"), resource))


def test_findings_have_minimal_structured_evidence_and_provider_identity():
    findings = scan_terraform_json(
        _plan(
            _resource(
                address="google_compute_firewall.edge",
                resource_type="google_compute_firewall",
                provider="registry.terraform.io/hashicorp/google-beta",
                after={"source_ranges": ["0.0.0.0/0"]},
            )
        )
    )
    assert findings
    for finding in findings:
        assert finding["resource"] == "google_compute_firewall.edge"
        assert finding["resource_type"] == "google_compute_firewall"
        assert finding["provider"] == "registry.terraform.io/hashicorp/google-beta"
        assert finding["action"] == "update"
        assert set(finding["evidence"]) == {"kind", "attribute_path", "predicate"}
        assert "before" not in finding
        assert "after" not in finding


def test_sensitive_and_unknown_values_are_removed_before_rule_evaluation():
    placeholder = "sensitive-placeholder-token"
    plan = _plan(
        _resource(
            after={
                "source_ranges": ["0.0.0.0/0"],
                "nested": {"credential": placeholder},
                "publicly_accessible": True,
            },
            after_sensitive={"source_ranges": True, "nested": True},
            after_unknown={"publicly_accessible": True},
        )
    )
    parsed = parse_terraform_plan_json(plan)
    serialized_model = repr(parsed)
    serialized_findings = json.dumps(scan_terraform_json(plan), sort_keys=True)
    assert placeholder not in serialized_model
    assert placeholder not in serialized_findings
    assert "terraform-public-exposure" not in _ids(scan_terraform_json(plan))


def test_error_never_echoes_sensitive_adjacent_value():
    placeholder = "sensitive-placeholder-token"
    plan = _plan(
        {
            "address": "aws_instance.bad",
            "type": "aws_instance",
            "provider_name": "registry.terraform.io/hashicorp/aws",
            "change": {
                "actions": ["unsupported", placeholder],
                "after": {"credential": placeholder},
                "after_sensitive": {"credential": True},
            },
        }
    )
    with pytest.raises(TerraformPlanError) as error:
        scan_terraform_json(plan)
    assert placeholder not in str(error.value)


@pytest.mark.parametrize(
    "after,mask",
    [
        ({"credential": "placeholder"}, "invalid-mask"),
        (["placeholder"], {"0": True}),
        ("placeholder", {"nested": True}),
    ],
)
def test_malformed_sensitive_masks_fail_closed(after, mask):
    with pytest.raises(TerraformPlanError, match="TF_PLAN_MASK") as error:
        scan_terraform_json(_plan(_resource(after=after, after_sensitive=mask)))
    assert "placeholder" not in str(error.value)


def test_limit_error_paths_do_not_echo_arbitrary_object_keys():
    key = "sensitive-placeholder-key"
    value = {key: {"nested": {"too_deep": True}}}
    with pytest.raises(TerraformPlanError) as error:
        scan_terraform_json(value, limits=TerraformPlanLimits(max_depth=1))
    assert key not in str(error.value)


@pytest.mark.parametrize(
    "after,expected_path",
    [
        ({"source_ranges": ["::/0"]}, "after.source_ranges[0]"),
        ({"publicly_accessible": True}, "after.publicly_accessible"),
        ({"public_network_access": "Enabled"}, "after.public_network_access"),
        (
            {"settings": {"authorized_networks": [{"value": "0.0.0.0/0"}]}},
            "after.settings.authorized_networks[0].value",
        ),
    ],
)
def test_public_exposure_uses_allowlisted_paths_and_content_free_predicates(after, expected_path):
    findings = scan_terraform_json(_plan(_resource(after=after)))
    exposure = next(item for item in findings if item["id"] == "terraform-public-exposure")
    assert exposure["evidence"]["attribute_path"] == expected_path
    assert "0.0.0.0/0" not in json.dumps(exposure)
    assert "::/0" not in json.dumps(exposure)


@pytest.mark.parametrize(
    "after",
    [
        {"description": "allow 0.0.0.0/0 only after review"},
        {"publicly_accessible": False},
        {"public_network_access": "Disabled"},
        {"cidr_blocks": ["10.0.0.0/8"]},
    ],
)
def test_public_exposure_negations_do_not_match(after):
    assert "terraform-public-exposure" not in _ids(
        scan_terraform_json(_plan(_resource(after=after)))
    )


def test_resource_order_does_not_change_serialized_findings():
    first = _resource(
        address="google_dns_record_set.api",
        resource_type="google_dns_record_set",
        provider="registry.terraform.io/hashicorp/google",
    )
    second = _resource(
        address="aws_kms_key.data",
        resource_type="aws_kms_key",
        provider="registry.terraform.io/hashicorp/aws",
    )
    forward = json.dumps(scan_terraform_json(_plan(first, second)), sort_keys=True)
    reverse = json.dumps(scan_terraform_json(_plan(second, first)), sort_keys=True)
    assert forward == reverse


def test_limits_reject_size_depth_nodes_resources_and_strings():
    with pytest.raises(TerraformPlanError, match="TF_PLAN_SIZE_LIMIT"):
        scan_terraform_json("{}" * 20, limits=TerraformPlanLimits(max_input_bytes=8))

    nested = current = {}
    for _ in range(5):
        current["child"] = {}
        current = current["child"]
    with pytest.raises(TerraformPlanError, match="TF_PLAN_DEPTH_LIMIT"):
        scan_terraform_json(nested, limits=TerraformPlanLimits(max_depth=3))

    with pytest.raises(TerraformPlanError, match="TF_PLAN_NODE_LIMIT"):
        scan_terraform_json(_plan(), limits=TerraformPlanLimits(max_nodes=2))

    with pytest.raises(TerraformPlanError, match="TF_PLAN_RESOURCE_LIMIT"):
        scan_terraform_json(
            _plan(_resource(address="aws_instance.one"), _resource(address="aws_instance.two")),
            limits=TerraformPlanLimits(max_resource_changes=1),
        )

    with pytest.raises(TerraformPlanError, match="TF_PLAN_STRING_LIMIT"):
        scan_terraform_json(
            _plan(_resource(after={"description": "x" * 20})),
            limits=TerraformPlanLimits(max_string_bytes=8),
        )


def test_large_plan_within_explicit_budget_is_processed_completely():
    resources = tuple(
        _resource(
            address=f"aws_iam_role.role_{index}",
            resource_type="aws_iam_role",
        )
        for index in range(2_000)
    )
    findings = scan_terraform_json(
        _plan(*resources), limits=TerraformPlanLimits(max_resource_changes=2_001)
    )
    assert len(findings) == 2_000
    assert findings[0]["resource"] == "aws_iam_role.role_0"


def test_legacy_text_scanner_is_preserved_and_never_used_as_json_fallback(monkeypatch):
    assert _ids(scan_terraform("aws_iam_policy.admin will be created")) == {
        "terraform-iam-policy-change"
    }

    def fail_if_called(_):
        raise AssertionError("legacy scanner must not be called")

    monkeypatch.setattr("preflightops.scanners.scan_terraform", fail_if_called)
    with pytest.raises(TerraformPlanError, match="TF_PLAN_JSON"):
        scan_terraform_json("destroy aws_iam_policy")


def test_non_finite_json_number_is_rejected():
    raw = '{"format_version":"1.0","resource_changes":[],"value":NaN}'
    with pytest.raises(TerraformPlanError, match="non-finite"):
        scan_terraform_json(raw)


@pytest.mark.parametrize("field", TerraformPlanLimits.__dataclass_fields__)
def test_limits_must_be_positive_integers(field):
    with pytest.raises(ValueError, match=field):
        TerraformPlanLimits(**{field: 0})

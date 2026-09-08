"""Offline scope tests: no SDK, credentials or cloud resources are consulted."""

from dataclasses import replace

import pytest

from preflightops.gcp_scope import GcpAsset, GcpConfig, GcpMetric, GcpResource
from preflightops.provider_contract import ProviderContractError


def config(**changes):
    return replace(
        GcpConfig("sample-project", ("sample-project",), "project-1", "principal-1"), **changes
    )


@pytest.mark.parametrize(
    "kind,path",
    [
        ("policy", "alertPolicies/123"),
        ("dashboard", "dashboards/123"),
        ("uptime", "uptimeCheckConfigs/123"),
        ("service", "services/123"),
        ("slo", "services/123/serviceLevelObjectives/456"),
    ],
)
def test_explicit_resources_are_project_bound(kind, path):
    resource = GcpResource("control-1", kind, "projects/sample-project/" + path)
    assert config(resources=(resource,)).resources == (resource,)
    with pytest.raises(ProviderContractError):
        config(resources=(replace(resource, name="projects/other-project/" + path),))


@pytest.mark.parametrize(
    "changes",
    [
        {"project_id": "outside-project"},
        {"allowed_projects": ()},
        {"allowed_projects": ("sample-project", "sample-project")},
        {"allowed_projects": ("sample-project", "other-project")},
        {"project_id": "organizations/123"},
        {"project_id": "1234567890"},
        {"project_id": "sample-project/../other-project"},
        {"ttl_seconds": True},
        {"max_pages": 0},
        {"min_interval_ms": 0},
        {"resources": []},
    ],
)
def test_invalid_configuration_fails_before_io(changes):
    with pytest.raises(ProviderContractError):
        config(**changes)


def test_allowlisted_other_project_still_cannot_enter_current_selection():
    with pytest.raises(ProviderContractError):
        config(
            allowed_projects=("other-project", "sample-project"),
            resources=(
                GcpResource("control-1", "policy", "projects/other-project/alertPolicies/123"),
            ),
        )


def test_metric_filter_enforces_project_and_quotes_values():
    value = 'x" OR resource.labels.project_id = "outside-project'
    metric = GcpMetric(
        "metric-1",
        "compute.googleapis.com/instance/cpu/utilization",
        "gce_instance",
        (("resource.labels.instance_id", value),),
    )
    query = metric.query_filter("sample-project")
    assert query.startswith('resource.labels.project_id = "sample-project" AND ')
    assert 'instance_id = "x\\" OR resource.labels.project_id = \\"outside-project"' in query
    assert value not in repr(metric)


@pytest.mark.parametrize(
    "key,value",
    [
        ("resource.labels.project_id", "other-project"),
        ("resource.type OR true", "x"),
        ("metric.labels.name", "x\nOR true"),
        ("metric.labels.name", ""),
        ("metric.labels.name", "x" * 257),
    ],
)
def test_labels_cannot_override_project_or_inject_grammar(key, value):
    with pytest.raises(ProviderContractError):
        GcpMetric("metric-1", "custom.googleapis.com/test", "gce_instance", ((key, value),))


def test_duplicate_metric_labels_rejected():
    with pytest.raises(ProviderContractError):
        GcpMetric(
            "metric-1",
            "custom.googleapis.com/test",
            "gce_instance",
            (("metric.labels.a", "1"), ("metric.labels.a", "2")),
        )


def test_assets_are_explicit_and_project_scoped():
    asset = GcpAsset(
        "asset-1",
        "compute.googleapis.com/Instance",
        "//compute.googleapis.com/projects/sample-project/zones/zone-1/instances/123",
    )
    assert config(assets=(asset,)).assets == (asset,)
    with pytest.raises(ProviderContractError):
        config(
            assets=(replace(asset, name=asset.name.replace("sample-project", "outside-project")),)
        )
    with pytest.raises(ProviderContractError):
        replace(asset, name=asset.name.replace("projects/sample-project", "organizations/123"))
    with pytest.raises(ProviderContractError):
        replace(asset, asset_type="storage.googleapis.com/Bucket")


def test_control_identities_cannot_collide_across_capabilities():
    resource = GcpResource("identity", "service", "projects/sample-project/services/123")
    with pytest.raises(ProviderContractError):
        config(resources=(resource,))
    with pytest.raises(ProviderContractError):
        config(
            resources=(replace(resource, control_id="shared"),),
            metrics=(GcpMetric("shared", "custom.googleapis.com/test", "gce_instance"),),
        )


def test_sample_age_must_fit_query_interval():
    with pytest.raises(ProviderContractError):
        config(
            lookback_seconds=10,
            metrics=(GcpMetric("metric-1", "custom.googleapis.com/test", "gce_instance"),),
        )


def test_digest_is_stable_and_binds_project_and_budgets():
    first = config()
    assert first.digest == config().digest
    assert first.digest != config(retries=1).digest
    assert first.digest != config(principal_reference="principal-2").digest
    assert "sample-project" not in repr(first)
    assert len(first.digest) == 64

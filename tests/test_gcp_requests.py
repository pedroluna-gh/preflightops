"""Official read request shapes, without network or credentials."""

from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest

from preflightops.gcp_requests import GcpRequests
from preflightops.gcp_scope import GcpAsset, GcpConfig, GcpMetric, GcpResource
from preflightops.provider_contract import ProviderContractError


def config(**changes):
    return replace(
        GcpConfig("sample-project", ("sample-project",), "project-1", "principal-1"), **changes
    )


@pytest.mark.parametrize(
    "kind,path,version",
    [
        ("policy", "alertPolicies/123", "v3"),
        ("dashboard", "dashboards/123", "v1"),
        ("uptime", "uptimeCheckConfigs/123", "v3"),
        ("service", "services/123", "v3"),
        ("slo", "services/123/serviceLevelObjectives/456", "v3"),
    ],
)
def test_read_resource_routes_and_minimal_projection(kind, path, version):
    resource = GcpResource("control", kind, "projects/sample-project/" + path)
    request = GcpRequests(config(resources=(resource,))).resource(resource)
    assert request.url == "https://monitoring.googleapis.com/" + version + "/" + resource.name
    assert "name" in dict(request.parameters)["fields"]
    assert "sample-project" not in repr(request)


def test_unconfigured_resources_cannot_be_requested():
    request = GcpRequests(config())
    with pytest.raises(ProviderContractError):
        request.resource(GcpResource("control", "service", "projects/sample-project/services/123"))
    with pytest.raises(ProviderContractError):
        request.metric(
            GcpMetric("metric", "custom.googleapis.com/test", "gce_instance"),
            "2026-09-08T12:00:00Z",
        )


def test_project_identity_read_never_lists_projects():
    request = GcpRequests(config()).project()
    assert request.url == "https://cloudresourcemanager.googleapis.com/v3/projects/sample-project"
    assert dict(request.parameters) == {"fields": "name,projectId,state"}


def test_metric_interval_scope_no_values_and_token_encoding():
    metric = GcpMetric("metric", "custom.googleapis.com/test", "gce_instance")
    request = GcpRequests(config(metrics=(metric,))).metric(
        metric, "2026-09-08T12:00:00Z", "x&project=outside"
    )
    params = parse_qs(urlsplit(request.encoded_url).query)
    assert params["pageToken"] == ["x&project=outside"]
    assert "project" not in params
    assert params["interval.startTime"] == ["2026-09-08T11:00:00Z"]
    assert params["interval.endTime"] == ["2026-09-08T12:00:00Z"]
    assert params["filter"][0].startswith('resource.labels.project_id = "sample-project"')
    assert "value" not in params["fields"][0]
    assert "executionErrors" in params["fields"][0]


@pytest.mark.parametrize("token", ["x" * 4097, "a\nb", "\x00", None])
def test_invalid_page_token_rejected(token):
    metric = GcpMetric("metric", "custom.googleapis.com/test", "gce_instance")
    with pytest.raises(ProviderContractError):
        GcpRequests(config(metrics=(metric,))).metric(metric, "2026-09-08T12:00:00Z", token)


def test_asset_scope_is_single_project_exact_type_and_metadata_only():
    asset = GcpAsset(
        "asset",
        "compute.googleapis.com/Instance",
        "//compute.googleapis.com/projects/sample-project/zones/zone-1/instances/123",
    )
    request = GcpRequests(config(assets=(asset,))).asset(asset, "2026-09-08T12:00:00Z")
    assert request.url == "https://cloudasset.googleapis.com/v1/projects/sample-project/assets"
    params = dict(request.parameters)
    assert params["assetTypes"] == r"^compute\.googleapis\.com/Instance$"
    assert "contentType" not in params
    assert params["fields"] == "readTime,assets(name,assetType,updateTime),nextPageToken"
    with pytest.raises(ProviderContractError):
        GcpRequests(config()).asset(asset, "2026-09-08T12:00:00Z")

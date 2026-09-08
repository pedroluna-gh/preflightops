"""Response provenance, factual semantics and precise freshness regression tests."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_gcp_client import config
from test_gcp_pagination import ASSET, INSTANT, METRIC

from preflightops.gcp_client import GcpReadError
from preflightops.gcp_observations import (
    asset_observation,
    metric_observation,
    project_number,
    resource_observation,
)
from preflightops.gcp_scope import GcpResource

POLICY = GcpResource("policy-1", "policy", "projects/sample-project/alertPolicies/123")
SLO = GcpResource(
    "slo-1", "slo", "projects/sample-project/services/test/serviceLevelObjectives/one"
)


def policy(**changes):
    return {
        "name": POLICY.name,
        "enabled": True,
        "conditions": [{"name": POLICY.name + "/conditions/1"}],
        **changes,
    }


def series(end="2026-09-08T11:59:30Z"):
    return {
        "metric": {"type": METRIC.metric_type},
        "resource": {
            "type": METRIC.resource_type,
            "labels": {"project_id": "sample-project", "instance_id": "one"},
        },
        "points": [{"interval": {"endTime": end}}],
    }


def metric_result(*rows):
    return metric_observation(METRIC, ({"timeSeries": list(rows)},), config(), INSTANT)


def test_project_number_bound_to_id_and_active_state():
    assert (
        project_number(
            {"name": "projects/123456", "projectId": "sample-project", "state": "ACTIVE"}, config()
        )
        == "123456"
    )
    for row in (
        {},
        {"name": "projects/123456", "projectId": "outside-project", "state": "ACTIVE"},
        {"name": "projects/123456", "projectId": "sample-project", "state": "DELETE_REQUESTED"},
    ):
        with pytest.raises(GcpReadError):
            project_number(row, config())


@pytest.mark.parametrize(
    "changes,status",
    [
        ({}, "PASS"),
        ({"enabled": False}, "FAIL"),
        ({"enabled": None}, "UNKNOWN"),
        ({"enabled": 1}, "UNKNOWN"),
        ({"validity": {"code": 3, "message": "sensitive"}}, "FAIL"),
    ],
)
def test_policy_enabled_is_not_coverage(changes, status):
    result = resource_observation(POLICY, policy(**changes), config(), "123456")
    assert result.status == status
    assert "sensitive" not in repr(result)
    if status == "PASS":
        assert "not assessed" in result.summary


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "projects/outside-project/alertPolicies/123"},
        {"conditions": []},
        {"conditions": [{"name": "projects/outside-project/alertPolicies/123/conditions/1"}]},
        {"conditions": [{"name": POLICY.name + "/conditions/1"}] * 2},
        {"validity": {"code": True}},
    ],
)
def test_invalid_policy_never_positive(changes):
    with pytest.raises(GcpReadError, match="INVALID_RESPONSE"):
        resource_observation(POLICY, policy(**changes), config(), "123456")


def test_verified_project_number_alias_is_accepted():
    row = policy()
    row["name"] = row["name"].replace("sample-project", "123456")
    row["conditions"][0]["name"] = row["conditions"][0]["name"].replace("sample-project", "123456")
    assert resource_observation(POLICY, row, config(), "123456").status == "PASS"
    with pytest.raises(GcpReadError):
        resource_observation(POLICY, row, config(), "999")


@pytest.mark.parametrize(
    "period",
    [{"calendarPeriod": "MONTH"}, {"rollingPeriod": "86400s"}, {"rollingPeriod": "2592000.000s"}],
)
def test_slo_definition_does_not_claim_attainment(period):
    result = resource_observation(
        SLO, {"name": SLO.name, "goal": 0.9999, **period}, config(), "123456"
    )
    assert result.status == "PASS" and "not assessed" in result.summary


@pytest.mark.parametrize(
    "changes",
    [
        {"goal": True},
        {"goal": 1},
        {"goal": float("nan")},
        {"rollingPeriod": "1s"},
        {"rollingPeriod": "2678400s"},
        {"rollingPeriod": "86400.1s"},
        {"calendarPeriod": "YEAR"},
        {"calendarPeriod": "DAY", "rollingPeriod": "86400s"},
    ],
)
def test_invalid_slo_rejected(changes):
    row = {"name": SLO.name, "goal": 0.99, "calendarPeriod": "MONTH"}
    if "rollingPeriod" in changes and "calendarPeriod" not in changes:
        row.pop("calendarPeriod")
    row.update(changes)
    with pytest.raises(GcpReadError):
        resource_observation(SLO, row, config(), "123456")


@pytest.mark.parametrize(
    "kind,path",
    [
        ("dashboard", "dashboards/test"),
        ("uptime", "uptimeCheckConfigs/test"),
        ("service", "services/test"),
    ],
)
def test_presence_only_summary(kind, path):
    resource = GcpResource("test", kind, "projects/sample-project/" + path)
    result = resource_observation(resource, {"name": resource.name}, config(), "123456")
    assert result.status == "PASS" and "not assessed" in result.summary


def test_freshness_uses_oldest_latest_series_sample_not_collection_time():
    first, second = series(), series("2026-09-08T11:55:01.999999999Z")
    second["resource"]["labels"]["instance_id"] = "two"
    result = metric_result(first, second)
    assert result.status == "PASS" and result.expires_at == "2026-09-08T12:00:01Z"
    assert "sample-project" not in repr(result)


@pytest.mark.parametrize(
    "end,code", [("2026-09-08T11:55:00Z", "STALE"), ("2026-09-08T12:00:00.000000001Z", "FUTURE")]
)
def test_stale_and_nanosecond_future_are_unknown(end, code):
    result = metric_result(series(end))
    assert result.status == "UNKNOWN" and result.code == code


def test_missing_samples_unknown():
    assert metric_result().code == "MISSING"
    row = series()
    row["points"] = []
    assert metric_result(row).code == "MISSING"


@pytest.mark.parametrize(
    "mutation",
    ["project", "metric", "resource", "duplicate", "interval", "timestamp", "outside-window"],
)
def test_metric_adversarial_responses(mutation):
    row = series()
    if mutation == "project":
        row["resource"]["labels"]["project_id"] = "outside-project"
    elif mutation == "metric":
        row["metric"]["type"] = "custom.googleapis.com/other"
    elif mutation == "resource":
        row["resource"]["type"] = "global"
    elif mutation == "duplicate":
        row["points"] *= 2
    elif mutation == "interval":
        row["points"][0]["interval"]["startTime"] = INSTANT
    elif mutation == "timestamp":
        row["points"][0]["interval"]["endTime"] = "invalid"
    else:
        row["points"][0]["interval"]["endTime"] = "2026-09-08T10:00:00Z"
    with pytest.raises(GcpReadError, match="INVALID_RESPONSE"):
        metric_result(row)


def test_selected_labels_must_match_and_series_can_span_pages():
    selected = replace(METRIC, labels=(("resource.labels.instance_id", "two"),))
    with pytest.raises(GcpReadError):
        metric_observation(selected, ({"timeSeries": [series()]},), config(), INSTANT)
    pages = ({"timeSeries": [series("2026-09-08T11:59:00Z")]}, {"timeSeries": [series()]})
    assert metric_observation(METRIC, pages, config(), INSTANT).status == "PASS"


def test_asset_snapshot_validates_scope_and_does_not_require_recent_mutation():
    asset = {
        "name": ASSET.name,
        "assetType": ASSET.asset_type,
        "updateTime": "2020-01-01T00:00:00Z",
    }
    page = {"readTime": INSTANT, "assets": [asset]}
    result = asset_observation(ASSET, (page,), config(), "123456", INSTANT)
    assert result.status == "PASS" and "not assessed" in result.summary
    assert (
        asset_observation(ASSET, ({"readTime": INSTANT},), config(), "123456", INSTANT).code
        == "MISSING"
    )
    for key, value in [
        ("name", ASSET.name.replace("sample-project", "outside-project")),
        ("assetType", "compute.googleapis.com/Disk"),
        ("updateTime", "2026-09-09T00:00:00Z"),
    ]:
        bad = deepcopy(page)
        bad["assets"][0][key] = value
        with pytest.raises(GcpReadError):
            asset_observation(ASSET, (bad,), config(), "123456", INSTANT)
    with pytest.raises(GcpReadError):
        asset_observation(ASSET, (page, page), config(), "123456", INSTANT)
    with pytest.raises(GcpReadError):
        asset_observation(
            ASSET, ({**page, "readTime": "2026-09-08T11:00:00Z"},), config(), "123456", INSTANT
        )

"""Pagination never promotes incomplete or malformed responses to evidence."""

import json

import pytest
from test_gcp_client import Transport, config, context

from preflightops.gcp_client import GcpClient, GcpReadError, GcpResponse
from preflightops.gcp_scope import GcpAsset, GcpMetric
from preflightops.provider_contract import ProviderContractError

INSTANT = "2026-09-08T12:00:00Z"
METRIC = GcpMetric("metric-1", "compute.googleapis.com/instance/cpu/utilization", "gce_instance")
ASSET = GcpAsset(
    "asset-1",
    "compute.googleapis.com/Instance",
    "//compute.googleapis.com/projects/sample-project/zones/zone-a/instances/instance-1",
)


def response(value):
    return GcpResponse(200, json.dumps(value).encode())


@pytest.mark.parametrize("selection,field", [(METRIC, "timeSeries"), (ASSET, "assets")])
def test_complete_pages_preserve_bounded_query(selection, field):
    cfg = config(metrics=(METRIC,), assets=(ASSET,))

    class RecordingTransport(Transport):
        def get(self, read, *args):
            params = dict(read.parameters)
            assert params.get("pageToken", "") == ("" if self.calls == 0 else "next")
            if field == "timeSeries":
                assert 'resource.labels.project_id = "sample-project"' in params["filter"]
                assert params["interval.endTime"] == INSTANT
            else:
                assert params["readTime"] == INSTANT
            return super().get(read, *args)

    transport = RecordingTransport(response({field: [{}], "nextPageToken": "next"}), response({}))
    assert len(GcpClient(cfg, transport).pages(selection, INSTANT, context())) == 2
    assert transport.calls == 2


@pytest.mark.parametrize(
    "page",
    [
        {"nextPageToken": None},
        {"nextPageToken": 1},
        {"nextPageToken": "x" * 4097},
        {"nextPageToken": "bad\n"},
        {"timeSeries": {}},
        {"timeSeries": [1]},
        {"executionErrors": [{"message": "sensitive"}]},
        {"executionErrors": None},
    ],
)
def test_invalid_pages_rejected(page):
    with pytest.raises(GcpReadError, match="^INVALID_RESPONSE$"):
        GcpClient(config(metrics=(METRIC,)), Transport(response(page))).pages(
            METRIC, INSTANT, context()
        )


def test_repeated_token_stops_before_third_request():
    transport = Transport(response({"nextPageToken": "same"}), response({"nextPageToken": "same"}))
    with pytest.raises(GcpReadError, match="INVALID_RESPONSE"):
        GcpClient(config(metrics=(METRIC,)), transport).pages(METRIC, INSTANT, context())
    assert transport.calls == 2


def test_page_budget_does_not_return_partial_success():
    transport = Transport(response({"timeSeries": [{}], "nextPageToken": "next"}))
    with pytest.raises(GcpReadError, match="INVALID_RESPONSE"):
        GcpClient(config(metrics=(METRIC,), max_pages=1), transport).pages(
            METRIC, INSTANT, context()
        )
    assert transport.calls == 1


def test_later_permission_failure_discards_earlier_pages():
    transport = Transport(response({"nextPageToken": "next"}), GcpResponse(403, b"private"))
    with pytest.raises(GcpReadError, match="^AUTH$"):
        GcpClient(config(metrics=(METRIC,)), transport).pages(METRIC, INSTANT, context())


def test_unselected_metric_never_reaches_transport():
    transport = Transport()
    with pytest.raises(ProviderContractError):
        GcpClient(config(), transport).pages(METRIC, INSTANT, context())
    assert transport.calls == 0

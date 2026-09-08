"""Allowlisted official REST reads derived only from validated GCP configuration."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from urllib.parse import urlencode

from .gcp_scope import GcpAsset, GcpConfig, GcpMetric, GcpResource
from .provider_contract import ProviderContractError, _timestamp

_MONITORING = "https://monitoring.googleapis.com"
_FIELDS = {
    "policy": "name,enabled,conditions/name,validity/code",
    "dashboard": "name",
    "uptime": "name",
    "service": "name",
    "slo": "name,goal,rollingPeriod,calendarPeriod",
}


@dataclass(frozen=True, slots=True)
class GcpRead:
    """Internal projection; do not log URLs or page tokens. No mutation method exists."""

    url: str = field(repr=False)
    parameters: tuple[tuple[str, str], ...] = field(repr=False)

    @property
    def encoded_url(self) -> str:
        return self.url + "?" + urlencode(self.parameters)


class GcpRequests:
    """Project/resource membership is checked again before each planned API read."""

    def __init__(self, config: GcpConfig):
        config.__post_init__()
        self.config = config

    @staticmethod
    def _page(token: str) -> tuple[tuple[str, str], ...]:
        if (
            not isinstance(token, str)
            or len(token) > 4096
            or any(ord(char) < 33 or ord(char) > 126 for char in token)
        ):
            raise ProviderContractError("Invalid bounded GCP page token.")
        return (("pageToken", token),) if token else ()

    def project(self) -> GcpRead:
        self.config.__post_init__()
        return GcpRead(
            "https://cloudresourcemanager.googleapis.com/v3/projects/" + self.config.project_id,
            (("fields", "name,projectId,state"),),
        )

    def validate(self, read: GcpRead) -> None:
        """Reject forged URLs, projections, duplicated parameters and wider filters."""
        if type(read) is not GcpRead or type(read.parameters) is not tuple:
            raise ProviderContractError("Invalid GCP read request.")
        if read == self.project() or any(read == self.resource(r) for r in self.config.resources):
            return
        try:
            params = dict(read.parameters)
            token = params.get("pageToken", "")
            if any(
                "interval.endTime" in params
                and read == self.metric(metric, params["interval.endTime"], token)
                for metric in self.config.metrics
            ) or any(
                "readTime" in params and read == self.asset(asset, params["readTime"], token)
                for asset in self.config.assets
            ):
                return
        except (TypeError, ValueError):
            pass
        raise ProviderContractError("GCP read does not match approved scope and projection.")

    def resource(self, resource: GcpResource) -> GcpRead:
        self.config.__post_init__()
        if type(resource) is not GcpResource or resource not in self.config.resources:
            raise ProviderContractError("Resource was not explicitly selected.")
        resource.__post_init__()
        version = "v1" if resource.kind == "dashboard" else "v3"
        return GcpRead(
            _MONITORING + "/" + version + "/" + resource.name,
            (("fields", _FIELDS[resource.kind]),),
        )

    def metric(self, metric: GcpMetric, evaluated_at: str, page_token: str = "") -> GcpRead:
        self.config.__post_init__()
        if type(metric) is not GcpMetric or metric not in self.config.metrics:
            raise ProviderContractError("Metric was not explicitly selected.")
        end = _timestamp(evaluated_at)
        try:
            start = end - dt.timedelta(seconds=self.config.lookback_seconds)
        except OverflowError:
            raise ProviderContractError("Invalid query interval.") from None
        return GcpRead(
            _MONITORING + "/v3/projects/" + self.config.project_id + "/timeSeries",
            (
                ("filter", metric.query_filter(self.config.project_id)),
                ("interval.startTime", start.strftime("%Y-%m-%dT%H:%M:%SZ")),
                ("interval.endTime", evaluated_at),
                ("view", "FULL"),
                ("pageSize", str(self.config.page_size)),
                # Labels identify series/scope; values are deliberately never retrieved.
                (
                    "fields",
                    "timeSeries(metric,resource,points/interval),nextPageToken,executionErrors",
                ),
                *self._page(page_token),
            ),
        )

    def asset(self, asset: GcpAsset, evaluated_at: str, page_token: str = "") -> GcpRead:
        self.config.__post_init__()
        if type(asset) is not GcpAsset or asset not in self.config.assets:
            raise ProviderContractError("Asset was not explicitly selected.")
        _timestamp(evaluated_at)
        return GcpRead(
            "https://cloudasset.googleapis.com/v1/projects/" + self.config.project_id + "/assets",
            (
                # Asset type accepts RE2: anchor and escape to prevent broader matching.
                ("assetTypes", "^" + re.escape(asset.asset_type) + "$"),
                ("readTime", evaluated_at),
                ("pageSize", str(self.config.page_size)),
                ("fields", "readTime,assets(name,assetType,updateTime),nextPageToken"),
                *self._page(page_token),
            ),
        )

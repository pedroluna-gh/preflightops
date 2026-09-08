"""Pure safe projections of GCP response facts, not risk or CAB decisions."""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from typing import Any

from .evidence import canonical_json
from .gcp_client import GcpReadError
from .gcp_scope import GcpAsset, GcpConfig, GcpMetric, GcpResource
from .provider_contract import ProviderStatus, _timestamp


@dataclass(frozen=True, slots=True)
class Observation:
    status: ProviderStatus
    summary: str
    code: str | None = None
    expires_at: str | None = None


def _invalid() -> GcpReadError:
    return GcpReadError("INVALID_RESPONSE")


def _ns(value: Any) -> int:
    """Parse Google's UTC RFC3339 timestamps without losing nanosecond precision."""
    if type(value) is not str:
        raise _invalid()
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.([0-9]{1,9}))?Z", value)
    if not match:
        raise _invalid()
    try:
        instant = _timestamp(match[1] + "Z")
    except ValueError:
        raise _invalid() from None
    delta = instant - dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + int(
        (match[2] or "").ljust(9, "0")
    )


def project_number(value: dict[str, Any], config: GcpConfig) -> str:
    """A successful project GET binds its number to the approved project ID."""
    name = value.get("name")
    if (
        value.get("projectId") != config.project_id
        or type(name) is not str
        or not re.fullmatch(r"projects/[1-9][0-9]{0,19}", name)
    ):
        raise _invalid()
    if value.get("state") != "ACTIVE":
        raise GcpReadError("UNAVAILABLE")
    return name.split("/")[1]


def _normalized(name: Any, config: GcpConfig, number: str) -> str:
    if type(name) is not str:
        raise _invalid()
    # Only replace the project path component, never arbitrary occurrences.
    prefix = "projects/" + number + "/"
    if name.startswith(prefix):
        return "projects/" + config.project_id + "/" + name[len(prefix) :]
    if name.startswith("//"):
        parts = name.split("/")
        if len(parts) > 5 and parts[3] == "projects" and parts[4] == number:
            parts[4] = config.project_id
            return "/".join(parts)
    return name


def resource_observation(
    selected: GcpResource, value: dict[str, Any], config: GcpConfig, number: str
) -> Observation:
    if _normalized(value.get("name"), config, number) != selected.name:
        raise _invalid()
    if selected.kind == "policy":
        enabled = value.get("enabled")
        if type(enabled) is not bool:
            return Observation("UNKNOWN", "Policy enabled state is not demonstrated.", "MISSING")
        if not enabled:
            return Observation(
                "FAIL", "Expected alert policy is disabled; coverage is not assessed."
            )
        if "validity" in value:
            validity = value["validity"]
            if type(validity) is not dict or type(validity.get("code", 0)) is not int:
                raise _invalid()
            if validity.get("code", 0) != 0:
                return Observation(
                    "FAIL", "Expected alert policy reports an invalid configuration."
                )
        conditions = value.get("conditions")
        if type(conditions) is not list or not 1 <= len(conditions) <= 6:
            raise _invalid()
        names = set()
        for condition in conditions:
            if type(condition) is not dict:
                raise _invalid()
            name = _normalized(condition.get("name"), config, number)
            if (
                not re.fullmatch(
                    re.escape(selected.name) + r"/conditions/[A-Za-z0-9_-]{1,128}", name
                )
                or name in names
            ):
                raise _invalid()
            names.add(name)
        return Observation(
            "PASS", "Expected policy is enabled; alert coverage and delivery are not assessed."
        )
    if selected.kind == "slo":
        goal = value.get("goal")
        if (
            not isinstance(goal, (int, float))
            or isinstance(goal, bool)
            or not math.isfinite(goal)
            or not 0 < goal <= 0.9999
        ):
            raise _invalid()
        if ("rollingPeriod" in value) == ("calendarPeriod" in value):
            raise _invalid()
        if "rollingPeriod" in value:
            rolling = value["rollingPeriod"]
            if type(rolling) is not str or not re.fullmatch(r"[0-9]{1,7}(?:\.0{1,9})?s", rolling):
                raise _invalid()
            seconds = int(rolling[:-1].split(".")[0])
            if not 86400 <= seconds <= 30 * 86400 or seconds % 86400:
                raise _invalid()
        elif value["calendarPeriod"] not in ("DAY", "WEEK", "FORTNIGHT", "MONTH"):
            raise _invalid()
        return Observation(
            "PASS", "Expected SLO definition exists; attainment and SLI adequacy are not assessed."
        )
    return Observation(
        "PASS", "Expected resource exists; operational health and coverage are not assessed."
    )


def metric_observation(
    selected: GcpMetric, pages: tuple[dict[str, Any], ...], config: GcpConfig, evaluated_at: str
) -> Observation:
    now = _ns(evaluated_at)
    oldest = now - config.lookback_seconds * 1_000_000_000
    latest: dict[bytes, int] = {}
    seen: set[tuple[bytes, int]] = set()
    for page in pages:
        for series in page.get("timeSeries", []):
            metric, resource = series.get("metric"), series.get("resource")
            if type(metric) is not dict or type(resource) is not dict:
                raise _invalid()
            if (
                metric.get("type") != selected.metric_type
                or resource.get("type") != selected.resource_type
            ):
                raise _invalid()
            for component in (metric, resource):
                labels = component.get("labels", {})
                if type(labels) is not dict or any(
                    type(k) is not str or type(v) is not str for k, v in labels.items()
                ):
                    raise _invalid()
            if resource.get("labels", {}).get("project_id") != config.project_id:
                raise _invalid()
            for key, expected in selected.labels:
                component_name, _, label = key.split(".")
                actual = metric if component_name == "metric" else resource
                if actual.get("labels", {}).get(label) != expected:
                    raise _invalid()
            identity = canonical_json({"metric": metric, "resource": resource})
            points = series.get("points")
            if type(points) is not list or not points:
                return Observation("UNKNOWN", "Expected metric samples are missing.", "MISSING")
            for point in points:
                if type(point) is not dict or type(point.get("interval")) is not dict:
                    raise _invalid()
                interval = point["interval"]
                end = _ns(interval.get("endTime"))
                if "startTime" in interval and _ns(interval["startTime"]) > end:
                    raise _invalid()
                if end > now:
                    return Observation("UNKNOWN", "Metric timestamps are in the future.", "FUTURE")
                if end < oldest or (identity, end) in seen:
                    raise _invalid()
                seen.add((identity, end))
                latest[identity] = max(latest.get(identity, end), end)
    if not latest:
        return Observation(
            "UNKNOWN", "No metric series returned for the explicit selection.", "MISSING"
        )
    expires = min(latest.values()) + selected.max_sample_age * 1_000_000_000
    # Round down to contract seconds, never extend source validity by rounding.
    seconds = expires // 1_000_000_000
    if seconds * 1_000_000_000 <= now:
        return Observation("UNKNOWN", "One or more selected metric series are stale.", "STALE")
    until = (dt.datetime(1970, 1, 1, tzinfo=dt.UTC) + dt.timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return Observation(
        "PASS",
        "Returned metric series are fresh; complete resource coverage is not assessed.",
        expires_at=until,
    )


def asset_observation(
    selected: GcpAsset,
    pages: tuple[dict[str, Any], ...],
    config: GcpConfig,
    number: str,
    evaluated_at: str,
) -> Observation:
    instant = _ns(evaluated_at)
    names: set[str] = set()
    for page in pages:
        if _ns(page.get("readTime")) != instant:
            raise _invalid()
        for asset in page.get("assets", []):
            name = _normalized(asset.get("name"), config, number)
            if asset.get("assetType") != selected.asset_type or name in names:
                raise _invalid()
            try:
                candidate = GcpAsset(selected.control_id, selected.asset_type, name)
            except ValueError:
                raise _invalid() from None
            if candidate.name.split("/")[4] != config.project_id:
                raise _invalid()
            if "updateTime" in asset and _ns(asset["updateTime"]) > instant:
                raise _invalid()
            names.add(name)
    if selected.name not in names:
        return Observation(
            "UNKNOWN", "Expected asset is not visible in the bounded snapshot.", "MISSING"
        )
    return Observation(
        "PASS", "Expected asset exists in the requested snapshot; configuration is not assessed."
    )

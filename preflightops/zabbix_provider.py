"""Zabbix observations projected into the common contract, never into risk rules."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from typing import Any

from .evidence import canonical_json
from .provider_contract import (
    ProviderContractError,
    ProviderEvidence,
    ProviderStatus,
    _identifier,
    _timestamp,
)
from .provider_runtime import (
    ProviderCapabilities,
    ProviderContext,
    ProviderExecutionError,
    ProviderRequest,
)
from .zabbix_client import ZabbixClient, ZabbixClientError, ZabbixTransport
from .zabbix_transport import PinnedZabbixTransport, ZabbixEndpoint

KINDS = ("host", "triggers", "maintenance", "problems", "events", "freshness")
Query = Callable[[str, dict[str, Any]], Any]


def _id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        raise ProviderContractError("Expected bounded Zabbix object identifier.")
    return value


def _number(value: Any, maximum: int = 4_102_444_800) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]{0,19}", value):
        raise ZabbixClientError("INVALID_RESPONSE")
    result = int(value)
    if result > maximum:
        raise ZabbixClientError("INVALID_RESPONSE")
    return result


@dataclass(frozen=True, slots=True)
class ZabbixConfig:
    endpoint: ZabbixEndpoint = field(repr=False)
    source_reference: str
    host_id: str = field(repr=False)
    trigger_ids: tuple[str, ...] = field(repr=False)
    item_ids: tuple[str, ...] = field(repr=False)
    ttl_seconds: int = 60
    max_sample_age: int = 300
    lookback_seconds: int = 3600
    page_size: int = 100
    max_pages: int = 5
    max_response_bytes: int = 1_048_576
    retries: int = 2
    min_interval_ms: int = 100

    def __post_init__(self) -> None:
        self.endpoint.__post_init__()
        _identifier(self.source_reference)
        if len(self.source_reference) > 80:
            raise ProviderContractError("Source reference exceeds control identity budget.")
        _id(self.host_id)
        for ids in (self.trigger_ids, self.item_ids):
            if type(ids) is not tuple or len(ids) > 100:
                raise ProviderContractError("Expected bounded immutable Zabbix selection.")
            for value in ids:
                _id(value)
            if len(ids) != len(set(ids)) or ids != tuple(sorted(ids, key=int)):
                raise ProviderContractError("Zabbix selections must be unique and ordered.")
        for budget, low, high in (
            (self.ttl_seconds, 1, 3600),
            (self.max_sample_age, 1, 86400),
            (self.lookback_seconds, 1, 604800),
            (self.page_size, 1, 1000),
            (self.max_pages, 1, 20),
            (self.max_response_bytes, 256, 4_194_304),
            (self.retries, 0, 3),
            (self.min_interval_ms, 1, 10_000),
        ):
            if type(budget) is not int or not low <= budget <= high:
                raise ProviderContractError("Invalid Zabbix configuration budget.")

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(asdict(self))).hexdigest()


class ZabbixProvider:
    """One explicit host scope per instance; use an approved opaque source alias."""

    def __init__(self, config: ZabbixConfig, *, transport: ZabbixTransport | None = None):
        config.__post_init__()
        self.config = config
        self.capabilities = ProviderCapabilities(
            "zabbix", "1.0.0", tuple(config.source_reference + "." + kind for kind in KINDS)
        )
        self._client = ZabbixClient(
            config.endpoint.url,
            transport or PinnedZabbixTransport(config.endpoint),
            retries=config.retries,
            max_response_bytes=config.max_response_bytes,
            min_interval_ms=config.min_interval_ms,
        )
        self._opened = False

    def open(self, request: ProviderRequest, context: ProviderContext) -> None:
        context.remaining()
        if request.configuration_digest != self.config.digest:
            raise ProviderContractError("Zabbix configuration digest mismatch.")
        self._opened = True

    def close(self) -> None:
        self._opened = False
        self._client.close()

    def collect(
        self, request: ProviderRequest, context: ProviderContext
    ) -> Iterator[ProviderEvidence]:
        if not self._opened:
            raise ProviderContractError("Provider lifecycle is not open.")
        version: str | None = None

        def evidence(
            kind: str,
            status: ProviderStatus,
            summary: str,
            code: str | None = None,
            expires: int | None = None,
        ) -> ProviderEvidence:
            instant = _timestamp(request.evaluated_at)
            until = instant + dt.timedelta(seconds=self.config.ttl_seconds)
            if expires is not None:
                until = min(until, dt.datetime.fromtimestamp(expires, tz=dt.UTC))
            return ProviderEvidence(
                "zabbix",
                "1.0.0",
                self.config.source_reference + "." + kind,
                status,
                summary + (" API " + version + "." if version else ""),
                self.config.source_reference,
                request.evaluated_at,
                until.strftime("%Y-%m-%dT%H:%M:%SZ"),
                80 if status in {"PASS", "FAIL"} else 0,
                error_code=code,
            )

        def query(method: str, params: dict[str, Any]) -> Any:
            if version is None:
                raise ZabbixClientError("INVALID_RESPONSE")
            return self._client.call(method, params, context=context, version=version)

        requested = [k for k in KINDS if self.config.source_reference + "." + k in request.controls]
        try:
            version = self._client.discover(context)
        except ZabbixClientError as exc:
            if exc.code in {"TIMEOUT", "CANCELLED"}:
                raise ProviderExecutionError(exc.code) from None
            for kind in requested:
                yield evidence(kind, "ERROR", "Zabbix discovery unavailable.", exc.code)
            return
        for kind in requested:
            context.remaining()
            expires = None
            result: tuple[ProviderStatus, str]
            try:
                if kind == "host":
                    host = self._host(query)
                    result = (
                        ("PASS", "Expected host is enabled.")
                        if _number(host.get("status"), 1) == 0
                        else ("FAIL", "Expected host is disabled.")
                    )
                elif kind == "triggers":
                    self._enabled_host(query)
                    rows = self._triggers(query)
                    if any(_number(row.get("state"), 1) == 1 for row in rows):
                        yield evidence(
                            kind, "UNKNOWN", "Trigger evaluation state is unknown.", "UNAVAILABLE"
                        )
                        continue
                    failed = any(
                        _number(row.get("status"), 1) or _number(row.get("value"), 1)
                        for row in rows
                    )
                    result = (
                        ("FAIL", "Expected triggers are disabled or reporting problems.")
                        if failed
                        else ("PASS", "Expected triggers are enabled and currently OK.")
                    )
                elif kind == "maintenance":
                    host, rows = self._maintenance(query, version)
                    instant = int(_timestamp(request.evaluated_at).timestamp())
                    overlap = False
                    for row in rows:
                        start, end = (
                            _number(row.get("active_since")),
                            _number(row.get("active_till")),
                        )
                        if start >= end:
                            raise ZabbixClientError("INVALID_RESPONSE")
                        overlap |= start <= instant < end
                    if _number(host.get("maintenance_status"), 1):
                        result = ("FAIL", "Host reports effective maintenance.")
                    elif overlap:
                        yield evidence(
                            kind,
                            "UNKNOWN",
                            "Maintenance definition overlaps; recurrence requires review.",
                            "UNAVAILABLE",
                        )
                        continue
                    else:
                        result = (
                            "PASS",
                            "No effective maintenance or overlapping visible definition.",
                        )
                elif kind == "freshness":
                    self._enabled_host(query)
                    rows = self._selected(
                        query,
                        "item.get",
                        "itemid",
                        self.config.item_ids,
                        ["itemid", "hostid", "status", "state", "lastclock"],
                    )
                    now = int(_timestamp(request.evaluated_at).timestamp())
                    clocks = [_number(row.get("lastclock")) for row in rows]
                    if any(clock > now for clock in clocks):
                        yield evidence(
                            kind, "UNKNOWN", "Sample timestamps are in the future.", "FUTURE"
                        )
                        continue
                    if any(
                        clock == 0 or now - clock >= self.config.max_sample_age for clock in clocks
                    ):
                        yield evidence(
                            kind, "UNKNOWN", "Expected samples are absent or expired.", "STALE"
                        )
                        continue
                    failed = any(
                        _number(row.get("status"), 1) or _number(row.get("state"), 1)
                        for row in rows
                    )
                    result = (
                        ("FAIL", "Expected items are disabled or unsupported.")
                        if failed
                        else ("PASS", "Expected item timestamps demonstrate recent collection.")
                    )
                    expires = min(clocks) + self.config.max_sample_age
                else:
                    self._enabled_host(query)
                    triggers = self._triggers(query)
                    states = [
                        (_number(row.get("status"), 1), _number(row.get("state"), 1))
                        for row in triggers
                    ]
                    if any(disabled or unknown for disabled, unknown in states):
                        yield evidence(
                            kind,
                            "UNKNOWN",
                            "Expected triggers cannot demonstrate active evaluation.",
                            "UNAVAILABLE",
                        )
                        continue
                    count = self._events(
                        query, kind, int(_timestamp(request.evaluated_at).timestamp())
                    )
                    result = (
                        ("FAIL", "Problem records observed within the configured interval.")
                        if count
                        else ("PASS", "No problem records in the complete bounded query.")
                    )
                yield evidence(kind, result[0], result[1], expires=expires)
            except ZabbixClientError as exc:
                if exc.code in {"TIMEOUT", "CANCELLED"}:
                    raise ProviderExecutionError(exc.code) from None
                yield evidence(kind, "ERROR", "Zabbix control query unavailable.", exc.code)
            except LookupError:
                yield evidence(
                    kind,
                    "UNKNOWN",
                    "Expected Zabbix objects are not visible or not configured.",
                    "MISSING",
                )

    @staticmethod
    def _rows(value: Any, identity: str, limit: int) -> list[dict[str, Any]]:
        if type(value) is not list or len(value) > limit:
            raise ZabbixClientError("INVALID_RESPONSE")
        seen = set()
        for row in value:
            if type(row) is not dict:
                raise ZabbixClientError("INVALID_RESPONSE")
            try:
                key = _id(row.get(identity))
            except ProviderContractError:
                raise ZabbixClientError("INVALID_RESPONSE") from None
            if key in seen:
                raise ZabbixClientError("INVALID_RESPONSE")
            seen.add(key)
        return value

    def _host(self, query: Query, group_selection: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "hostids": [self.config.host_id],
            "output": ["hostid", "status", "maintenance_status"],
            "limit": 2,
        }
        if group_selection:
            params[group_selection] = ["groupid"]
        rows = self._rows(
            query("host.get", params),
            "hostid",
            1,
        )
        if not rows:
            raise LookupError
        if rows[0]["hostid"] != self.config.host_id:
            raise ZabbixClientError("INVALID_RESPONSE")
        return rows[0]

    def _maintenance(
        self, query: Query, version: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        selection = "selectGroups" if version.startswith("6.") else "selectHostGroups"
        property_name = "groups" if version.startswith("6.") else "hostgroups"
        host = self._host(query, selection)
        groups = self._rows(host.get(property_name), "groupid", 100)
        if not groups:
            raise LookupError
        group_ids = {row["groupid"] for row in groups}
        common = {
            "output": ["maintenanceid", "active_since", "active_till"],
            "limit": self.config.page_size + 1,
        }
        direct = self._rows(
            query("maintenance.get", {**common, "hostids": [self.config.host_id]}),
            "maintenanceid",
            self.config.page_size,
        )
        grouped = self._rows(
            query(
                "maintenance.get",
                {
                    **common,
                    "groupids": sorted(group_ids, key=int),
                    selection: ["groupid"],
                },
            ),
            "maintenanceid",
            self.config.page_size,
        )
        # groupids also matches maintenance assigned to other hosts in these groups.
        # Only actual group assignments affect this host; direct assignments are above.
        merged = {row["maintenanceid"]: row for row in direct}
        for row in grouped:
            assigned = self._rows(row.get(property_name), "groupid", 100)
            if not any(group["groupid"] in group_ids for group in assigned):
                continue
            previous = merged.get(row["maintenanceid"])
            if previous is not None and any(
                previous.get(key) != row.get(key) for key in ("active_since", "active_till")
            ):
                raise ZabbixClientError("INVALID_RESPONSE")
            merged[row["maintenanceid"]] = row
        return host, list(merged.values())

    def _selected(
        self, query: Query, method: str, key: str, ids: tuple[str, ...], output: list[str]
    ) -> list[dict[str, Any]]:
        if not ids:
            raise LookupError
        rows = self._rows(
            query(
                method,
                {
                    key + "s": list(ids),
                    "hostids": [self.config.host_id],
                    "output": output,
                    "limit": len(ids) + 1,
                },
            ),
            key,
            len(ids),
        )
        if any(
            row[key] not in ids or ("hostid" in output and row.get("hostid") != self.config.host_id)
            for row in rows
        ):
            raise ZabbixClientError("INVALID_RESPONSE")
        if {row[key] for row in rows} != set(ids):
            raise LookupError
        return rows

    def _enabled_host(self, query: Query) -> None:
        host = self._host(query)
        if _number(host.get("status"), 1):
            raise ZabbixClientError("UNAVAILABLE")

    def _triggers(self, query: Query) -> list[dict[str, Any]]:
        return self._selected(
            query,
            "trigger.get",
            "triggerid",
            self.config.trigger_ids,
            ["triggerid", "status", "state", "value"],
        )

    def _events(self, query: Query, kind: str, now: int) -> int:
        cursor, total = 0, 0
        for _ in range(self.config.max_pages):
            params: dict[str, Any] = {
                "hostids": [self.config.host_id],
                "objectids": list(self.config.trigger_ids),
                "source": 0,
                "object": 0,
                "time_from": now - self.config.lookback_seconds,
                "time_till": now,
                "eventid_from": str(cursor + 1),
                "sortfield": "eventid",
                "sortorder": "ASC",
                "limit": self.config.page_size,
                "output": ["eventid", "objectid", "clock"],
            }
            if kind == "events":
                params["value"] = 1
            rows = self._rows(
                query("problem.get" if kind == "problems" else "event.get", params),
                "eventid",
                self.config.page_size,
            )
            for row in rows:
                identity = int(row["eventid"])
                timestamp = _number(row.get("clock"))
                if (
                    identity <= cursor
                    or row.get("objectid") not in self.config.trigger_ids
                    or not now - self.config.lookback_seconds <= timestamp <= now
                ):
                    raise ZabbixClientError("INVALID_RESPONSE")
                cursor = identity
            total += len(rows)
            if len(rows) < self.config.page_size:
                return total
        raise ZabbixClientError("INVALID_RESPONSE")

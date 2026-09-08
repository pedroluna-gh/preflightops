"""Bounded JSON-RPC read client. No implicit connection or credential storage."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from .provider_contract import ProviderContractError
from .provider_runtime import ProviderContext, ProviderExecutionError

READ_METHODS = frozenset(
    {
        "apiinfo.version",
        "host.get",
        "trigger.get",
        "maintenance.get",
        "problem.get",
        "event.get",
        "item.get",
    }
)
SUPPORTED_FAMILIES = frozenset({"6.0", "7.0", "7.4"})


class ZabbixClientError(Exception):
    """Static taxonomy; remote messages and request data are never interpolated."""

    def __init__(self, code: str):
        self.code = (
            code
            if code
            in {"AUTH", "RATE_LIMIT", "UNAVAILABLE", "INVALID_RESPONSE", "TIMEOUT", "CANCELLED"}
            else "INVALID_RESPONSE"
        )
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class ZabbixResponse:
    status: int
    body: bytes = field(repr=False)


class ZabbixTransport(Protocol):
    """A transport must enforce TLS, destination, timeout and streamed byte limit."""

    def post(
        self,
        *,
        endpoint: str,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
        max_response_bytes: int,
    ) -> ZabbixResponse: ...

    def close(self) -> None: ...


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ZabbixClientError("INVALID_RESPONSE")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ZabbixClientError("INVALID_RESPONSE")


class ZabbixClient:
    """Explicit token-only client for configured read operations, not a generic SDK."""

    def __init__(
        self,
        endpoint: str,
        transport: ZabbixTransport,
        *,
        max_response_bytes: int = 1_048_576,
        retries: int = 2,
        min_interval_ms: int = 0,
    ):
        if type(max_response_bytes) is not int or not 256 <= max_response_bytes <= 4_194_304:
            raise ProviderContractError("Invalid response budget.")
        if type(retries) is not int or not 0 <= retries <= 3:
            raise ProviderContractError("Invalid retry budget.")
        if type(min_interval_ms) is not int or not 0 <= min_interval_ms <= 10_000:
            raise ProviderContractError("Invalid request interval.")
        self._endpoint = endpoint
        self._transport = transport
        self._limit = max_response_bytes
        self._retries = retries
        self._interval = min_interval_ms / 1000
        self._next_request = 0.0

    def discover(self, context: ProviderContext) -> str:
        value = self.call("apiinfo.version", {}, context=context)
        if not isinstance(value, str) or not re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{1,3}", value):
            raise ZabbixClientError("INVALID_RESPONSE")
        if ".".join(value.split(".")[:2]) not in SUPPORTED_FAMILIES:
            raise ZabbixClientError("UNAVAILABLE")
        return value

    def call(
        self,
        method: str,
        params: dict[str, Any],
        *,
        context: ProviderContext,
        version: str | None = None,
    ) -> Any:
        if not isinstance(method, str) or method not in READ_METHODS or type(params) is not dict:
            raise ProviderContractError("Only approved Zabbix read methods are supported.")
        family = ".".join(version.split(".")[:2]) if isinstance(version, str) else None
        if method != "apiinfo.version" and (
            family not in SUPPORTED_FAMILIES
            or not isinstance(version, str)
            or not re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{1,3}", version)
        ):
            raise ZabbixClientError("UNAVAILABLE")
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        headers = {"Content-Type": "application/json-rpc"}
        context.remaining()
        if method != "apiinfo.version":
            try:
                token = context.credentials()
            except ProviderExecutionError:
                raise
            except Exception:
                raise ZabbixClientError("AUTH") from None
            if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", token):
                raise ZabbixClientError("AUTH")
            if family == "6.0":
                payload["auth"] = token
            else:
                headers["Authorization"] = "Bearer " + token
        try:
            body = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        except (TypeError, ValueError, RecursionError):
            raise ProviderContractError("Invalid bounded JSON-RPC parameters.") from None
        if len(body) > 65_536:
            raise ProviderContractError("JSON-RPC request exceeds budget.")
        for attempt in range(self._retries + 1):
            try:
                delay = max(0.0, self._next_request - context.monotonic())
                if delay:
                    context.cancellation.wait(min(delay, context.remaining()))
                context.remaining()
                self._next_request = context.monotonic() + self._interval
                response = self._transport.post(
                    endpoint=self._endpoint,
                    body=body,
                    headers=headers,
                    timeout=context.remaining(),
                    max_response_bytes=self._limit,
                )
                context.remaining()
            except (ProviderExecutionError, ZabbixClientError):
                raise
            except TimeoutError:
                raise ZabbixClientError("TIMEOUT") from None
            except Exception:
                raise ZabbixClientError("UNAVAILABLE") from None
            if not isinstance(response, ZabbixResponse) or type(response.status) is not int:
                raise ZabbixClientError("INVALID_RESPONSE")
            if response.status in {429, 502, 503, 504} and attempt < self._retries:
                delay = min(0.25 * (2**attempt), context.remaining())
                context.cancellation.wait(delay)
                context.remaining()
                continue
            if response.status in {401, 403}:
                raise ZabbixClientError("AUTH")
            if response.status == 429:
                raise ZabbixClientError("RATE_LIMIT")
            if response.status != 200:
                raise ZabbixClientError("UNAVAILABLE")
            return self._decode(response.body)
        raise ZabbixClientError("UNAVAILABLE")

    def _decode(self, body: bytes) -> Any:
        if type(body) is not bytes or len(body) > self._limit:
            raise ZabbixClientError("INVALID_RESPONSE")
        try:
            data = json.loads(
                body.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant
            )
        except (ValueError, UnicodeError, RecursionError):
            raise ZabbixClientError("INVALID_RESPONSE") from None
        if (
            type(data) is not dict
            or data.get("jsonrpc") != "2.0"
            or type(data.get("id")) is not int
            or data["id"] != 1
            or set(data) not in ({"jsonrpc", "id", "result"}, {"jsonrpc", "id", "error"})
        ):
            raise ZabbixClientError("INVALID_RESPONSE")
        if "error" in data:
            # Zabbix shares JSON-RPC codes between permission and parameter failures.
            # Do not inspect or expose remote error.data/message to guess authorization.
            raise ZabbixClientError("UNAVAILABLE")
        return data["result"]

    def close(self) -> None:
        self._transport.close()

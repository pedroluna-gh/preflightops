"""Bounded read execution and static error taxonomy for official GCP REST APIs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from .gcp_auth import GcpCredentialBinding, bind_adc
from .gcp_requests import GcpRead, GcpRequests
from .gcp_scope import GcpAsset, GcpConfig, GcpMetric
from .provider_runtime import ProviderContext, ProviderExecutionError


class GcpReadError(Exception):
    def __init__(self, code: str):
        self.code = (
            code
            if code
            in {
                "AUTH",
                "MISSING",
                "RATE_LIMIT",
                "UNAVAILABLE",
                "INVALID_RESPONSE",
                "TIMEOUT",
                "CANCELLED",
            }
            else "INVALID_RESPONSE"
        )
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class GcpResponse:
    status: int
    body: bytes = field(repr=False)


class GcpTransport(Protocol):
    """Implementations must enforce streamed byte limits, TLS and context deadlines."""

    def get(
        self,
        read: GcpRead,
        binding: GcpCredentialBinding,
        context: ProviderContext,
        max_response_bytes: int,
    ) -> GcpResponse: ...

    def close(self) -> None: ...


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GcpReadError("INVALID_RESPONSE")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise GcpReadError("INVALID_RESPONSE")


class GcpClient:
    """No arbitrary HTTP method, URL, credential discovery or provider SDK exposure."""

    def __init__(self, config: GcpConfig, transport: GcpTransport):
        self._requests = GcpRequests(config)
        self._config = config
        self._transport = transport
        self._next_request = 0.0

    def read(self, read: GcpRead, context: ProviderContext) -> dict[str, Any]:
        self._requests.validate(read)
        context.remaining()
        binding = bind_adc(
            context, needs_cloud_scope=not read.url.startswith("https://monitoring.googleapis.com/")
        )
        for attempt in range(self._config.retries + 1):
            try:
                delay = max(0.0, self._next_request - context.monotonic())
                if delay:
                    context.cancellation.wait(min(delay, context.remaining()))
                context.remaining()
                self._next_request = context.monotonic() + self._config.min_interval_ms / 1000
                response = self._transport.get(
                    read, binding, context, self._config.max_response_bytes
                )
                context.remaining()
            except (ProviderExecutionError, GcpReadError):
                raise
            except TimeoutError:
                raise GcpReadError("TIMEOUT") from None
            except Exception:
                raise GcpReadError("UNAVAILABLE") from None
            if type(response) is not GcpResponse or type(response.status) is not int:
                raise GcpReadError("INVALID_RESPONSE")
            if response.status in {429, 500, 502, 503, 504} and attempt < self._config.retries:
                context.cancellation.wait(min(0.25 * 2**attempt, context.remaining()))
                context.remaining()
                continue
            if response.status in {401, 403}:
                raise GcpReadError("AUTH")
            if response.status == 404:
                raise GcpReadError("MISSING")
            if response.status == 429:
                raise GcpReadError("RATE_LIMIT")
            if response.status != 200:
                raise GcpReadError("UNAVAILABLE")
            if (
                type(response.body) is not bytes
                or len(response.body) > self._config.max_response_bytes
            ):
                raise GcpReadError("INVALID_RESPONSE")
            try:
                value = json.loads(
                    response.body.decode("utf-8"),
                    object_pairs_hook=_object,
                    parse_constant=_constant,
                )
            except (ValueError, UnicodeError, RecursionError):
                raise GcpReadError("INVALID_RESPONSE") from None
            if type(value) is not dict or "error" in value:
                raise GcpReadError("INVALID_RESPONSE")
            return value
        raise GcpReadError("UNAVAILABLE")

    def pages(
        self,
        selection: GcpMetric | GcpAsset,
        evaluated_at: str,
        context: ProviderContext,
    ) -> tuple[dict[str, Any], ...]:
        """Return complete bounded pages only; never expose a partial collection.

        Resource membership and the unchanged query are validated on every page.
        Callers must still validate resource provenance and freshness before use.
        Memory is bounded by max_pages * max_response_bytes before JSON overhead.
        """
        if type(selection) is GcpMetric:
            collection = "timeSeries"
        elif type(selection) is GcpAsset:
            collection = "assets"
        else:
            from .provider_contract import ProviderContractError

            raise ProviderContractError("Unsupported paginated GCP selection.")
        token = ""
        seen: set[str] = set()
        pages: list[dict[str, Any]] = []
        for _ in range(self._config.max_pages):
            read = (
                self._requests.metric(selection, evaluated_at, token)
                if isinstance(selection, GcpMetric)
                else self._requests.asset(selection, evaluated_at, token)
            )
            page = self.read(read, context)
            items = page.get(collection, [])
            if type(items) is not list or any(type(item) is not dict for item in items):
                raise GcpReadError("INVALID_RESPONSE")
            if "executionErrors" in page and page["executionErrors"] != []:
                raise GcpReadError("INVALID_RESPONSE")
            next_token = page.get("nextPageToken", "")
            if (
                type(next_token) is not str
                or len(next_token) > 4096
                or any(ord(char) < 33 or ord(char) > 126 for char in next_token)
                or next_token in seen
            ):
                raise GcpReadError("INVALID_RESPONSE")
            pages.append(page)
            if not next_token:
                return tuple(pages)
            seen.add(next_token)
            token = next_token
        raise GcpReadError("INVALID_RESPONSE")

    def close(self) -> None:
        try:
            self._transport.close()
        except Exception:
            raise GcpReadError("UNAVAILABLE") from None

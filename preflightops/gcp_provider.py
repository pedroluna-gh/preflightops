"""Read-only GCP Evidence Provider v1 with independent, safe control facts."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from dataclasses import replace

from .gcp_client import GcpClient, GcpReadError, GcpTransport
from .gcp_observations import (
    Observation,
    asset_observation,
    metric_observation,
    project_number,
    resource_observation,
)
from .gcp_requests import GcpRequests
from .gcp_scope import GcpAsset, GcpConfig, GcpMetric, GcpResource
from .gcp_transport import GcpHttpsTransport
from .provider_contract import ProviderContractError, ProviderEvidence, _timestamp
from .provider_runtime import (
    ProviderCapabilities,
    ProviderContext,
    ProviderExecutionError,
    ProviderRequest,
)


class GcpProvider:
    """No discovery at construction; one injected principal per collection lifecycle."""

    def __init__(self, config: GcpConfig, *, transport: GcpTransport | None = None):
        config.__post_init__()
        self.config = config
        self.capabilities = ProviderCapabilities(
            "gcp",
            "1.0.0",
            tuple(
                config.project_reference + "." + key
                for key in (
                    "identity",
                    *(r.control_id for r in config.resources),
                    *(m.control_id for m in config.metrics),
                    *(a.control_id for a in config.assets),
                )
            ),
        )
        self._transport = transport
        self._client: GcpClient | None = None
        self._request: ProviderRequest | None = None
        self._context: ProviderContext | None = None
        self._collected = False

    def open(self, request: ProviderRequest, context: ProviderContext) -> None:
        context.remaining()
        self.config.__post_init__()
        request.__post_init__()
        if (
            self._client is not None
            or request.configuration_digest != self.config.digest
            or not set(request.controls) <= set(self.capabilities.controls)
        ):
            raise ProviderContractError("Invalid GCP lifecycle or request configuration.")
        # Resolve once, never switch to another principal halfway through the run.
        credentials = context.credentials()
        self._context = replace(context, credential_supplier=lambda: credentials)
        self._client = GcpClient(self.config, self._transport or GcpHttpsTransport(self.config))
        self._request = request
        self._collected = False

    def close(self) -> None:
        client = self._client
        self._client = None
        self._request = None
        self._context = None
        if client is not None:
            client.close()

    def _evidence(
        self, key: str, result: Observation, request: ProviderRequest
    ) -> ProviderEvidence:
        until = _timestamp(request.evaluated_at) + dt.timedelta(seconds=self.config.ttl_seconds)
        if result.expires_at is not None:
            until = min(until, _timestamp(result.expires_at))
        return ProviderEvidence(
            "gcp",
            "1.0.0",
            key,
            result.status,
            result.summary,
            self.config.project_reference + "." + self.config.principal_reference,
            request.evaluated_at,
            until.strftime("%Y-%m-%dT%H:%M:%SZ"),
            80 if result.status in {"PASS", "FAIL"} else 0,
            error_code=result.code,
        )

    @staticmethod
    def _failure(error: GcpReadError) -> Observation:
        if error.code in {"TIMEOUT", "CANCELLED"}:
            raise ProviderExecutionError(error.code) from None
        return Observation(
            "UNKNOWN" if error.code == "MISSING" else "ERROR",
            "GCP observation unavailable; no positive conclusion is supported.",
            error.code,
        )

    def collect(
        self, request: ProviderRequest, context: ProviderContext
    ) -> Iterator[ProviderEvidence]:
        context.remaining()
        if (
            self._client is None
            or self._context is None
            or self._request != request
            or self._collected
        ):
            raise ProviderContractError("GCP lifecycle is not open for this collection.")
        self._collected = True
        client, bound = self._client, self._context
        reads = GcpRequests(self.config)
        try:
            number = project_number(client.read(reads.project(), bound), self.config)
        except GcpReadError as exc:
            failure = self._failure(exc)
            for key in sorted(request.controls):
                yield self._evidence(key, failure, request)
            return
        items: tuple[GcpResource | GcpMetric | GcpAsset, ...] = (
            *self.config.resources,
            *self.config.metrics,
            *self.config.assets,
        )
        selections = {item.control_id: item for item in items}
        for key in sorted(request.controls):
            bound.remaining()
            control = key[len(self.config.project_reference) + 1 :]
            try:
                if control == "identity":
                    result = Observation(
                        "UNKNOWN",
                        "Project access verified; principal alias and effective OAuth scopes are not independently attested.",
                        "UNAVAILABLE",
                    )
                else:
                    selected = selections[control]
                    if isinstance(selected, GcpResource):
                        result = resource_observation(
                            selected,
                            client.read(reads.resource(selected), bound),
                            self.config,
                            number,
                        )
                    elif isinstance(selected, GcpMetric):
                        result = metric_observation(
                            selected,
                            client.pages(selected, request.evaluated_at, bound),
                            self.config,
                            request.evaluated_at,
                        )
                    else:
                        result = asset_observation(
                            selected,
                            client.pages(selected, request.evaluated_at, bound),
                            self.config,
                            number,
                            request.evaluated_at,
                        )
            except GcpReadError as exc:
                result = self._failure(exc)
            yield self._evidence(key, result, request)

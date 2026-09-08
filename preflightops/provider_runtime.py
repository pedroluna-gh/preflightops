"""Explicit read-only provider lifecycle with cooperative cancellation.

Adapters must enforce context.remaining() at every blocking transport operation.
This in-process runner rejects late output; it cannot kill arbitrary Python code.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Protocol

from .evidence import canonical_json
from .provider_contract import ProviderContractError, ProviderEvidence, _identifier, _timestamp


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    provider: str
    version: str
    controls: tuple[str, ...]
    read_only: bool = True

    def __post_init__(self) -> None:
        _identifier(self.provider)
        _identifier(self.version)
        if type(self.controls) is not tuple or not 1 <= len(self.controls) <= 256:
            raise ProviderContractError("Expected bounded immutable controls.")
        for control in self.controls:
            _identifier(control)
        if len(set(self.controls)) != len(self.controls) or self.read_only is not True:
            raise ProviderContractError("Only unique read-only capabilities are supported.")


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    context_digest: str
    configuration_digest: str
    controls: tuple[str, ...]
    evaluated_at: str
    timeout_seconds: float = 10

    def __post_init__(self) -> None:
        for digest in (self.context_digest, self.configuration_digest):
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                raise ProviderContractError("Expected approved SHA-256 context/configuration.")
        ProviderCapabilities("request", "1", self.controls)
        _timestamp(self.evaluated_at)
        if (
            type(self.timeout_seconds) not in (int, float)
            or not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= 120
        ):
            raise ProviderContractError("Timeout must be finite and bounded.")


class ProviderExecutionError(Exception):
    """Static execution taxonomy; never wraps a remote exception message."""

    def __init__(self, code: str):
        self.code = (
            code
            if code in {"TIMEOUT", "CANCELLED", "AUTH", "RATE_LIMIT", "UNAVAILABLE"}
            else "INTERNAL"
        )
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class ProviderContext:
    deadline: float
    cancellation: threading.Event = field(repr=False)
    credential_supplier: Callable[[], object] = field(repr=False)
    monotonic: Callable[[], float] = field(repr=False, default=time.monotonic)

    def remaining(self) -> float:
        if self.cancellation.is_set():
            raise ProviderExecutionError("CANCELLED")
        remaining = self.deadline - self.monotonic()
        if not math.isfinite(remaining) or remaining <= 0:
            raise ProviderExecutionError("TIMEOUT")
        return remaining

    def credentials(self) -> object:
        self.remaining()
        result = self.credential_supplier()
        self.remaining()
        return result


class EvidenceProvider(Protocol):
    capabilities: ProviderCapabilities

    def open(self, request: ProviderRequest, context: ProviderContext) -> None: ...
    def collect(
        self, request: ProviderRequest, context: ProviderContext
    ) -> Iterable[ProviderEvidence]: ...
    def close(self) -> None: ...


class ProviderRunner:
    """One execution at a time; bounded cache contains only immutable evidence."""

    def __init__(
        self, *, cache_capacity: int = 32, monotonic: Callable[[], float] = time.monotonic
    ):
        if type(cache_capacity) is not int or not 0 <= cache_capacity <= 1024:
            raise ProviderContractError("Invalid cache capacity.")
        self._capacity = cache_capacity
        self._clock = monotonic
        self._cache: OrderedDict[str, tuple[ProviderEvidence, ...]] = OrderedDict()
        self._lock = threading.Lock()

    def run(
        self,
        provider: EvidenceProvider,
        request: ProviderRequest,
        *,
        credentials: Callable[[], object] = lambda: None,
        cancellation: threading.Event | None = None,
    ) -> tuple[ProviderEvidence, ...]:
        with self._lock:
            return self._run(provider, request, credentials, cancellation or threading.Event())

    def _run(
        self,
        provider: EvidenceProvider,
        request: ProviderRequest,
        credentials: Callable[[], object],
        cancellation: threading.Event,
    ) -> tuple[ProviderEvidence, ...]:
        cap = provider.capabilities
        cap.__post_init__()
        request.__post_init__()
        if not set(request.controls) <= set(cap.controls):
            raise ProviderContractError("Requested control is not supported.")
        context = ProviderContext(
            self._clock() + request.timeout_seconds, cancellation, credentials, self._clock
        )
        key = hashlib.sha256(
            canonical_json(
                {
                    "provider": cap.provider,
                    "version": cap.version,
                    "context": request.context_digest,
                    "configuration": request.configuration_digest,
                    "controls": sorted(request.controls),
                }
            )
        ).hexdigest()

        def failure(control: str, code: str) -> ProviderEvidence:
            until = (_timestamp(request.evaluated_at) + dt.timedelta(seconds=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            return ProviderEvidence(
                cap.provider,
                cap.version,
                control,
                "UNKNOWN" if code == "MISSING" else "ERROR",
                "Provider evidence unavailable.",
                "provider-runtime",
                request.evaluated_at,
                until,
                0,
                error_code=code,
            )

        try:
            context.remaining()
        except ProviderExecutionError as exc:
            return tuple(failure(c, exc.code) for c in sorted(request.controls))
        cached = self._cache.pop(key, None)
        if cached is not None and all(
            _timestamp(e.collected_at)
            <= _timestamp(request.evaluated_at)
            < _timestamp(e.valid_until)
            for e in cached
        ):
            self._cache[key] = cached
            return cached
        result: dict[str, ProviderEvidence] = {}
        error: str | None = None
        try:
            provider.open(request, context)
            context.remaining()
            for evidence in provider.collect(request, context):
                context.remaining()
                if not isinstance(evidence, ProviderEvidence):
                    raise ProviderContractError("Invalid provider response.")
                evidence.__post_init__()
                if (
                    evidence.provider != cap.provider
                    or evidence.provider_version != cap.version
                    or evidence.control_id not in request.controls
                    or evidence.control_id in result
                ):
                    raise ProviderContractError("Response identity mismatch or duplicate.")
                instant = _timestamp(request.evaluated_at)
                if (
                    not _timestamp(evidence.collected_at)
                    <= instant
                    < _timestamp(evidence.valid_until)
                ):
                    code = "FUTURE" if instant < _timestamp(evidence.collected_at) else "STALE"
                    evidence = replace(
                        evidence,
                        status=evidence.status
                        if evidence.status in {"FAIL", "ERROR"}
                        else "UNKNOWN",
                        confidence=0,
                        error_code=evidence.error_code
                        if evidence.status in {"FAIL", "ERROR"}
                        else code,
                        not_applicable_reason=None,
                    )
                result[evidence.control_id] = evidence
            context.remaining()
        except ProviderExecutionError as exc:
            error = exc.code
        except ProviderContractError:
            error = "INVALID_RESPONSE"
            result.clear()
        except Exception:
            error = "INTERNAL"
        finally:
            try:
                provider.close()
                context.remaining()
            except ProviderExecutionError as exc:
                error = exc.code
                result.clear()
            except Exception:
                error = "INTERNAL"
                result.clear()
        # A terminal failure must remain observable even if every control was yielded.
        if error in {"TIMEOUT", "CANCELLED"} or (
            error is not None and len(result) == len(request.controls)
        ):
            result.clear()
        output = tuple(
            result.get(c) or failure(c, error or "MISSING") for c in sorted(request.controls)
        )
        if (
            not error
            and all(e.status not in {"UNKNOWN", "ERROR"} for e in output)
            and self._capacity
        ):
            self._cache[key] = output
            while len(self._cache) > self._capacity:
                self._cache.popitem(last=False)
        return output


@dataclass
class FakeProvider:
    """Reference adapter: deterministic fixtures, no credentials or network."""

    capabilities: ProviderCapabilities
    evidence: tuple[ProviderEvidence, ...]
    calls: int = field(default=0, init=False)
    opened: bool = field(default=False, init=False)

    def open(self, request: ProviderRequest, context: ProviderContext) -> None:
        context.remaining()
        self.opened = True

    def collect(
        self, request: ProviderRequest, context: ProviderContext
    ) -> Iterable[ProviderEvidence]:
        context.remaining()
        self.calls += 1
        return tuple(e for e in self.evidence if e.control_id in request.controls)

    def close(self) -> None:
        self.opened = False

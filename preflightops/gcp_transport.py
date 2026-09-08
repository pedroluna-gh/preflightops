"""Official ADC authentication and bounded HTTPS reads, with no ambient discovery.

Resource traffic is GET-only. Credential refresh is a separate, narrowly allowed
token exchange, not permission to mutate GCP resources. Deadlines are cooperative:
requests cannot interrupt arbitrary credential code or OS DNS resolution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .gcp_auth import GcpCredentialBinding
from .gcp_client import GcpReadError, GcpResponse
from .gcp_requests import GcpRead, GcpRequests
from .gcp_scope import GcpConfig
from .provider_contract import ProviderContractError
from .provider_runtime import ProviderContext, ProviderExecutionError

_TOKEN_ENDPOINTS = frozenset(
    {"https://oauth2.googleapis.com/token", "https://sts.googleapis.com/v1/token"}
)
_IMPERSONATION = re.compile(
    r"https://iamcredentials\.googleapis\.com/v1/projects/-/serviceAccounts/"
    r"[a-zA-Z0-9._@%-]{1,254}:generateAccessToken\Z"
)


@dataclass(frozen=True, slots=True)
class _AuthResponse:
    status: int
    data: bytes = field(repr=False)
    headers: dict[str, str] = field(repr=False)


def _exchange(
    session: Any,
    method: str,
    url: str,
    context: ProviderContext,
    limit: int,
    *,
    headers: Any,
    body: bytes | str | None = None,
) -> _AuthResponse:
    remaining = context.remaining()
    response = session.request(
        method,
        url,
        headers=headers,
        data=body,
        timeout=(min(5.0, remaining), min(1.0, remaining)),
        allow_redirects=False,
        stream=True,
        verify=True,
        proxies={},
    )
    try:
        context.remaining()
        if type(response.status_code) is not int:
            raise GcpReadError("INVALID_RESPONSE")
        # Neither error payloads nor redirect bodies are needed by the provider.
        if response.status_code != 200:
            return _AuthResponse(response.status_code, b"{}", {})
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            if not re.fullmatch(r"[0-9]{1,12}", content_length) or int(content_length) > limit:
                raise GcpReadError("INVALID_RESPONSE")
        content = bytearray()
        for chunk in response.iter_content(chunk_size=min(4096, limit + 1)):
            context.remaining()
            if type(chunk) is not bytes or len(content) + len(chunk) > limit:
                raise GcpReadError("INVALID_RESPONSE")
            content.extend(chunk)
        context.remaining()
        return _AuthResponse(response.status_code, bytes(content), {})
    finally:
        response.close()


class _RefreshRequest:
    """google-auth Request-compatible callback with a finite refresh budget."""

    def __init__(self, session: Any, context: ProviderContext):
        self._session = session
        self._context = context
        self._calls = 0
        self._active = True

    def close(self) -> None:
        self._active = False

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | str | None = None,
        headers: Any = None,
        timeout: Any = None,
        **kwargs: Any,
    ) -> _AuthResponse:
        self._context.remaining()
        if (
            not self._active
            or type(url) is not str
            or method != "POST"
            or (url not in _TOKEN_ENDPOINTS and not _IMPERSONATION.fullmatch(url))
            or kwargs
            or self._calls >= 4
            or (body is not None and type(body) not in (bytes, str))
        ):
            raise GcpReadError("AUTH")
        encoded = body.encode("utf-8") if isinstance(body, str) else body
        if encoded is not None and len(encoded) > 16384:
            raise GcpReadError("AUTH")
        self._calls += 1
        return _exchange(
            self._session, "POST", url, self._context, 131072, headers=headers, body=encoded
        )


class GcpHttpsTransport:
    """One disposable requests session per read; official credentials sign it.

    Injected credential objects are trusted executable dependencies, not user
    configuration. Metadata/external subject-token retrieval must be performed
    by an explicitly approved supplier outside this transport. Never use default().
    """

    def __init__(self, config: GcpConfig):
        self._requests = GcpRequests(config)
        self._limit = config.max_response_bytes
        self._closed = False

    def get(
        self,
        read: GcpRead,
        binding: GcpCredentialBinding,
        context: ProviderContext,
        max_response_bytes: int,
    ) -> GcpResponse:
        self._requests.validate(read)
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= self._limit:
            raise ProviderContractError("Invalid GCP transport response budget.")
        if self._closed:
            raise GcpReadError("UNAVAILABLE")
        context.remaining()
        try:
            import requests
            from google.auth.credentials import AnonymousCredentials, Credentials
        except ImportError:
            raise GcpReadError("UNAVAILABLE") from None
        if (
            type(binding) is not GcpCredentialBinding
            or not isinstance(binding.credentials, Credentials)
            or isinstance(binding.credentials, AnonymousCredentials)
            or getattr(binding.credentials, "_use_non_blocking_refresh", False) is not False
        ):
            raise GcpReadError("AUTH")
        try:
            with requests.Session() as session:
                session.trust_env = False
                headers: dict[str, str] = {"Accept": "application/json"}
                refresh = _RefreshRequest(session, context)
                try:
                    binding.credentials.before_request(refresh, "GET", read.encoded_url, headers)
                except (GcpReadError, ProviderExecutionError, requests.exceptions.Timeout):
                    raise
                except Exception:
                    raise GcpReadError("AUTH") from None
                finally:
                    refresh.close()
                context.remaining()
                response = _exchange(
                    session, "GET", read.encoded_url, context, max_response_bytes, headers=headers
                )
                return GcpResponse(response.status, response.data)
        except (GcpReadError, ProviderExecutionError):
            raise
        except requests.exceptions.Timeout:
            raise GcpReadError("TIMEOUT") from None
        except Exception:
            raise GcpReadError("UNAVAILABLE") from None

    def close(self) -> None:
        self._closed = True

"""Explicit official ADC binding. Never discover or refresh ambient credentials here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .provider_contract import ProviderContractError
from .provider_runtime import ProviderContext, ProviderExecutionError

MONITORING_SCOPE = "https://www.googleapis.com/auth/monitoring.read"
CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


@dataclass(frozen=True, slots=True)
class GcpCredentialBinding:
    """Credentials remain private; metadata is not proof of effective IAM identity."""

    credentials: Any = field(repr=False)
    requested_scopes: tuple[str, ...]
    scopes_confirmed: bool


def bind_adc(context: ProviderContext, *, needs_cloud_scope: bool) -> GcpCredentialBinding:
    """Accept injected official credentials and scope a copy if required.

    This does not call google.auth.default(), a metadata endpoint, refresh, or
    token introspection. User ADC can lack scope information; return that uncertainty.
    """
    if type(needs_cloud_scope) is not bool:
        raise ProviderContractError("Invalid requested credential scope.")
    try:
        from google.auth.credentials import (
            AnonymousCredentials,
            Credentials,
            with_scopes_if_required,
        )
    except ImportError:
        raise ProviderExecutionError("UNAVAILABLE") from None
    context.remaining()
    try:
        credentials = context.credentials()
        if not isinstance(credentials, Credentials) or isinstance(
            credentials, AnonymousCredentials
        ):
            raise ProviderExecutionError("AUTH")
        # google-auth's optional worker can outlive this bounded collection.
        # Inspect the pinned library flag without mutating caller credentials.
        if getattr(credentials, "_use_non_blocking_refresh", False) is not False:
            raise ProviderExecutionError("AUTH")
        scopes = (CLOUD_SCOPE,) if needs_cloud_scope else (MONITORING_SCOPE,)
        scoped = with_scopes_if_required(credentials, scopes)
        has_scopes = getattr(scoped, "has_scopes", None)
        confirmed = callable(has_scopes) and has_scopes(scopes) is True
        context.remaining()
        return GcpCredentialBinding(scoped, scopes, confirmed)
    except ProviderExecutionError:
        raise
    except Exception:
        raise ProviderExecutionError("AUTH") from None

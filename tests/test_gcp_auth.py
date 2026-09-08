"""Official credential objects injected without token refresh or ambient discovery."""

import threading

import pytest
from google.auth.credentials import AnonymousCredentials, Credentials

from preflightops.gcp_auth import CLOUD_SCOPE, MONITORING_SCOPE, bind_adc
from preflightops.provider_runtime import ProviderContext, ProviderExecutionError


class InjectedCredentials(Credentials):
    def refresh(self, request):
        pytest.fail("Binding must never refresh credentials")


def context(supplier):
    return ProviderContext(10, threading.Event(), supplier, lambda: 0)


@pytest.mark.parametrize("cloud,expected", [(False, MONITORING_SCOPE), (True, CLOUD_SCOPE)])
def test_binding_does_not_invent_scope_or_identity(cloud, expected):
    credentials = InjectedCredentials()
    result = bind_adc(context(lambda: credentials), needs_cloud_scope=cloud)
    assert result.credentials is credentials
    assert result.requested_scopes == (expected,)
    assert result.scopes_confirmed is False
    assert "InjectedCredentials" not in repr(result)


@pytest.mark.parametrize("value", [None, "synthetic-not-adc", {}, AnonymousCredentials()])
def test_invalid_or_anonymous_credentials_rejected(value):
    with pytest.raises(ProviderExecutionError, match="AUTH"):
        bind_adc(context(lambda: value), needs_cloud_scope=False)


def test_credential_supplier_failure_is_redacted():
    def supplier():
        raise ValueError("secret content should not escape")

    with pytest.raises(ProviderExecutionError) as error:
        bind_adc(context(supplier), needs_cloud_scope=False)
    assert str(error.value) == "AUTH"


def test_cancelled_binding_does_not_access_supplier():
    ctx = context(lambda: pytest.fail("Unexpected credential access"))
    ctx.cancellation.set()
    with pytest.raises(ProviderExecutionError, match="CANCELLED"):
        bind_adc(ctx, needs_cloud_scope=False)


def test_nonblocking_binding_rejected_without_mutating_credentials():
    credentials = InjectedCredentials()
    credentials.with_non_blocking_refresh()
    with pytest.raises(ProviderExecutionError, match="^AUTH$"):
        bind_adc(context(lambda: credentials), needs_cloud_scope=False)
    assert credentials._use_non_blocking_refresh is True

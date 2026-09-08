"""Read execution uses synthetic official credentials and in-memory transport."""

import threading
from dataclasses import replace

import pytest
from google.auth.credentials import Credentials

from preflightops.gcp_client import GcpClient, GcpReadError, GcpResponse
from preflightops.gcp_requests import GcpRequests
from preflightops.gcp_scope import GcpConfig
from preflightops.provider_contract import ProviderContractError
from preflightops.provider_runtime import ProviderContext, ProviderExecutionError


class SyntheticCredentials(Credentials):
    def refresh(self, request):
        pytest.fail("No real credential refresh permitted")


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0
        self.closed = False

    def get(self, read, binding, context, max_response_bytes):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


def config(**changes):
    return replace(
        GcpConfig(
            "sample-project",
            ("sample-project",),
            "project-1",
            "principal-1",
            retries=0,
            min_interval_ms=1,
        ),
        **changes,
    )


def context():
    return ProviderContext(10, threading.Event(), SyntheticCredentials, lambda: 0)


def test_success_and_explicit_cleanup():
    cfg = config()
    transport = Transport(GcpResponse(200, b'{"projectId":"sample-project"}'))
    client = GcpClient(cfg, transport)
    assert client.read(GcpRequests(cfg).project(), context()) == {"projectId": "sample-project"}
    client.close()
    assert transport.closed


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "AUTH"),
        (403, "AUTH"),
        (404, "MISSING"),
        (429, "RATE_LIMIT"),
        (500, "UNAVAILABLE"),
        (302, "UNAVAILABLE"),
    ],
)
def test_http_failures_static_and_not_positive(status, code):
    cfg = config()
    with pytest.raises(GcpReadError) as error:
        GcpClient(cfg, Transport(GcpResponse(status, b"sensitive remote message"))).read(
            GcpRequests(cfg).project(), context()
        )
    assert str(error.value) == code


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b"not-json",
        b'{"error":{"message":"sensitive"}}',
        b"\xff",
        b"x" * 257,
    ],
)
def test_malformed_and_oversized_response_rejected(body):
    cfg = config(max_response_bytes=256)
    with pytest.raises(GcpReadError, match="INVALID_RESPONSE"):
        GcpClient(cfg, Transport(GcpResponse(200, body))).read(
            GcpRequests(cfg).project(), context()
        )


def test_forged_url_rejected_before_credentials():
    cfg = config()
    ctx = ProviderContext(
        10, threading.Event(), lambda: pytest.fail("No credentials allowed"), lambda: 0
    )
    read = replace(GcpRequests(cfg).project(), url="https://attacker.invalid/")
    with pytest.raises(ProviderContractError):
        GcpClient(cfg, Transport()).read(read, ctx)


def test_cancellation_before_transport():
    cfg = config()
    ctx = context()
    ctx.cancellation.set()
    transport = Transport()
    with pytest.raises(ProviderExecutionError, match="CANCELLED"):
        GcpClient(cfg, transport).read(GcpRequests(cfg).project(), ctx)
    assert transport.calls == 0


def test_retries_are_bounded():
    cfg = config(retries=1)
    transport = Transport(GcpResponse(503, b""), GcpResponse(200, b"{}"))
    assert GcpClient(cfg, transport).read(GcpRequests(cfg).project(), context()) == {}
    assert transport.calls == 2


@pytest.mark.parametrize(
    "exception,code",
    [(TimeoutError("sensitive"), "TIMEOUT"), (OSError("sensitive"), "UNAVAILABLE")],
)
def test_transport_exceptions_redacted(exception, code):
    cfg = config()
    with pytest.raises(GcpReadError) as error:
        GcpClient(cfg, Transport(exception)).read(GcpRequests(cfg).project(), context())
    assert str(error.value) == code

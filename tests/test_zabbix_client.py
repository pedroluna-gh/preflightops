"""Offline JSON-RPC protocol fixtures, never a live Zabbix instance."""

import json
import threading

import pytest

from preflightops.provider_contract import ProviderContractError
from preflightops.provider_runtime import ProviderContext, ProviderExecutionError
from preflightops.zabbix_client import ZabbixClient, ZabbixClientError, ZabbixResponse


class Transport:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.closed = False

    def post(self, **kwargs):
        self.calls.append(kwargs)
        return self.response

    def close(self):
        self.closed = True


def test_request_rate_is_bounded_across_calls():
    clock = [0.0]
    waits = []

    class Event:
        def is_set(self):
            return False

        def wait(self, seconds):
            waits.append(seconds)
            clock[0] += seconds
            return False

    ctx = ProviderContext(10, Event(), lambda: "synthetic-test-token-0001", lambda: clock[0])
    client = ZabbixClient("unused", Transport(response([])), min_interval_ms=250)
    for _ in range(3):
        client.call("host.get", {}, context=ctx, version="7.0.30")
    assert waits == [0.25, 0.25]


def test_rate_wait_obeys_cancellation_before_next_request():
    cancellation = threading.Event()
    ctx = ProviderContext(10, cancellation, lambda: "synthetic-test-token-0001", lambda: 0)
    transport = Transport(response([]))
    client = ZabbixClient("unused", transport, min_interval_ms=250)
    client.call("host.get", {}, context=ctx, version="7.0.30")
    cancellation.set()
    with pytest.raises(ProviderExecutionError, match="CANCELLED"):
        client.call("host.get", {}, context=ctx, version="7.0.30")
    assert len(transport.calls) == 1


def context(supplier=lambda: "synthetic-test-token-0001"):
    return ProviderContext(10, threading.Event(), supplier, lambda: 0)


def response(value):
    return ZabbixResponse(200, json.dumps({"jsonrpc": "2.0", "id": 1, "result": value}).encode())


@pytest.mark.parametrize("version", ["6.0.42", "7.0.30", "7.4.1"])
def test_version_discovery_never_requests_credentials(version):
    transport = Transport(response(version))
    client = ZabbixClient("https://zabbix.example.test/api_jsonrpc.php", transport)

    def forbidden():
        pytest.fail("Discovery must not access credentials")

    assert client.discover(context(forbidden)) == version
    assert "Authorization" not in transport.calls[0]["headers"]
    assert "auth" not in json.loads(transport.calls[0]["body"])


@pytest.mark.parametrize("version", ["6.0.42", "7.0.30", "7.4.1"])
def test_token_mechanism_is_explicit_and_not_saved(version):
    transport = Transport(response([]))
    client = ZabbixClient("https://zabbix.example.test/api_jsonrpc.php", transport)
    assert client.call("host.get", {"hostids": ["42"]}, context=context(), version=version) == []
    sent = transport.calls[0]
    assert ("auth" in json.loads(sent["body"])) == version.startswith("6.")
    assert ("Authorization" in sent["headers"]) == version.startswith("7.")
    assert "synthetic-test-token" not in repr(client)
    assert all(
        "synthetic-test-token" not in repr(v) for k, v in vars(client).items() if k != "_transport"
    )
    client.close()
    assert transport.closed


@pytest.mark.parametrize(
    "method", ["host.create", "trigger.update", "event.acknowledge", "user.login", "host.delete"]
)
def test_write_and_login_methods_never_reach_transport(method):
    transport = Transport(response([]))
    with pytest.raises(ProviderContractError):
        ZabbixClient("unused", transport).call(method, {}, context=context(), version="7.4.1")
    assert not transport.calls


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b"not-json",
        b'{"jsonrpc":"2.0","id":true,"result":[]}',
        b'{"jsonrpc":"2.0","id":1,"id":1,"result":[]}',
        b'{"jsonrpc":"2.0","id":2,"result":[]}',
        b'{"jsonrpc":"2.0","id":1,"result":NaN}',
        b"x" * 300,
    ],
)
def test_invalid_responses_fail_without_echo(body):
    transport = Transport(ZabbixResponse(200, body))
    with pytest.raises(ZabbixClientError, match="^INVALID_RESPONSE$"):
        ZabbixClient("unused", transport, max_response_bytes=256).discover(context())


@pytest.mark.parametrize(
    "status,code",
    [(401, "AUTH"), (403, "AUTH"), (429, "RATE_LIMIT"), (500, "UNAVAILABLE"), (302, "UNAVAILABLE")],
)
def test_http_failures_are_static(status, code):
    transport = Transport(ZabbixResponse(status, b"token=private https://internal.test"))
    with pytest.raises(ZabbixClientError, match="^" + code + "$"):
        ZabbixClient("unused", transport, retries=0).discover(context())


def test_unsupported_version_never_sends_authenticated_query():
    transport = Transport(response("8.0.0"))
    with pytest.raises(ZabbixClientError, match="UNAVAILABLE"):
        ZabbixClient("unused", transport).discover(context())
    assert len(transport.calls) == 1


def test_precancelled_request_never_connects():
    ctx = context()
    ctx.cancellation.set()
    transport = Transport(response("7.0.1"))
    with pytest.raises(ProviderExecutionError, match="CANCELLED"):
        ZabbixClient("unused", transport).discover(ctx)
    assert not transport.calls


def test_transient_read_retries_are_bounded_and_do_not_log_response():
    class Event(threading.Event):
        def __init__(self):
            super().__init__()
            self.delays = []

        def wait(self, timeout=None):
            self.delays.append(timeout)
            return False

    event = Event()
    ctx = ProviderContext(10, event, lambda: None, lambda: 0)
    transport = Transport(ZabbixResponse(503, b"sensitive remote body"))
    with pytest.raises(ZabbixClientError, match="^UNAVAILABLE$"):
        ZabbixClient("unused", transport, retries=2).discover(ctx)
    assert len(transport.calls) == 3
    assert event.delays == [0.25, 0.5]


@pytest.mark.parametrize(
    "exception,code",
    [(TimeoutError("token=hidden"), "TIMEOUT"), (OSError("https://internal.test"), "UNAVAILABLE")],
)
def test_transport_exceptions_are_sanitized(exception, code):
    class Failing(Transport):
        def post(self, **kwargs):
            raise exception

    with pytest.raises(ZabbixClientError, match="^" + code + "$"):
        ZabbixClient("unused", Failing(None)).discover(context())


def test_rpc_error_does_not_expose_remote_message_or_data():
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32602, "message": "token=hidden", "data": "https://internal.test"},
        }
    ).encode()
    with pytest.raises(ZabbixClientError, match="^UNAVAILABLE$"):
        ZabbixClient("unused", Transport(ZabbixResponse(200, body))).discover(context())


def test_credential_supplier_exception_is_not_exposed():
    def supplier():
        raise RuntimeError("token=hidden https://internal.test")

    transport = Transport(response([]))
    with pytest.raises(ZabbixClientError, match="^AUTH$"):
        ZabbixClient("unused", transport).call(
            "host.get", {}, context=context(supplier), version="7.4.1"
        )
    assert not transport.calls


@pytest.mark.parametrize("version", ["7.4", "7.4.bad", "7.4.1.extra"])
def test_malformed_version_cannot_request_credentials(version):
    def forbidden():
        pytest.fail("Malformed version must fail before credentials")

    with pytest.raises(ZabbixClientError, match="UNAVAILABLE"):
        ZabbixClient("unused", Transport(response([]))).call(
            "host.get", {}, context=context(forbidden), version=version
        )

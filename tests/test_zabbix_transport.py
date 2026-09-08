"""Pinned HTTPS transport tests with simulated sockets; no network access."""

import json
import ssl

import pytest

from preflightops.provider_contract import ProviderContractError
from preflightops.zabbix_client import ZabbixClientError
from preflightops.zabbix_transport import PinnedZabbixTransport, ZabbixEndpoint

URL = "https://zabbix.example.test/api_jsonrpc.php"


class Socket:
    def __init__(self, wire, clock):
        self.wire = bytearray(wire)
        self.clock = clock
        self.delay = 0
        self.chunk = 8192
        self.sent = []
        self.closed = False
        self.address = None
        self.timeouts = []

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def connect(self, address):
        self.address = address

    def getpeername(self):
        return self.address

    def sendall(self, data):
        self.sent.append(data)

    def recv_into(self, buffer, size):
        self.clock[0] += self.delay
        count = min(len(self.wire), size, self.chunk)
        buffer[:count] = self.wire[:count]
        del self.wire[:count]
        return count

    def close(self):
        self.closed = True


@pytest.fixture
def sockets(monkeypatch):
    clock = [0.0]
    sock = Socket(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}", clock)
    wraps = []
    created = []

    def socket(*args):
        created.append(args)
        return sock

    def wrap(ctx, raw, *, server_hostname):
        assert ctx.check_hostname
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
        wraps.append(server_hostname)
        return raw

    monkeypatch.setattr("preflightops.zabbix_transport.socket.socket", socket)
    monkeypatch.setattr("preflightops.zabbix_transport.ssl.SSLContext.wrap_socket", wrap)
    monkeypatch.setattr("preflightops.zabbix_transport.time.monotonic", lambda: clock[0])
    return sock, wraps, created


def post(transport=None, **changes):
    transport = transport or PinnedZabbixTransport(ZabbixEndpoint(URL, "8.8.8.8"))
    return transport.post(
        **{
            "endpoint": URL,
            "body": json.dumps(
                {"method": "apiinfo.version", "params": {}, "id": 1, "jsonrpc": "2.0"}
            ).encode(),
            "headers": {"Content-Type": "application/json-rpc"},
            "timeout": 5,
            "max_response_bytes": 256,
            **changes,
        }
    )


def test_numeric_pin_tls_hostname_and_resource_cleanup(sockets, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted.example.test:8080")
    sock, wraps, created = sockets
    result = post()
    assert result.status == 200 and result.body == b"{}"
    assert sock.address == ("8.8.8.8", 443)
    assert wraps == ["zabbix.example.test"] and len(created) == 1
    assert sock.closed
    assert b"Host: zabbix.example.test\r\n" in sock.sent[0]
    assert b"POST /api_jsonrpc.php HTTP/1.1" in sock.sent[0]


@pytest.mark.parametrize(
    "url",
    [
        "http://zabbix.example.test/api_jsonrpc.php",
        "https://user:pass@zabbix.example.test/api_jsonrpc.php",
        URL + "?token=x",
        URL + "#x",
        "https://zabbix.example.test/%2e%2e/api_jsonrpc.php",
        "https://zabbix.example.test/a/../api_jsonrpc.php",
        "https://zabbix.example.test:0/api_jsonrpc.php",
        "https://zabbix.example.test/other.php",
        "https://zabbix.example.test\n/api_jsonrpc.php",
    ],
)
def test_bad_endpoints_never_connect(url, sockets):
    with pytest.raises(ProviderContractError):
        ZabbixEndpoint(url, "8.8.8.8")
    assert not sockets[2]


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "169.254.169.254", "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "::ffff:127.0.0.1"],
)
def test_dangerous_pins_rejected_even_with_private_opt_in(ip):
    with pytest.raises(ProviderContractError):
        ZabbixEndpoint(URL, ip, allow_private=True)


def test_private_address_requires_explicit_approval_and_repr_is_redacted():
    with pytest.raises(ProviderContractError):
        ZabbixEndpoint(URL, "10.1.2.3")
    endpoint = ZabbixEndpoint(URL, "10.1.2.3", allow_private=True)
    assert "10.1.2.3" not in repr(endpoint) and "example.test" not in repr(endpoint)


@pytest.mark.parametrize(
    "changes",
    [
        {"endpoint": "https://other.example.test/api_jsonrpc.php"},
        {"timeout": True},
        {"timeout": float("inf")},
        {"timeout": 0},
        {"max_response_bytes": True},
        {"headers": {"Content-Type": "application/json-rpc", "Host": "attacker.test"}},
        {"headers": {"Content-Type": "application/json-rpc", "Authorization": "Bearer x\r\nX: y"}},
        {"body": b'{"method":"host.create"}'},
    ],
)
def test_invalid_request_rejected_before_connection(changes, sockets):
    with pytest.raises(ProviderContractError):
        post(**changes)
    assert not sockets[2]


@pytest.mark.parametrize(
    "wire",
    [
        b"HTTP/1.1 200 OK\r\nContent-Length: 999\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
        b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nTransfer-Encoding: chunked\r\n\r\n",
        b"HTTP/1.1 200 OK\r\n\r\n" + b"x" * 257,
    ],
)
def test_oversized_or_ambiguous_http_response_is_rejected(wire, sockets):
    sock = sockets[0]
    sock.wire = bytearray(wire)
    with pytest.raises(ZabbixClientError, match="INVALID_RESPONSE"):
        post()
    assert sock.closed


def test_redirect_is_returned_without_following_location(sockets):
    sock = sockets[0]
    sock.wire = bytearray(
        b"HTTP/1.1 302 Found\r\nLocation: https://attacker.test\r\nContent-Length: 0\r\n\r\n"
    )
    assert post().status == 302
    assert len(sockets[2]) == 1 and sock.closed


def test_slow_headers_cannot_reset_the_absolute_deadline(sockets):
    sock = sockets[0]
    sock.chunk = 1
    sock.delay = 1
    with pytest.raises(ZabbixClientError, match="TIMEOUT"):
        post(timeout=2)
    assert sock.closed


def test_chunked_body_within_budget(sockets):
    sockets[0].wire = bytearray(
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n"
    )
    assert post().body == b"{}"


def test_truncated_declared_body_fails_closed(sockets):
    sockets[0].wire = bytearray(b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\n{}")
    with pytest.raises(ZabbixClientError, match="INVALID_RESPONSE"):
        post()


def test_duplicate_method_keys_cannot_cross_transport_boundary(sockets):
    with pytest.raises(ProviderContractError):
        post(body=b'{"method":"host.create","method":"host.get"}')
    assert not sockets[2]


def test_tls_failure_is_static_and_socket_is_closed(sockets, monkeypatch):
    def invalid(*args, **kwargs):
        raise ssl.SSLError("https://internal.test sensitive certificate detail")

    monkeypatch.setattr("preflightops.zabbix_transport.ssl.SSLContext.wrap_socket", invalid)
    with pytest.raises(ZabbixClientError, match="^UNAVAILABLE$"):
        post()
    assert sockets[0].closed and not sockets[0].sent


def test_cleanup_failure_cannot_leak_exception_or_return_success(sockets, monkeypatch):
    def failed_close():
        raise OSError("token=hidden https://internal.test")

    monkeypatch.setattr(sockets[0], "close", failed_close)
    with pytest.raises(ZabbixClientError, match="^UNAVAILABLE$"):
        post()

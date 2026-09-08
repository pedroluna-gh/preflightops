"""Faithful HTTP boundary tests: no sockets, real ADC or token services."""

import datetime as dt

import pytest
import requests
from google.oauth2.credentials import Credentials
from test_gcp_client import config, context

from preflightops.gcp_auth import GcpCredentialBinding
from preflightops.gcp_client import GcpReadError
from preflightops.gcp_requests import GcpRequests
from preflightops.gcp_transport import GcpHttpsTransport, _RefreshRequest
from preflightops.provider_contract import ProviderContractError
from preflightops.provider_runtime import ProviderExecutionError


class Response:
    def __init__(self, chunks=(b"{}",), status=200, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.chunks = chunks
        self.closed = False
        self.streamed = False

    def iter_content(self, chunk_size):
        assert 1 <= chunk_size <= 4096
        self.streamed = True
        yield from self.chunks

    def close(self):
        self.closed = True


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.trust_env = True
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def request(self, method, url, **kwargs):
        assert self.trust_env is False
        assert kwargs["allow_redirects"] is False
        assert kwargs["verify"] is True
        assert kwargs["stream"] is True
        assert kwargs["proxies"] == {}
        assert 0 < kwargs["timeout"][0] <= 5
        assert 0 < kwargs["timeout"][1] <= 1
        self.calls.append((method, url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def binding(credentials=None):
    return GcpCredentialBinding(credentials or Credentials("synthetic-access"), (), False)


def get(monkeypatch, session, *, ctx=None, credentials=None):
    monkeypatch.setattr(requests, "Session", lambda: session)
    cfg = config(max_response_bytes=256)
    return GcpHttpsTransport(cfg).get(
        GcpRequests(cfg).project(), binding(credentials), ctx or context(), 256
    )


def test_official_credentials_apply_header_and_only_resource_get(monkeypatch):
    response = Response()
    session = Session(response)
    assert get(monkeypatch, session).body == b"{}"
    assert len(session.calls) == 1
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url.startswith("https://cloudresourcemanager.googleapis.com/v3/projects/sample-project?")
    assert kwargs["headers"]["authorization"] == "Bearer synthetic-access"
    assert response.closed and session.closed


def test_official_user_adc_refresh_is_separate_bounded_token_exchange(monkeypatch):
    credentials = Credentials(
        None,
        refresh_token="synthetic-refresh",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="synthetic-client",
        client_secret="synthetic-client-secret",
    )
    credentials.expiry = dt.datetime(2000, 1, 1)
    token = Response((b'{"access_token":"synthetic-new","expires_in":3600,"token_type":"Bearer"}',))
    resource = Response()
    session = Session(token, resource)
    assert get(monkeypatch, session, credentials=credentials).status == 200
    assert [call[0] for call in session.calls] == ["POST", "GET"]
    assert session.calls[0][1] == "https://oauth2.googleapis.com/token"
    assert token.closed and resource.closed and session.closed


@pytest.mark.parametrize(
    "response",
    [
        Response((b"x" * 200, b"y" * 57)),
        Response(("wrong-type",)),
        Response(headers={"Content-Length": "257"}),
        Response(headers={"Content-Length": "-1"}),
        Response(headers={"Content-Length": "invalid"}),
    ],
)
def test_stream_and_header_limits_close_response(monkeypatch, response):
    session = Session(response)
    with pytest.raises(GcpReadError, match="INVALID_RESPONSE"):
        get(monkeypatch, session)
    assert response.closed and session.closed


@pytest.mark.parametrize("status", [301, 302, 401, 403, 429, 503])
def test_errors_are_not_streamed_or_redirected(monkeypatch, status):
    response = Response((b"private error body",), status)
    session = Session(response)
    result = get(monkeypatch, session)
    assert result.status == status and result.body == b"{}"
    assert not response.streamed and response.closed
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "url,method",
    [
        ("http://metadata.google.internal/computeMetadata/v1/", "GET"),
        ("https://attacker.invalid/token", "POST"),
        ("https://oauth2.googleapis.com/token?redirect=evil", "POST"),
        ("https://oauth2.googleapis.com/token", "GET"),
        (
            "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/test@example.com:signBlob",
            "POST",
        ),
    ],
)
def test_refresh_rejects_unapproved_destinations_before_http(url, method):
    session = Session()
    with pytest.raises(GcpReadError, match="AUTH"):
        _RefreshRequest(session, context())(url, method=method)
    assert not session.calls


def test_refresh_budget_and_body_limit():
    session = Session(*(Response() for _ in range(4)))
    session.trust_env = False
    refresh = _RefreshRequest(session, context())
    for _ in range(4):
        refresh("https://sts.googleapis.com/v1/token", method="POST")
    with pytest.raises(GcpReadError, match="AUTH"):
        refresh("https://sts.googleapis.com/v1/token", method="POST")
    assert len(session.calls) == 4
    with pytest.raises(GcpReadError, match="AUTH"):
        _RefreshRequest(session, context())(
            "https://sts.googleapis.com/v1/token", method="POST", body=b"x" * 16385
        )
    assert len(session.calls) == 4


def test_cancellation_during_stream_discards_result(monkeypatch):
    ctx = context()

    class CancellingResponse(Response):
        def iter_content(self, chunk_size):
            yield b"{"
            ctx.cancellation.set()
            yield b"}"

    response = CancellingResponse()
    session = Session(response)
    with pytest.raises(ProviderExecutionError, match="CANCELLED"):
        get(monkeypatch, session, ctx=ctx)
    assert response.closed and session.closed


@pytest.mark.parametrize(
    "exception,code",
    [
        (requests.exceptions.Timeout("private"), "TIMEOUT"),
        (requests.exceptions.SSLError("private"), "UNAVAILABLE"),
    ],
)
def test_network_exceptions_redacted(monkeypatch, exception, code):
    with pytest.raises(GcpReadError, match="^" + code + "$"):
        get(monkeypatch, Session(exception))


def test_closed_transport_and_invalid_budget_rejected():
    cfg = config()
    transport = GcpHttpsTransport(cfg)
    transport.close()
    with pytest.raises(GcpReadError, match="UNAVAILABLE"):
        transport.get(GcpRequests(cfg).project(), binding(), context(), 256)
    with pytest.raises(ProviderContractError):
        transport.get(GcpRequests(cfg).project(), binding(), context(), True)


def test_nonblocking_credentials_rejected_before_session(monkeypatch):
    credentials = Credentials("synthetic-access")
    credentials.with_non_blocking_refresh()
    monkeypatch.setattr(requests, "Session", lambda: pytest.fail("No session permitted"))
    cfg = config()
    with pytest.raises(GcpReadError, match="^AUTH$"):
        GcpHttpsTransport(cfg).get(GcpRequests(cfg).project(), binding(credentials), context(), 256)


def test_refresh_callback_is_revoked_after_authentication():
    session = Session()
    refresh = _RefreshRequest(session, context())
    refresh.close()
    with pytest.raises(GcpReadError, match="^AUTH$"):
        refresh("https://oauth2.googleapis.com/token", method="POST")
    assert session.calls == []

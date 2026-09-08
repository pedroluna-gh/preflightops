"""Explicit pinned-address HTTPS transport; no DNS, proxies or redirects."""

from __future__ import annotations

import http.client
import io
import ipaddress
import json
import math
import re
import socket
import ssl
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urlsplit

from .provider_contract import ProviderContractError
from .zabbix_client import READ_METHODS, ZabbixClientError, ZabbixResponse, _constant, _object


@dataclass(frozen=True, slots=True)
class ZabbixEndpoint:
    """Operator-approved destination. Internal names and addresses stay out of repr."""

    url: str = field(repr=False)
    pinned_ip: str = field(repr=False)
    allow_private: bool = False
    ca_file: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.allow_private) is not bool or not isinstance(self.url, str):
            raise ProviderContractError("Invalid Zabbix destination configuration.")
        try:
            parts = urlsplit(self.url)
            host = parts.hostname or ""
            if (
                len(self.url) > 2048
                or parts.scheme != "https"
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host)
                or any(
                    not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                    for label in host.split(".")
                )
                or parts.username is not None
                or parts.password is not None
                or parts.query
                or parts.fragment
                or "?" in self.url
                or "#" in self.url
                or not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*api_jsonrpc\.php", parts.path)
                or not 1 <= (443 if parts.port is None else parts.port) <= 65535
                or parts.netloc.endswith(":")
                or any(ord(c) < 33 or ord(c) > 126 for c in self.url)
                or "\\" in self.url
            ):
                raise ValueError
            address = ipaddress.ip_address(self.pinned_ip)
            if (
                str(address) != self.pinned_ip
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_unspecified
                or address.is_reserved
                or (not address.is_global and not (self.allow_private and address.is_private))
                or getattr(address, "ipv4_mapped", None) is not None
            ):
                raise ValueError
            if self.ca_file is not None and (not isinstance(self.ca_file, str) or not self.ca_file):
                raise ValueError
        except (ValueError, TypeError):
            raise ProviderContractError("Invalid or unapproved Zabbix destination.") from None


class _DeadlineReader(io.RawIOBase):
    """Refresh the remaining deadline for every socket read, including headers."""

    def __init__(self, stream: ssl.SSLSocket, deadline: float, limit: int):
        self.stream = stream
        self.deadline = deadline
        self.remaining_bytes = limit

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        if self.remaining_bytes <= 0:
            raise ZabbixClientError("INVALID_RESPONSE")
        self.stream.settimeout(remaining)
        count = self.stream.recv_into(buffer, min(len(buffer), self.remaining_bytes))
        self.remaining_bytes -= count
        return count


class _ResponseSocket:
    def __init__(self, reader: _DeadlineReader):
        self.reader = reader

    def makefile(self, mode: str) -> io.BufferedReader:
        if mode != "rb":
            raise ZabbixClientError("INVALID_RESPONSE")
        return io.BufferedReader(self.reader)


class PinnedZabbixTransport:
    """One TLS connection per read request, closed on every path."""

    def __init__(self, endpoint: ZabbixEndpoint):
        endpoint.__post_init__()
        self._endpoint = endpoint

    def post(
        self,
        *,
        endpoint: str,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
        max_response_bytes: int,
    ) -> ZabbixResponse:
        self._endpoint.__post_init__()
        if (
            endpoint != self._endpoint.url
            or type(body) is not bytes
            or len(body) > 65_536
            or type(timeout) not in (float, int)
            or not math.isfinite(timeout)
            or not 0 < timeout <= 120
            or type(max_response_bytes) is not int
            or not 256 <= max_response_bytes <= 4_194_304
            or not isinstance(headers, Mapping)
            or set(headers) not in ({"Content-Type"}, {"Content-Type", "Authorization"})
            or headers.get("Content-Type") != "application/json-rpc"
        ):
            raise ProviderContractError("Invalid bounded Zabbix HTTPS request.")
        authorization = headers.get("Authorization")
        if authorization is not None and (
            not isinstance(authorization, str)
            or not re.fullmatch(r"Bearer [A-Za-z0-9_-]{16,256}", authorization)
        ):
            raise ProviderContractError("Invalid Zabbix authorization header.")
        try:
            request = json.loads(body, object_pairs_hook=_object, parse_constant=_constant)
            if type(request) is not dict or request.get("method") not in READ_METHODS:
                raise ValueError
        except (ValueError, TypeError, RecursionError, ZabbixClientError):
            raise ProviderContractError("Only Zabbix read requests may connect.") from None
        parts = urlsplit(endpoint)
        hostname = cast(str, parts.hostname)
        deadline = time.monotonic() + timeout
        raw = None
        secure = None
        response = None
        try:
            context = ssl.create_default_context(cafile=self._endpoint.ca_file)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.set_alpn_protocols(["http/1.1"])
            address = ipaddress.ip_address(self._endpoint.pinned_ip)
            raw = socket.socket(
                socket.AF_INET6 if address.version == 6 else socket.AF_INET, socket.SOCK_STREAM
            )

            def remaining() -> float:
                value = deadline - time.monotonic()
                if value <= 0:
                    raise TimeoutError
                return value

            raw.settimeout(remaining())
            raw.connect((str(address), parts.port or 443))
            if ipaddress.ip_address(raw.getpeername()[0]) != address:
                raise ZabbixClientError("UNAVAILABLE")
            raw.settimeout(remaining())
            secure = context.wrap_socket(raw, server_hostname=hostname)
            secure.settimeout(remaining())
            wire_headers = {
                "Host": parts.netloc,
                "Connection": "close",
                "Accept-Encoding": "identity",
                "Content-Length": str(len(body)),
                **headers,
            }
            head = (
                "POST "
                + parts.path
                + " HTTP/1.1\r\n"
                + "".join(key + ": " + value + "\r\n" for key, value in wire_headers.items())
                + "\r\n"
            )
            secure.sendall(head.encode("ascii") + body)
            reader = _DeadlineReader(secure, deadline, max_response_bytes + 65_536)
            response = http.client.HTTPResponse(cast(Any, _ResponseSocket(reader)))
            response.begin()
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise ZabbixClientError("INVALID_RESPONSE")
            lengths = response.headers.get_all("Content-Length", [])
            if (
                len(lengths) > 1
                or (lengths and (not lengths[0].isdigit() or int(lengths[0]) > max_response_bytes))
                or (lengths and response.getheader("Transfer-Encoding") is not None)
            ):
                raise ZabbixClientError("INVALID_RESPONSE")
            payload = response.read(max_response_bytes + 1)
            remaining()
            if len(payload) > max_response_bytes or (lengths and len(payload) != int(lengths[0])):
                raise ZabbixClientError("INVALID_RESPONSE")
            return ZabbixResponse(response.status, payload)
        except ZabbixClientError:
            raise
        except TimeoutError:
            raise ZabbixClientError("TIMEOUT") from None
        except Exception:
            raise ZabbixClientError("UNAVAILABLE") from None
        finally:
            cleanup_failed = False
            for resource in (response, secure, raw):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        cleanup_failed = True
            if cleanup_failed:
                raise ZabbixClientError("UNAVAILABLE") from None

    def close(self) -> None:
        """No connection pool or retained authentication material."""

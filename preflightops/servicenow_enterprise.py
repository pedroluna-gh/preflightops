"""ServiceNow enterprise adapter v2.

Preview construction is deterministic and offline. Network, credentials, time and
sleep are explicit dependencies of execution. Production writes are only supported
through the scoped Evidence Gateway described by the public v2 contracts.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import ipaddress
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from .auditable_report import AuditableReportError, validate_auditable_report_v1
from .evidence import canonical_json
from .integration_errors import IntegrationError

MAPPING_SCHEMA_VERSION = "servicenow-mapping-v2"
REQUEST_SCHEMA_VERSION = "servicenow-adapter-request-v2"
PLAN_SCHEMA_VERSION = "servicenow-adapter-plan-v2"
RESULT_SCHEMA_VERSION = "servicenow-adapter-result-v2"
GATEWAY_PROFILE = "evidence_gateway_v1"
CHANGE_API_PROFILE = "change_management_v1"
DELIVERY_FIELD = "u_preflightops_delivery_id"

_CHANGE_API_PATH = "/api/sn_chg_rest/v1/change"
_GATEWAY_PATH = "/api/x_preflightops/v1/evidence"
_CAPABILITY_PATH = "/api/x_preflightops/v1/capabilities"
_TOKEN_PATH = "/oauth_token.do"
_MAX_MAPPING_BYTES = 256 * 1024
_MAX_RESPONSE_BYTES = 1024 * 1024
_MAX_REQUEST_BYTES = 10 * 1024 * 1024

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SYS_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CHANGE_NUMBER_RE = re.compile(r"^CHG[0-9]{7,12}$")
_ALIAS_RE = re.compile(r"^[a-z][a-z0-9._-]{2,63}$")
_AUTHORIZATION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_DESTINATION_RE = re.compile(r"^(?:short_description|description|risk|impact|u_[a-z0-9_]{1,77})$")
_DELIVERY_KEY_RE = re.compile(r"^snv2-[0-9a-f]{64}$")
_REQUEST_ID_RE = re.compile(r"^snreq-[0-9a-f]{32}$")
_ASSESSMENT_ID_RE = re.compile(r"^urn:preflightops:assessment:sha256:[0-9a-f]{64}$")
_REPORT_ID_RE = re.compile(r"^urn:preflightops:assessment-report:sha256:[0-9a-f]{64}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

_SEMANTIC_SOURCES = {
    "assessment_status": "decision.verdict",
    "risk": "scores.risk",
    "confidence": "scores.confidence",
    "assessment_id": "audit.assessment_id",
    "policy": "audit.policy",
    "blockers": "controls.top_blockers",
    "risk_impact": "decision.technical_recommendation.summary",
    "automation_details": "automation_details",
    "evidence_url": "delivery.evidence_url",
    "commit": "audit.commit",
    "timestamp": "audit.assessment_timestamp",
}
_FORBIDDEN_DESTINATION_PARTS = (
    "approval",
    "assigned",
    "assignment",
    "close_",
    "comments",
    "schedule",
    "start_date",
    "end_date",
    "transition",
    "work_notes",
)
_FORBIDDEN_DESTINATIONS = {"state", "close_code", "close_notes", "task"}
_REDIRECTS = {301, 302, 303, 307, 308}
_RETRYABLE_STATUSES = {502, 503, 504}
_KNOWN_REMOTE_CONFLICTS = {
    "CONCURRENCY_CONFLICT",
    "REPLAY_MISMATCH",
    "TARGET_AMBIGUOUS",
    "TARGET_NOT_FOUND",
    "MODEL_NOT_ALLOWED",
}


class ServiceNowV2Error(IntegrationError):
    """A bounded v2 adapter error that is safe to expose in results and logs."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        write_state: str = "NOT_ATTEMPTED",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = _safe_message(message)
        self.retryable = retryable
        self.write_state = write_state


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """Transport-neutral HTTP request."""

    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None = None
    timeout_seconds: float = 10.0


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Transport-neutral bounded HTTP response."""

    status: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    """Injected transport; preview code never receives or calls one."""

    def send(self, request: HttpRequest) -> HttpResponse: ...


class CredentialProvider(Protocol):
    """Injected short-lived credential provider."""

    def authorization_header(self, instance_origin: str) -> str: ...


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retry policy mirrored from the approved mapping."""

    attempts: int = 3
    elapsed_seconds: float = 90.0
    request_timeout_seconds: float = 10.0
    base_delay_seconds: float = 0.5

    def __post_init__(self) -> None:
        if type(self.attempts) is not int or not 1 <= self.attempts <= 5:
            raise ServiceNowV2Error("INVALID_MAPPING", "Retry attempts must be from 1 to 5.")
        if not 1 <= float(self.elapsed_seconds) <= 300:
            raise ServiceNowV2Error(
                "INVALID_MAPPING", "Retry elapsed budget must be from 1 to 300 seconds."
            )
        if not 0.1 <= float(self.request_timeout_seconds) <= 120:
            raise ServiceNowV2Error(
                "INVALID_MAPPING", "Request timeout must be from 0.1 to 120 seconds."
            )
        if not 0 <= float(self.base_delay_seconds) <= 30:
            raise ServiceNowV2Error(
                "INVALID_MAPPING", "Retry base delay must be from 0 to 30 seconds."
            )


def system_resolver(host: str) -> tuple[str, ...]:
    """Resolve a hostname for a live execution policy.

    This function is never called by preview. Tests and controlled deployments should
    inject a resolver that is appropriate for their network boundary.
    """

    addresses = {str(item[4][0]) for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    return tuple(sorted(addresses))


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    """Exact host and resolved-address policy for ServiceNow v2."""

    allowed_instance_hosts: tuple[str, ...]
    allowed_evidence_hosts: tuple[str, ...] = ()
    allowed_proxy_hosts: tuple[str, ...] = ()
    allowed_private_cidrs: tuple[str, ...] = ()
    resolver: Callable[[str], Sequence[str]] | None = None

    def __post_init__(self) -> None:
        for label, hosts in (
            ("instance", self.allowed_instance_hosts),
            ("evidence", self.allowed_evidence_hosts),
            ("proxy", self.allowed_proxy_hosts),
        ):
            if len(hosts) > 64:
                raise ServiceNowV2Error(
                    "UNTRUSTED_DESTINATION", f"Too many {label} hosts in network policy."
                )
            for host in hosts:
                _validate_policy_host(host, label)
        if len(self.allowed_private_cidrs) > 64:
            raise ServiceNowV2Error(
                "UNTRUSTED_DESTINATION", "Too many private networks in network policy."
            )
        for value in self.allowed_private_cidrs:
            try:
                network = ipaddress.ip_network(value, strict=True)
            except ValueError as exc:
                raise ServiceNowV2Error(
                    "UNTRUSTED_DESTINATION", "Private network allowlist contains invalid CIDR."
                ) from exc
            if (
                not network.is_private
                or network.is_loopback
                or network.is_link_local
                or network.is_multicast
                or network.is_reserved
                or network.is_unspecified
            ):
                raise ServiceNowV2Error(
                    "UNTRUSTED_DESTINATION",
                    "Only non-special private CIDRs may be explicitly allowlisted.",
                )

    def validate_instance_origin(self, value: str) -> str:
        return _validate_https_origin(value, self.allowed_instance_hosts, "instance")

    def validate_evidence_url(self, value: str) -> str:
        return _validate_https_resource(value, self.allowed_evidence_hosts, "evidence")

    def validate_proxy_origin(self, value: str) -> str:
        return _validate_https_origin(value, self.allowed_proxy_hosts, "proxy")

    def validate_request_url(self, value: str, instance_origin: str) -> str:
        parsed = urllib.parse.urlsplit(value)
        origin = self.validate_instance_origin(instance_origin)
        expected = urllib.parse.urlsplit(origin)
        if (
            parsed.scheme != "https"
            or parsed.hostname != expected.hostname
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ServiceNowV2Error(
                "UNTRUSTED_DESTINATION", "HTTP request URL is outside the approved instance origin."
            )
        return value

    def validate_resolution(self, host: str) -> tuple[str, ...]:
        if self.resolver is None:
            raise ServiceNowV2Error(
                "UNTRUSTED_DESTINATION",
                "Live execution requires an explicit DNS/IP validation resolver.",
            )
        try:
            raw_addresses = tuple(self.resolver(host))
        except Exception as exc:
            raise ServiceNowV2Error(
                "UNTRUSTED_DESTINATION", "Destination resolution failed closed."
            ) from exc
        if not raw_addresses:
            raise ServiceNowV2Error(
                "UNTRUSTED_DESTINATION", "Destination resolution returned no addresses."
            )
        allowed_networks = tuple(
            ipaddress.ip_network(value, strict=True) for value in self.allowed_private_cidrs
        )
        normalized: set[str] = set()
        for raw in raw_addresses:
            try:
                address = ipaddress.ip_address(raw)
            except ValueError as exc:
                raise ServiceNowV2Error(
                    "UNTRUSTED_DESTINATION", "Destination resolution returned an invalid address."
                ) from exc
            if (
                address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_unspecified
                or address.is_reserved
            ):
                raise ServiceNowV2Error(
                    "UNTRUSTED_DESTINATION", "Destination resolved to a forbidden address class."
                )
            if address.is_private and not any(address in network for network in allowed_networks):
                raise ServiceNowV2Error(
                    "UNTRUSTED_DESTINATION",
                    "Destination resolved to a private address not allowlisted.",
                )
            normalized.add(address.compressed)
        return tuple(sorted(normalized))


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class UrllibTransport:
    """TLS-validating urllib transport with redirects and ambient proxies disabled."""

    def __init__(
        self,
        *,
        network_policy: NetworkPolicy,
        proxy_origin: str | None = None,
        ssl_context: ssl.SSLContext | None = None,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
    ) -> None:
        if not 1024 <= max_response_bytes <= _MAX_REQUEST_BYTES:
            raise ValueError("max_response_bytes must be between 1 KiB and 10 MiB.")
        handlers: list[Any] = [_NoRedirectHandler()]
        if proxy_origin is None:
            handlers.append(urllib.request.ProxyHandler({}))
        else:
            proxy = network_policy.validate_proxy_origin(proxy_origin)
            handlers.append(urllib.request.ProxyHandler({"https": proxy}))
        handlers.append(
            urllib.request.HTTPSHandler(context=ssl_context or ssl.create_default_context())
        )
        self._network_policy = network_policy
        self._proxy_host = (
            urllib.parse.urlsplit(proxy_origin).hostname if proxy_origin is not None else None
        )
        self._opener = urllib.request.build_opener(*handlers)
        self._max_response_bytes = max_response_bytes

    def send(self, request: HttpRequest) -> HttpResponse:
        parsed = urllib.parse.urlsplit(request.url)
        request_origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        origin = self._network_policy.validate_instance_origin(request_origin)
        self._network_policy.validate_request_url(request.url, origin)
        host = parsed.hostname
        assert host is not None
        self._network_policy.validate_resolution(host)
        if self._proxy_host is not None:
            self._network_policy.validate_resolution(self._proxy_host)
        outbound = urllib.request.Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method=request.method,
        )
        try:
            with self._opener.open(outbound, timeout=request.timeout_seconds) as response:
                body = response.read(self._max_response_bytes + 1)
                if len(body) > self._max_response_bytes:
                    raise ServiceNowV2Error(
                        "RESPONSE_INVALID", "ServiceNow response exceeded the configured limit."
                    )
                return HttpResponse(response.status, dict(response.headers.items()), body)
        except urllib.error.HTTPError as exc:
            body = exc.read(self._max_response_bytes + 1)
            if len(body) > self._max_response_bytes:
                body = b""
            return HttpResponse(exc.code, dict(exc.headers.items()), body)
        except TimeoutError as exc:
            raise TimeoutError("ServiceNow request timed out.") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError("ServiceNow request timed out.") from exc
            raise OSError("ServiceNow transport failed.") from exc


class OAuthClientCredentialsProvider:
    """Acquire a short-lived OAuth token through an injected hardened transport."""

    __slots__ = (
        "_client_id",
        "_client_secret",
        "_network_policy",
        "_scope",
        "_timeout_seconds",
        "_transport",
    )

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        transport: HttpTransport,
        network_policy: NetworkPolicy,
        scope: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not client_id or _CONTROL_RE.search(client_id):
            raise ValueError("OAuth client_id is required and must not contain controls.")
        if not client_secret or _CONTROL_RE.search(client_secret):
            raise ValueError("OAuth client_secret is required and must not contain controls.")
        if not scope or _CONTROL_RE.search(scope) or len(scope) > 256:
            raise ValueError("OAuth scope is required and must be bounded.")
        if not 0.1 <= float(timeout_seconds) <= 120:
            raise ValueError("OAuth timeout must be from 0.1 to 120 seconds.")
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport = transport
        self._network_policy = network_policy
        self._scope = scope
        self._timeout_seconds = timeout_seconds

    def authorization_header(self, instance_origin: str) -> str:
        origin = self._network_policy.validate_instance_origin(instance_origin)
        host = urllib.parse.urlsplit(origin).hostname
        assert host is not None
        self._network_policy.validate_resolution(host)
        token_url = f"{origin}{_TOKEN_PATH}"
        self._network_policy.validate_request_url(token_url, origin)
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": self._scope,
            }
        ).encode("ascii")
        response = self._transport.send(
            HttpRequest(
                "POST",
                token_url,
                {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
                body,
                self._timeout_seconds,
            )
        )
        if response.status in _REDIRECTS:
            raise ServiceNowV2Error("REDIRECT_REJECTED", "OAuth endpoint redirect was rejected.")
        if response.status in {400, 401, 403}:
            raise ServiceNowV2Error(
                "AUTHENTICATION_FAILED", "OAuth client credentials were rejected."
            )
        if not 200 <= response.status < 300:
            raise ServiceNowV2Error(
                "AUTHENTICATION_FAILED", "OAuth token acquisition failed closed."
            )
        payload = _json_object(response.body, "OAuth token")
        token = payload.get("access_token")
        token_type = payload.get("token_type", "Bearer")
        if (
            not isinstance(token, str)
            or not 8 <= len(token) <= 8192
            or any(character.isspace() or ord(character) < 32 for character in token)
            or str(token_type).lower() != "bearer"
        ):
            raise ServiceNowV2Error("AUTHENTICATION_FAILED", "OAuth token response was invalid.")
        return f"Bearer {token}"


@dataclass(frozen=True, slots=True)
class ServiceNowPlanV2:
    """Immutable-by-contract, serializable ServiceNow v2 execution plan."""

    request: Mapping[str, Any]
    mapping: Mapping[str, Any]
    mapped_fields: Mapping[str, str]
    evidence: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PLAN_SCHEMA_VERSION,
            "request": copy.deepcopy(dict(self.request)),
            "mapping": copy.deepcopy(dict(self.mapping)),
            "mapped_fields": copy.deepcopy(dict(self.mapped_fields)),
            "evidence": copy.deepcopy(dict(self.evidence)),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.to_dict())


def load_servicenow_mapping_v2(
    mapping: str | Path | Mapping[str, Any],
) -> dict[str, Any]:
    """Load a strict local v2 mapping and reject YAML indirection."""

    if isinstance(mapping, Mapping):
        loaded: Any = copy.deepcopy(dict(mapping))
    elif isinstance(mapping, (str, Path)):
        path = Path(mapping)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ServiceNowV2Error(
                "INVALID_MAPPING", "Unable to read ServiceNow v2 mapping."
            ) from exc
        if len(raw) > _MAX_MAPPING_BYTES:
            raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow v2 mapping is too large.")
        try:
            text = raw.decode("utf-8")
            for event in yaml.parse(text):
                if isinstance(event, yaml.events.AliasEvent) or getattr(event, "anchor", None):
                    raise ServiceNowV2Error(
                        "INVALID_MAPPING", "YAML aliases and anchors are forbidden in mappings."
                    )
            loaded = yaml.safe_load(text)
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow v2 mapping is invalid.") from exc
    else:
        raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow v2 mapping must be local data.")
    if not isinstance(loaded, dict):
        raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow v2 mapping must be an object.")
    _validate_mapping_v2(loaded)
    return loaded


def build_servicenow_plan_v2(
    report: Mapping[str, Any],
    mapping: str | Path | Mapping[str, Any],
    *,
    instance_alias: str,
    instance_origin: str,
    network_policy: NetworkPolicy,
    operation: str = "enrich_existing",
    target_number: str | None = None,
    target_sys_id: str | None = None,
    expected_sys_mod_count: int | None = None,
    capability_attestation_sha256: str,
    dry_run: bool = True,
    write_enabled: bool = False,
    transport_profile: str = GATEWAY_PROFILE,
    evidence_mode: str = "attachment",
    evidence_url: str | None = None,
    model_sys_id: str | None = None,
    external_authorization_id: str | None = None,
    draft_feature_enabled: bool = False,
) -> ServiceNowPlanV2:
    """Build a deterministic, credential-free adapter plan."""

    try:
        validate_auditable_report_v1(report)
    except (AuditableReportError, KeyError, TypeError, ValueError) as exc:
        raise ServiceNowV2Error(
            "INVALID_MAPPING", "Assessment Report v1 is invalid for ServiceNow delivery."
        ) from exc
    configured = load_servicenow_mapping_v2(mapping)
    origin = network_policy.validate_instance_origin(instance_origin)
    if not _ALIAS_RE.fullmatch(instance_alias):
        raise ServiceNowV2Error("UNTRUSTED_DESTINATION", "Instance alias is invalid.")
    if not _SHA256_RE.fullmatch(capability_attestation_sha256):
        raise ServiceNowV2Error("CAPABILITY_MISSING", "Capability attestation digest is invalid.")
    if type(dry_run) is not bool or type(write_enabled) is not bool:
        raise ServiceNowV2Error("AUTHORIZATION_DENIED", "Write mode flags must be booleans.")
    if write_enabled and (dry_run or transport_profile != GATEWAY_PROFILE):
        raise ServiceNowV2Error(
            "AUTHORIZATION_DENIED", "Live writes require dry_run=false and Evidence Gateway."
        )
    if transport_profile not in {GATEWAY_PROFILE, CHANGE_API_PROFILE}:
        raise ServiceNowV2Error("CAPABILITY_MISSING", "Transport profile is unsupported.")

    target: dict[str, str] | None = None
    creation: dict[str, str] | None = None
    if operation == "enrich_existing":
        if not configured["operations"]["enrich_existing"]:
            raise ServiceNowV2Error("AUTHORIZATION_DENIED", "Enrichment is disabled by mapping.")
        if (target_number is None) == (target_sys_id is None):
            raise ServiceNowV2Error(
                "TARGET_AMBIGUOUS", "Enrichment requires exactly one target identifier."
            )
        if target_number is not None:
            if not _CHANGE_NUMBER_RE.fullmatch(target_number):
                raise ServiceNowV2Error("TARGET_NOT_FOUND", "Change number format is invalid.")
            target = {"number": target_number}
        else:
            assert target_sys_id is not None
            if not _SYS_ID_RE.fullmatch(target_sys_id):
                raise ServiceNowV2Error("TARGET_NOT_FOUND", "Change sys_id format is invalid.")
            target = {"sys_id": target_sys_id}
        if type(expected_sys_mod_count) is not int or expected_sys_mod_count < 0:
            raise ServiceNowV2Error(
                "CONCURRENCY_CONFLICT", "Expected sys_mod_count is required for enrichment."
            )
    elif operation == "create_draft":
        if not draft_feature_enabled or not configured["operations"]["create_draft"]:
            raise ServiceNowV2Error(
                "MODEL_NOT_ALLOWED", "Draft creation is disabled by default policy."
            )
        if model_sys_id not in configured["creation"]["allowed_model_sys_ids"]:
            raise ServiceNowV2Error("MODEL_NOT_ALLOWED", "Draft change model is not allowlisted.")
        if not external_authorization_id or not _AUTHORIZATION_ID_RE.fullmatch(
            external_authorization_id
        ):
            raise ServiceNowV2Error(
                "AUTHORIZATION_DENIED", "Draft creation requires external authorization."
            )
        creation = {
            "model_sys_id": str(model_sys_id),
            "external_authorization_id": external_authorization_id,
        }
    else:
        raise ServiceNowV2Error("AUTHORIZATION_DENIED", "ServiceNow operation is unsupported.")

    if evidence_mode not in {"attachment", "https_link"}:
        raise ServiceNowV2Error("INVALID_MAPPING", "Evidence mode is unsupported.")
    configured_mode = configured["evidence"]["mode"]
    if configured_mode != "attachment_or_link" and evidence_mode != configured_mode:
        raise ServiceNowV2Error("INVALID_MAPPING", "Evidence mode is disabled by mapping.")
    safe_evidence_url: str | None = None
    if evidence_mode == "https_link":
        if not evidence_url:
            raise ServiceNowV2Error(
                "UNTRUSTED_DESTINATION", "HTTPS evidence mode requires an evidence URL."
            )
        safe_evidence_url = network_policy.validate_evidence_url(evidence_url)
        if urllib.parse.urlsplit(safe_evidence_url).hostname not in set(
            configured["evidence"]["allowed_link_hosts"]
        ):
            raise ServiceNowV2Error(
                "UNTRUSTED_DESTINATION", "Evidence URL host is not allowed by the mapping."
            )
    elif evidence_url is not None:
        raise ServiceNowV2Error(
            "UNTRUSTED_DESTINATION", "Attachment mode must not include an evidence URL."
        )

    report_document = copy.deepcopy(dict(report))
    report_bytes = canonical_json(report_document)
    if len(report_bytes) > configured["evidence"]["attachment_max_bytes"]:
        raise ServiceNowV2Error("INVALID_MAPPING", "Assessment report exceeds evidence limit.")
    report_sha256 = str(report_document["integrity"]["value"])
    report_id = str(report_document["report_id"])
    if report_id.rsplit(":", 1)[-1] != report_sha256:
        raise ServiceNowV2Error("RESPONSE_INVALID", "Assessment report digest is inconsistent.")

    sources = copy.deepcopy(report_document)
    sources["delivery"] = {"evidence_url": safe_evidence_url}
    mapped_fields = _map_report(configured, sources)
    mapping_sha256 = hashlib.sha256(canonical_json(configured)).hexdigest()
    payload_sha256 = hashlib.sha256(canonical_json(mapped_fields)).hexdigest()
    audit = report_document["audit"]
    assessment_id = str(audit["assessment_id"])
    target_or_model = target if target is not None else creation
    identity = [
        REQUEST_SCHEMA_VERSION,
        operation,
        instance_alias,
        target_or_model,
        assessment_id,
        report_sha256,
        mapping_sha256,
        payload_sha256,
    ]
    idempotency_key = "snv2-" + hashlib.sha256(canonical_json(identity)).hexdigest()
    request_basis = [idempotency_key, dry_run, expected_sys_mod_count]
    request_id = "snreq-" + hashlib.sha256(canonical_json(request_basis)).hexdigest()[:32]
    risk = report_document["scores"]["risk"]
    confidence = report_document["scores"]["confidence"]
    policy = audit["policy"]
    commit = str(audit["commit"])
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ServiceNowV2Error("INVALID_MAPPING", "Assessment commit must be a full SHA-1.")
    request: dict[str, Any] = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "request_id": request_id,
        "operation": operation,
        "dry_run": dry_run,
        "write_enabled": write_enabled,
        "transport_profile": transport_profile,
        "instance": {"alias": instance_alias, "origin": origin},
        "assessment": {
            "assessment_id": assessment_id,
            "report_id": report_id,
            "report_sha256": report_sha256,
            "verdict": report_document["decision"]["verdict"],
            "risk_level": risk["level"],
            "confidence_level": confidence["level"],
            "policy_name": policy["name"],
            "policy_version": policy["version"],
            "commit": commit,
            "assessed_at": audit["assessment_timestamp"],
        },
        "delivery": {
            "mapping_profile_id": configured["profile_id"],
            "mapping_sha256": mapping_sha256,
            "idempotency_key": idempotency_key,
            "payload_sha256": payload_sha256,
            "evidence_mode": evidence_mode,
        },
        "preconditions": {
            "capability_attestation_sha256": capability_attestation_sha256,
        },
    }
    if target is not None:
        request["target"] = target
        request["preconditions"]["expected_sys_mod_count"] = expected_sys_mod_count
    if creation is not None:
        request["creation"] = creation
    if safe_evidence_url is not None:
        request["delivery"]["evidence_url"] = safe_evidence_url
    evidence: dict[str, Any] = {
        "mode": evidence_mode,
        "sha256": report_sha256,
        "media_type": "application/vnd.preflightops.assessment-report.v1+json",
    }
    if evidence_mode == "attachment":
        evidence["document"] = report_document
    else:
        evidence["url"] = safe_evidence_url
    plan = ServiceNowPlanV2(request, configured, mapped_fields, evidence)
    validate_servicenow_plan_v2(plan)
    return plan


def validate_servicenow_plan_v2(plan: ServiceNowPlanV2) -> None:
    """Recompute every local invariant before execution."""

    document = plan.to_dict()
    _exact_keys(
        document, {"schema_version", "request", "mapping", "mapped_fields", "evidence"}, "plan"
    )
    if document["schema_version"] != PLAN_SCHEMA_VERSION:
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow plan version is unsupported.")
    mapping = document["mapping"]
    _validate_mapping_v2(mapping)
    request = document["request"]
    _validate_request_v2(request)
    mapped_fields = document["mapped_fields"]
    if not isinstance(mapped_fields, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in mapped_fields.items()
    ):
        raise ServiceNowV2Error("INVALID_MAPPING", "Mapped fields are invalid.")
    allowed_destinations = {rule["destination"] for rule in mapping["fields"].values()}
    if not set(mapped_fields).issubset(allowed_destinations):
        raise ServiceNowV2Error("INVALID_MAPPING", "Plan contains a field outside the mapping.")
    mapping_sha256 = hashlib.sha256(canonical_json(mapping)).hexdigest()
    payload_sha256 = hashlib.sha256(canonical_json(mapped_fields)).hexdigest()
    delivery = request["delivery"]
    if delivery["mapping_sha256"] != mapping_sha256 or delivery["payload_sha256"] != payload_sha256:
        raise ServiceNowV2Error("REPLAY_MISMATCH", "Plan digest verification failed.")
    if delivery["mapping_profile_id"] != mapping["profile_id"]:
        raise ServiceNowV2Error("REPLAY_MISMATCH", "Plan mapping profile verification failed.")
    destination_limits = {
        rule["destination"]: rule["max_length"] for rule in mapping["fields"].values()
    }
    if any(
        len(value) > destination_limits.get(destination, -1)
        for destination, value in mapped_fields.items()
    ):
        raise ServiceNowV2Error("REPLAY_MISMATCH", "Plan field limit verification failed.")
    target_or_model = request.get("target") or request.get("creation")
    assessment = request["assessment"]
    identity = [
        REQUEST_SCHEMA_VERSION,
        request["operation"],
        request["instance"]["alias"],
        target_or_model,
        assessment["assessment_id"],
        assessment["report_sha256"],
        mapping_sha256,
        payload_sha256,
    ]
    expected_key = "snv2-" + hashlib.sha256(canonical_json(identity)).hexdigest()
    if delivery["idempotency_key"] != expected_key:
        raise ServiceNowV2Error("REPLAY_MISMATCH", "Plan delivery identity verification failed.")
    request_basis = [
        expected_key,
        request["dry_run"],
        request["preconditions"].get("expected_sys_mod_count"),
    ]
    expected_request = "snreq-" + hashlib.sha256(canonical_json(request_basis)).hexdigest()[:32]
    if request["request_id"] != expected_request:
        raise ServiceNowV2Error("REPLAY_MISMATCH", "Plan request identity verification failed.")
    evidence = document["evidence"]
    if not isinstance(evidence, dict):
        raise ServiceNowV2Error("RESPONSE_INVALID", "Plan evidence is invalid.")
    if evidence.get("sha256") != assessment["report_sha256"]:
        raise ServiceNowV2Error("REPLAY_MISMATCH", "Plan evidence digest verification failed.")
    if evidence.get("mode") == "attachment":
        report = evidence.get("document")
        if not isinstance(report, dict):
            raise ServiceNowV2Error("RESPONSE_INVALID", "Attachment evidence document is missing.")
        try:
            validate_auditable_report_v1(report)
        except (AuditableReportError, KeyError, TypeError, ValueError) as exc:
            raise ServiceNowV2Error("RESPONSE_INVALID", "Attachment report is invalid.") from exc
        if (
            report["integrity"]["value"] != evidence["sha256"]
            or report["report_id"].rsplit(":", 1)[-1] != evidence["sha256"]
        ):
            raise ServiceNowV2Error("REPLAY_MISMATCH", "Attachment report digest is inconsistent.")
    elif evidence.get("mode") == "https_link":
        if evidence.get("url") != delivery.get("evidence_url"):
            raise ServiceNowV2Error("REPLAY_MISMATCH", "Evidence link is inconsistent.")
    else:
        raise ServiceNowV2Error("RESPONSE_INVALID", "Plan evidence mode is invalid.")


class ServiceNowEnterpriseAdapter:
    """Execute a validated v2 plan through explicit, replaceable dependencies."""

    def __init__(
        self,
        *,
        network_policy: NetworkPolicy,
        transport: HttpTransport | None = None,
        credential_provider: CredentialProvider | None = None,
        retry_policy: RetryPolicy | None = None,
        draft_feature_enabled: bool = False,
        clock: Callable[[], dt.datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        event_sink: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self._network_policy = network_policy
        self._transport = transport
        self._credential_provider = credential_provider
        self._retry_policy = retry_policy or RetryPolicy()
        self._draft_feature_enabled = draft_feature_enabled
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep
        self._event_sink = event_sink

    def execute(self, plan: ServiceNowPlanV2, *, confirm_write: bool = False) -> dict[str, Any]:
        started = self._monotonic()
        try:
            validate_servicenow_plan_v2(plan)
            request = plan.request
            self._network_policy.validate_instance_origin(str(request["instance"]["origin"]))
            evidence_url = request["delivery"].get("evidence_url")
            if evidence_url is not None:
                self._network_policy.validate_evidence_url(str(evidence_url))
            mapping_limits = plan.mapping["limits"]
            if (
                self._retry_policy.attempts > mapping_limits["attempts"]
                or self._retry_policy.elapsed_seconds > mapping_limits["elapsed_seconds"]
            ):
                raise ServiceNowV2Error(
                    "INVALID_MAPPING", "Runtime retry policy exceeds the approved mapping budget."
                )
            if request["dry_run"]:
                result = self._result(plan, "DRY_RUN", False, 0)
                return self._finish(result, started)
            if request["operation"] == "create_draft" and not self._draft_feature_enabled:
                result = self._failure(
                    plan,
                    ServiceNowV2Error("MODEL_NOT_ALLOWED", "Draft creation feature is disabled."),
                    0,
                )
                return self._finish(result, started)
            if not request["write_enabled"]:
                if self._transport is None or self._credential_provider is None:
                    result = self._result(plan, "READ_ONLY", False, 0)
                elif request["operation"] == "enrich_existing":
                    authorization = self._authorization(plan)
                    target, attempts = self._lookup_target(plan, authorization)
                    result = self._result(plan, "READ_ONLY", True, attempts, target=target)
                else:
                    result = self._result(plan, "READ_ONLY", False, 0)
                return self._finish(result, started)
            if not confirm_write:
                result = self._failure(
                    plan,
                    ServiceNowV2Error(
                        "AUTHORIZATION_DENIED", "Explicit live-write confirmation was not supplied."
                    ),
                    0,
                )
                return self._finish(result, started)
            if request["transport_profile"] != GATEWAY_PROFILE:
                result = self._failure(
                    plan,
                    ServiceNowV2Error(
                        "CAPABILITY_MISSING", "Live writes require the Evidence Gateway profile."
                    ),
                    0,
                )
                return self._finish(result, started)
            if self._transport is None or self._credential_provider is None:
                result = self._failure(
                    plan,
                    ServiceNowV2Error(
                        "AUTHENTICATION_FAILED", "Live execution dependencies are unavailable."
                    ),
                    0,
                )
                return self._finish(result, started)

            authorization = self._authorization(plan)
            pinned_target: dict[str, Any] | None = None
            read_attempts = 0
            if request["operation"] == "enrich_existing":
                pinned_target, read_attempts = self._lookup_target(plan, authorization)
                expected = request["preconditions"]["expected_sys_mod_count"]
                if pinned_target["sys_mod_count"] != expected:
                    result = self._failure(
                        plan,
                        ServiceNowV2Error(
                            "CONCURRENCY_CONFLICT",
                            "Change changed after preview; no write was attempted.",
                            write_state="NOT_APPLIED",
                        ),
                        read_attempts,
                        outcome="CONFLICT",
                    )
                    return self._finish(result, started)
            self._validate_capability(plan, authorization)
            result = self._write_gateway(plan, authorization, pinned_target, started)
            return self._finish(result, started)
        except ServiceNowV2Error as exc:
            outcome = (
                "PARTIAL_FAILURE_UNKNOWN"
                if exc.write_state in {"APPLIED", "UNKNOWN"}
                else "CONFLICT"
                if exc.code in {"CONCURRENCY_CONFLICT", "REPLAY_MISMATCH"}
                else "FAILED"
            )
            result = self._failure(plan, exc, 0, outcome=outcome)
            return self._finish(result, started)
        except Exception:
            result = self._failure(
                plan,
                ServiceNowV2Error(
                    "PARTIAL_FAILURE_UNKNOWN",
                    "ServiceNow execution failed closed with an unclassified local error.",
                    write_state="UNKNOWN",
                ),
                0,
                outcome="PARTIAL_FAILURE_UNKNOWN",
            )
            return self._finish(result, started)

    def _authorization(self, plan: ServiceNowPlanV2) -> str:
        assert self._credential_provider is not None
        origin = str(plan.request["instance"]["origin"])
        host = urllib.parse.urlsplit(origin).hostname
        assert host is not None
        self._network_policy.validate_resolution(host)
        try:
            header = self._credential_provider.authorization_header(origin)
        except ServiceNowV2Error:
            raise
        except Exception as exc:
            raise ServiceNowV2Error(
                "AUTHENTICATION_FAILED", "Credential provider failed closed."
            ) from exc
        token = header[7:] if isinstance(header, str) and header.startswith("Bearer ") else ""
        if (
            not token
            or len(header) > 8200
            or any(
                character.isspace() or ord(character) < 33 or ord(character) == 127
                for character in token
            )
        ):
            raise ServiceNowV2Error(
                "AUTHENTICATION_FAILED", "Credential provider returned invalid authorization."
            )
        return header

    def _lookup_target(
        self, plan: ServiceNowPlanV2, authorization: str
    ) -> tuple[dict[str, Any], int]:
        request = plan.request
        origin = str(request["instance"]["origin"])
        target = request["target"]
        if "sys_id" in target:
            path = f"{_CHANGE_API_PATH}/{target['sys_id']}"
        else:
            path = f"{_CHANGE_API_PATH}?{urllib.parse.urlencode({'number': target['number']})}"
        response, attempts = self._send_read(origin, path, authorization, request["request_id"])
        if response.status == 404:
            raise ServiceNowV2Error(
                "TARGET_NOT_FOUND", "ServiceNow Change was not found.", write_state="NOT_APPLIED"
            )
        self._raise_http_error(response, read_only=True)
        payload = _json_object(response.body, "Change lookup")
        raw_result = payload.get("result")
        if isinstance(raw_result, list):
            records = raw_result
        elif isinstance(raw_result, dict):
            records = [raw_result]
        else:
            raise ServiceNowV2Error("RESPONSE_INVALID", "Change lookup response is invalid.")
        if not records:
            raise ServiceNowV2Error(
                "TARGET_NOT_FOUND", "ServiceNow Change was not found.", write_state="NOT_APPLIED"
            )
        if len(records) != 1 or not isinstance(records[0], dict):
            raise ServiceNowV2Error(
                "TARGET_AMBIGUOUS",
                "Change lookup did not resolve exactly one record.",
                write_state="NOT_APPLIED",
            )
        pinned = _target_from_remote(records[0])
        if ("number" in target and pinned["number"] != target["number"]) or (
            "sys_id" in target and pinned["sys_id"] != target["sys_id"]
        ):
            raise ServiceNowV2Error(
                "TARGET_AMBIGUOUS",
                "Change lookup identity did not match the requested target.",
                write_state="NOT_APPLIED",
            )
        return pinned, attempts

    def _validate_capability(self, plan: ServiceNowPlanV2, authorization: str) -> None:
        request = plan.request
        origin = str(request["instance"]["origin"])
        digest = request["preconditions"]["capability_attestation_sha256"]
        response, _ = self._send_read(
            origin, f"{_CAPABILITY_PATH}/{digest}", authorization, request["request_id"]
        )
        self._raise_http_error(response, read_only=True)
        payload = _json_object(response.body, "Gateway capability")
        capability = payload.get("result")
        required = {
            "attestation_sha256",
            "mapping_sha256",
            "server_compare_and_set",
            "unique_delivery",
            "delivery_field",
            "allowed_operations",
            "allowed_model_sys_ids",
        }
        if not isinstance(capability, dict) or set(capability) != required:
            raise ServiceNowV2Error("CAPABILITY_MISSING", "Gateway capability is invalid.")
        operations = capability["allowed_operations"]
        models = capability["allowed_model_sys_ids"]
        if (
            not isinstance(capability["attestation_sha256"], str)
            or not _SHA256_RE.fullmatch(capability["attestation_sha256"])
            or not isinstance(capability["mapping_sha256"], str)
            or not _SHA256_RE.fullmatch(capability["mapping_sha256"])
            or not isinstance(operations, list)
            or not 1 <= len(operations) <= 2
            or not all(isinstance(operation, str) for operation in operations)
            or len(operations) != len(set(operations))
            or not set(operations).issubset({"enrich_existing", "create_draft"})
            or not isinstance(models, list)
            or len(models) > 32
            or not all(isinstance(model, str) and _SYS_ID_RE.fullmatch(model) for model in models)
            or len(models) != len(set(models))
        ):
            raise ServiceNowV2Error("CAPABILITY_MISSING", "Gateway capability is invalid.")
        if (
            capability["attestation_sha256"] != digest
            or capability["mapping_sha256"] != request["delivery"]["mapping_sha256"]
            or capability["server_compare_and_set"] is not True
            or capability["unique_delivery"] is not True
            or capability["delivery_field"] != DELIVERY_FIELD
            or request["operation"] not in capability["allowed_operations"]
        ):
            raise ServiceNowV2Error("CAPABILITY_MISSING", "Gateway capability does not match plan.")
        if request["operation"] == "create_draft":
            model = request["creation"]["model_sys_id"]
            if model not in capability["allowed_model_sys_ids"]:
                raise ServiceNowV2Error("MODEL_NOT_ALLOWED", "Gateway does not allow draft model.")

    def _write_gateway(
        self,
        plan: ServiceNowPlanV2,
        authorization: str,
        pinned_target: Mapping[str, Any] | None,
        started: float,
    ) -> dict[str, Any]:
        assert self._transport is not None
        request = plan.request
        origin = str(request["instance"]["origin"])
        delivery = request["delivery"]
        headers = {
            "Accept": "application/json",
            "Authorization": authorization,
            "Content-Type": "application/json",
            "Idempotency-Key": delivery["idempotency_key"],
            "X-PreflightOps-Request-Id": request["request_id"],
        }
        body_document = {
            "request": copy.deepcopy(dict(request)),
            "mapped_fields": copy.deepcopy(dict(plan.mapped_fields)),
            "evidence": copy.deepcopy(dict(plan.evidence)),
        }
        body = canonical_json(body_document)
        if len(body) > _MAX_REQUEST_BYTES:
            return self._failure(
                plan,
                ServiceNowV2Error("INVALID_MAPPING", "Gateway request exceeds 10 MiB limit."),
                0,
            )
        attempt = 0
        while attempt < self._retry_policy.attempts:
            attempt += 1
            try:
                response = self._send(
                    origin,
                    _GATEWAY_PATH,
                    "POST",
                    headers,
                    body,
                )
            except TimeoutError:
                reconciled = self._reconcile(plan, authorization, pinned_target)
                if reconciled is not None:
                    if reconciled is False:
                        if attempt < self._retry_policy.attempts and self._sleep_retry(
                            plan, attempt, started
                        ):
                            continue
                    elif isinstance(reconciled, dict):
                        return self._result_from_remote(plan, reconciled, attempt, pinned_target)
                return self._failure(
                    plan,
                    ServiceNowV2Error(
                        "PARTIAL_FAILURE_UNKNOWN",
                        "Write timed out and reconciliation could not prove final state.",
                        write_state="UNKNOWN",
                    ),
                    attempt,
                    outcome="PARTIAL_FAILURE_UNKNOWN",
                )
            if response.status in _REDIRECTS:
                return self._failure(
                    plan,
                    ServiceNowV2Error(
                        "REDIRECT_REJECTED",
                        "Gateway redirect was rejected.",
                        write_state="UNKNOWN",
                    ),
                    attempt,
                    outcome="PARTIAL_FAILURE_UNKNOWN",
                )
            if response.status == 429:
                delay = _retry_after(response.headers)
                if attempt < self._retry_policy.attempts and self._sleep_retry(
                    plan, attempt, started, explicit_delay=delay
                ):
                    continue
                return self._failure(
                    plan,
                    ServiceNowV2Error(
                        "RATE_LIMITED",
                        "Gateway rate limit exhausted the retry budget.",
                        retryable=True,
                        write_state="NOT_APPLIED",
                    ),
                    attempt,
                    retry_after=delay,
                )
            if response.status in _RETRYABLE_STATUSES:
                reconciled = self._reconcile(plan, authorization, pinned_target)
                if isinstance(reconciled, dict):
                    return self._result_from_remote(plan, reconciled, attempt, pinned_target)
                if (
                    reconciled is False
                    and attempt < self._retry_policy.attempts
                    and self._sleep_retry(plan, attempt, started)
                ):
                    continue
                return self._failure(
                    plan,
                    ServiceNowV2Error(
                        "PARTIAL_FAILURE_UNKNOWN",
                        "Gateway failure could not be reconciled safely.",
                        write_state="UNKNOWN",
                    ),
                    attempt,
                    outcome="PARTIAL_FAILURE_UNKNOWN",
                )
            if response.status == 409:
                return self._conflict_response(plan, response, attempt)
            try:
                self._raise_http_error(response, read_only=False)
                _json_object(response.body, "Gateway write")
            except ServiceNowV2Error as exc:
                return self._failure(plan, exc, attempt)
            reconciled = self._reconcile(plan, authorization, pinned_target)
            if isinstance(reconciled, dict):
                return self._result_from_remote(plan, reconciled, attempt, pinned_target)
            return self._failure(
                plan,
                ServiceNowV2Error(
                    "PARTIAL_FAILURE_UNKNOWN",
                    "Gateway write was not verifiable by read-back.",
                    write_state="UNKNOWN",
                ),
                attempt,
                outcome="PARTIAL_FAILURE_UNKNOWN",
            )
        raise AssertionError("bounded write loop exhausted unexpectedly")

    def _reconcile(
        self,
        plan: ServiceNowPlanV2,
        authorization: str,
        pinned_target: Mapping[str, Any] | None,
    ) -> dict[str, Any] | bool | None:
        request = plan.request
        origin = str(request["instance"]["origin"])
        key = request["delivery"]["idempotency_key"]
        try:
            response, _ = self._send_read(
                origin,
                f"{_GATEWAY_PATH}/{key}",
                authorization,
                request["request_id"],
            )
        except ServiceNowV2Error:
            return None
        if response.status == 404:
            return False
        if not 200 <= response.status < 300:
            return None
        try:
            payload = _json_object(response.body, "Gateway reconciliation")
            remote = payload.get("result")
            if not isinstance(remote, dict):
                return None
            self._validate_remote_delivery(plan, remote, pinned_target)
            return remote
        except ServiceNowV2Error:
            return None

    def _result_from_remote(
        self,
        plan: ServiceNowPlanV2,
        remote: Mapping[str, Any],
        attempts: int,
        pinned_target: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        self._validate_remote_delivery(plan, remote, pinned_target)
        return self._result(
            plan,
            str(remote["outcome"]),
            True,
            attempts,
            target=_target_from_remote(remote["target"]),
        )

    def _validate_remote_delivery(
        self,
        plan: ServiceNowPlanV2,
        remote: Mapping[str, Any],
        pinned_target: Mapping[str, Any] | None,
    ) -> None:
        required = {
            "outcome",
            "target",
            "idempotency_key",
            "payload_sha256",
            "mapping_sha256",
            "assessment_id",
            "mapped_fields",
            "evidence_sha256",
        }
        if set(remote) != required:
            raise ServiceNowV2Error(
                "VERIFICATION_MISMATCH",
                "Gateway read-back contract is invalid.",
                write_state="APPLIED",
            )
        request = plan.request
        allowed_outcomes = (
            {"UPDATED", "UNCHANGED"}
            if request["operation"] == "enrich_existing"
            else {"CREATED_DRAFT", "UNCHANGED"}
        )
        if remote["outcome"] not in allowed_outcomes:
            raise ServiceNowV2Error(
                "VERIFICATION_MISMATCH",
                "Gateway outcome does not match operation.",
                write_state="APPLIED",
            )
        delivery = request["delivery"]
        if (
            remote["idempotency_key"] != delivery["idempotency_key"]
            or remote["payload_sha256"] != delivery["payload_sha256"]
            or remote["mapping_sha256"] != delivery["mapping_sha256"]
            or remote["assessment_id"] != request["assessment"]["assessment_id"]
            or remote["mapped_fields"] != dict(plan.mapped_fields)
            or remote["evidence_sha256"] != plan.evidence["sha256"]
        ):
            raise ServiceNowV2Error(
                "VERIFICATION_MISMATCH",
                "Gateway read-back digest or payload mismatch.",
                write_state="APPLIED",
            )
        target = _target_from_remote(remote["target"])
        requested = request.get("target")
        if requested and (
            ("number" in requested and target["number"] != requested["number"])
            or ("sys_id" in requested and target["sys_id"] != requested["sys_id"])
        ):
            raise ServiceNowV2Error(
                "VERIFICATION_MISMATCH",
                "Gateway read-back target mismatch.",
                write_state="APPLIED",
            )
        if pinned_target and (
            target["number"] != pinned_target["number"]
            or target["sys_id"] != pinned_target["sys_id"]
        ):
            raise ServiceNowV2Error(
                "VERIFICATION_MISMATCH",
                "Gateway changed the pinned Change identity.",
                write_state="APPLIED",
            )

    def _conflict_response(
        self, plan: ServiceNowPlanV2, response: HttpResponse, attempts: int
    ) -> dict[str, Any]:
        try:
            payload = _json_object(response.body, "Gateway conflict")
            error = payload.get("error")
            code = error.get("code") if isinstance(error, dict) else None
        except ServiceNowV2Error:
            code = None
        safe_code = code if code in _KNOWN_REMOTE_CONFLICTS else "CONCURRENCY_CONFLICT"
        return self._failure(
            plan,
            ServiceNowV2Error(
                safe_code,
                "Gateway rejected a conflict without applying the write.",
                write_state="NOT_APPLIED",
            ),
            attempts,
            outcome="CONFLICT",
        )

    def _send_read(
        self,
        origin: str,
        path: str,
        authorization: str,
        request_id: str,
    ) -> tuple[HttpResponse, int]:
        attempts = 0
        started = self._monotonic()
        while attempts < self._retry_policy.attempts:
            attempts += 1
            try:
                response = self._send(
                    origin,
                    path,
                    "GET",
                    {
                        "Accept": "application/json",
                        "Authorization": authorization,
                        "X-PreflightOps-Request-Id": request_id,
                    },
                    None,
                )
            except TimeoutError as exc:
                if attempts < self._retry_policy.attempts and self._sleep_retry_raw(
                    request_id, attempts, started
                ):
                    continue
                raise ServiceNowV2Error(
                    "TIMEOUT",
                    "ServiceNow read timed out within the retry budget.",
                    retryable=True,
                    write_state="NOT_APPLIED",
                ) from exc
            if response.status in _REDIRECTS:
                raise ServiceNowV2Error("REDIRECT_REJECTED", "ServiceNow redirect was rejected.")
            if response.status == 429:
                delay = _retry_after(response.headers)
                if attempts < self._retry_policy.attempts and self._sleep_retry_raw(
                    request_id, attempts, started, explicit_delay=delay
                ):
                    continue
                raise ServiceNowV2Error(
                    "RATE_LIMITED",
                    "ServiceNow read rate limit exhausted the retry budget.",
                    retryable=True,
                    write_state="NOT_APPLIED",
                )
            if response.status in _RETRYABLE_STATUSES:
                if attempts < self._retry_policy.attempts and self._sleep_retry_raw(
                    request_id, attempts, started
                ):
                    continue
            return response, attempts
        raise AssertionError("bounded read loop exhausted unexpectedly")

    def _send(
        self,
        origin: str,
        path: str,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> HttpResponse:
        assert self._transport is not None
        url = f"{origin}{path}"
        self._network_policy.validate_request_url(url, origin)
        host = urllib.parse.urlsplit(origin).hostname
        assert host is not None
        self._network_policy.validate_resolution(host)
        try:
            return self._transport.send(
                HttpRequest(
                    method,
                    url,
                    dict(headers),
                    body,
                    self._retry_policy.request_timeout_seconds,
                )
            )
        except ServiceNowV2Error:
            raise
        except TimeoutError:
            raise
        except Exception as exc:
            raise ServiceNowV2Error(
                "TIMEOUT",
                "ServiceNow transport failed closed.",
                retryable=True,
                write_state="UNKNOWN" if method != "GET" else "NOT_APPLIED",
            ) from exc

    def _raise_http_error(self, response: HttpResponse, *, read_only: bool) -> None:
        if 200 <= response.status < 300:
            return
        state = "NOT_APPLIED" if read_only else "UNKNOWN"
        if response.status in {401}:
            raise ServiceNowV2Error(
                "AUTHENTICATION_FAILED", "ServiceNow authentication failed.", write_state=state
            )
        if response.status in {403}:
            raise ServiceNowV2Error(
                "AUTHORIZATION_DENIED", "ServiceNow authorization was denied.", write_state=state
            )
        if response.status == 404:
            raise ServiceNowV2Error(
                "TARGET_NOT_FOUND", "ServiceNow resource was not found.", write_state=state
            )
        raise ServiceNowV2Error(
            "RESPONSE_INVALID", "ServiceNow returned an unexpected status.", write_state=state
        )

    def _sleep_retry(
        self,
        plan: ServiceNowPlanV2,
        attempt: int,
        started: float,
        explicit_delay: float | None = None,
    ) -> bool:
        return self._sleep_retry_raw(
            str(plan.request["request_id"]), attempt, started, explicit_delay
        )

    def _sleep_retry_raw(
        self,
        request_id: str,
        attempt: int,
        started: float,
        explicit_delay: float | None = None,
    ) -> bool:
        delay = explicit_delay
        if delay is None:
            digest = hashlib.sha256(f"{request_id}:{attempt}".encode()).digest()
            jitter = int.from_bytes(digest[:2], "big") / 65535 * 0.25
            delay = self._retry_policy.base_delay_seconds * (2 ** (attempt - 1)) + jitter
        elapsed = self._monotonic() - started
        if delay < 0 or elapsed + delay > self._retry_policy.elapsed_seconds:
            return False
        self._sleep(delay)
        return True

    def _result(
        self,
        plan: ServiceNowPlanV2,
        outcome: str,
        verified: bool,
        attempts: int,
        *,
        target: Mapping[str, Any] | None = None,
        error: ServiceNowV2Error | None = None,
        retry_after: float | None = None,
    ) -> dict[str, Any]:
        request = plan.request
        result: dict[str, Any] = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "request_id": request["request_id"],
            "idempotency_key": request["delivery"]["idempotency_key"],
            "operation": request["operation"],
            "outcome": outcome,
            "verified": verified,
            "attempts": min(max(int(attempts), 0), 5),
            "audit": {
                "mapping_sha256": request["delivery"]["mapping_sha256"],
                "payload_sha256": request["delivery"]["payload_sha256"],
                "assessment_id": request["assessment"]["assessment_id"],
                "completed_at": _timestamp(self._clock()),
            },
        }
        if target is not None:
            result["target"] = _target_from_remote(target)
        if retry_after is not None and 0 <= retry_after <= 300:
            result["retry_after_seconds"] = int(retry_after)
        if error is not None:
            result["error"] = {
                "code": error.code,
                "retryable": error.retryable,
                "write_state": error.write_state,
                "message": error.safe_message,
            }
        return result

    def _failure(
        self,
        plan: ServiceNowPlanV2,
        error: ServiceNowV2Error,
        attempts: int,
        *,
        outcome: str = "FAILED",
        retry_after: float | None = None,
    ) -> dict[str, Any]:
        return self._result(
            plan,
            outcome,
            False,
            attempts,
            error=error,
            retry_after=retry_after,
        )

    def _finish(self, result: dict[str, Any], started: float) -> dict[str, Any]:
        if self._event_sink is not None:
            event = {
                "event": "servicenow_delivery_v2",
                "request_id": result["request_id"],
                "operation": result["operation"],
                "outcome": result["outcome"],
                "attempts": result["attempts"],
                "duration_ms": max(0, int((self._monotonic() - started) * 1000)),
                "target_hash": _target_hash(result.get("target")),
                "error_code": result.get("error", {}).get("code"),
            }
            self._event_sink(event)
        return result


def compare_servicenow_previews_v1_v2(
    legacy_preview: Mapping[str, Any], plan: ServiceNowPlanV2
) -> dict[str, Any]:
    """Return a content-free, offline migration comparison."""

    validate_servicenow_plan_v2(plan)
    legacy_payload = legacy_preview.get("payload")
    if not isinstance(legacy_payload, Mapping):
        raise ServiceNowV2Error("INVALID_MAPPING", "Legacy preview payload is invalid.")
    legacy_destinations = sorted(str(value) for value in legacy_payload)
    v2_destinations = sorted(plan.mapped_fields)
    return {
        "schema_version": "servicenow-migration-preview-v1",
        "legacy": {
            "mapping_version": str(legacy_preview.get("mapping_version", "unknown")),
            "correlation_id_sha256": hashlib.sha256(
                str(legacy_preview.get("correlation_id", "")).encode()
            ).hexdigest(),
            "destinations": legacy_destinations,
        },
        "enterprise": {
            "request_id": plan.request["request_id"],
            "idempotency_key": plan.request["delivery"]["idempotency_key"],
            "mapping_sha256": plan.request["delivery"]["mapping_sha256"],
            "payload_sha256": plan.request["delivery"]["payload_sha256"],
            "destinations": v2_destinations,
        },
        "shared_destinations": sorted(set(legacy_destinations).intersection(v2_destinations)),
        "network_calls": 0,
        "notes": [
            "v2 never creates implicitly",
            "v2 production writes require gateway CAS and unique delivery",
            "v1 remains available only as the separately selected legacy path",
        ],
    }


def _validate_mapping_v2(mapping: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "profile_id",
        "api",
        "operations",
        "fields",
        "creation",
        "concurrency",
        "evidence",
        "limits",
    }
    _exact_keys(mapping, required, "mapping")
    if mapping["schema_version"] != MAPPING_SCHEMA_VERSION:
        raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow mapping version is unsupported.")
    if not isinstance(mapping["profile_id"], str) or not _ALIAS_RE.fullmatch(mapping["profile_id"]):
        raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow mapping profile_id is invalid.")
    api = mapping["api"]
    _exact_keys(
        api,
        {"production_profile", "sandbox_profile", "version", "table_api_legacy_mode"},
        "mapping.api",
    )
    if api != {
        "production_profile": GATEWAY_PROFILE,
        "sandbox_profile": CHANGE_API_PROFILE,
        "version": "v1",
        "table_api_legacy_mode": "read_only",
    }:
        raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow API profiles are not approved.")
    operations = mapping["operations"]
    _exact_keys(operations, {"enrich_existing", "create_draft"}, "mapping.operations")
    if operations["enrich_existing"] is not True or type(operations["create_draft"]) is not bool:
        raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow operation gates are invalid.")
    fields = mapping["fields"]
    _exact_keys(fields, set(_SEMANTIC_SOURCES), "mapping.fields")
    destinations: set[str] = set()
    for semantic, expected_source in _SEMANTIC_SOURCES.items():
        rule = fields[semantic]
        if not isinstance(rule, Mapping):
            raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow field rule is invalid.")
        allowed = {"source", "destination", "max_length", "omit_empty"}
        if not {"source", "destination", "max_length"}.issubset(rule) or not set(rule).issubset(
            allowed
        ):
            raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow field rule is not strict.")
        if rule["source"] != expected_source:
            raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow semantic source is incorrect.")
        destination = rule["destination"]
        if not isinstance(destination, str) or not _DESTINATION_RE.fullmatch(destination):
            raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow destination is not allowlisted.")
        if destination in _FORBIDDEN_DESTINATIONS or any(
            part in destination for part in _FORBIDDEN_DESTINATION_PARTS
        ):
            raise ServiceNowV2Error(
                "INVALID_MAPPING", "ServiceNow workflow destination is forbidden."
            )
        if destination == DELIVERY_FIELD or destination in destinations:
            raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow destinations must be unique.")
        destinations.add(destination)
        limit = rule["max_length"]
        if type(limit) is not int or not 1 <= limit <= 16000:
            raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow field limit is invalid.")
        if "omit_empty" in rule and type(rule["omit_empty"]) is not bool:
            raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow omit_empty must be boolean.")
    creation = mapping["creation"]
    _exact_keys(
        creation,
        {
            "allowed_model_sys_ids",
            "require_external_confirmation",
            "require_capability_attestation",
        },
        "mapping.creation",
    )
    models = creation["allowed_model_sys_ids"]
    if (
        not isinstance(models, list)
        or len(models) > 32
        or not all(isinstance(value, str) and _SYS_ID_RE.fullmatch(value) for value in models)
        or len(models) != len(set(models))
        or creation["require_external_confirmation"] is not True
        or creation["require_capability_attestation"] is not True
    ):
        raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow draft creation policy is invalid.")
    concurrency = mapping["concurrency"]
    _exact_keys(
        concurrency,
        {"strategy", "version_field", "delivery_field", "require_unique_delivery"},
        "mapping.concurrency",
    )
    if concurrency != {
        "strategy": "server_compare_and_set",
        "version_field": "sys_mod_count",
        "delivery_field": DELIVERY_FIELD,
        "require_unique_delivery": True,
    }:
        raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow concurrency policy is invalid.")
    evidence = mapping["evidence"]
    _exact_keys(
        evidence,
        {"mode", "attachment_max_bytes", "allowed_link_hosts", "deduplicate_by_digest"},
        "mapping.evidence",
    )
    if evidence["mode"] not in {"attachment", "https_link", "attachment_or_link"}:
        raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow evidence mode is invalid.")
    if (
        type(evidence["attachment_max_bytes"]) is not int
        or not 1024 <= evidence["attachment_max_bytes"] <= _MAX_REQUEST_BYTES
        or evidence["deduplicate_by_digest"] is not True
    ):
        raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow evidence limits are invalid.")
    hosts = evidence["allowed_link_hosts"]
    if (
        not isinstance(hosts, list)
        or len(hosts) > 32
        or not all(isinstance(host, str) for host in hosts)
        or len(hosts) != len(set(hosts))
    ):
        raise ServiceNowV2Error("INVALID_MAPPING", "ServiceNow evidence hosts are invalid.")
    for host in hosts:
        _validate_policy_host(host, "evidence")
    limits = mapping["limits"]
    _exact_keys(
        limits,
        {"summary_characters", "blocker_count", "attempts", "elapsed_seconds"},
        "mapping.limits",
    )
    for name, minimum, maximum in (
        ("summary_characters", 256, 16000),
        ("blocker_count", 1, 50),
        ("attempts", 1, 5),
        ("elapsed_seconds", 1, 300),
    ):
        value = limits[name]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ServiceNowV2Error("INVALID_MAPPING", f"ServiceNow {name} limit is invalid.")


def _validate_request_v2(request: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "request_id",
        "operation",
        "dry_run",
        "write_enabled",
        "transport_profile",
        "instance",
        "assessment",
        "delivery",
        "preconditions",
    }
    optional = {"target", "creation"}
    if not required.issubset(request) or not set(request).issubset(required | optional):
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow request shape is invalid.")
    if request["schema_version"] != REQUEST_SCHEMA_VERSION or not _REQUEST_ID_RE.fullmatch(
        str(request["request_id"])
    ):
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow request identity is invalid.")
    operation = request["operation"]
    if operation not in {"enrich_existing", "create_draft"}:
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow request operation is invalid.")
    if type(request["dry_run"]) is not bool or type(request["write_enabled"]) is not bool:
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow request mode is invalid.")
    if request["write_enabled"] and (
        request["dry_run"] or request["transport_profile"] != GATEWAY_PROFILE
    ):
        raise ServiceNowV2Error("AUTHORIZATION_DENIED", "ServiceNow live-write mode is invalid.")
    if request["transport_profile"] not in {GATEWAY_PROFILE, CHANGE_API_PROFILE}:
        raise ServiceNowV2Error("CAPABILITY_MISSING", "ServiceNow transport profile is invalid.")
    instance = request["instance"]
    _exact_keys(instance, {"alias", "origin"}, "request.instance")
    if not _ALIAS_RE.fullmatch(str(instance["alias"])):
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow instance alias is invalid.")
    if operation == "enrich_existing":
        if "target" not in request or "creation" in request:
            raise ServiceNowV2Error("TARGET_AMBIGUOUS", "Enrichment target is invalid.")
        target = request["target"]
        if not isinstance(target, Mapping) or len(target) != 1:
            raise ServiceNowV2Error("TARGET_AMBIGUOUS", "Enrichment target is invalid.")
        if "number" in target and not _CHANGE_NUMBER_RE.fullmatch(str(target["number"])):
            raise ServiceNowV2Error("TARGET_NOT_FOUND", "Change number is invalid.")
        if "sys_id" in target and not _SYS_ID_RE.fullmatch(str(target["sys_id"])):
            raise ServiceNowV2Error("TARGET_NOT_FOUND", "Change sys_id is invalid.")
    else:
        if "creation" not in request or "target" in request:
            raise ServiceNowV2Error("MODEL_NOT_ALLOWED", "Draft creation request is invalid.")
        creation = request["creation"]
        _exact_keys(creation, {"model_sys_id", "external_authorization_id"}, "request.creation")
        if not _SYS_ID_RE.fullmatch(
            str(creation["model_sys_id"])
        ) or not _AUTHORIZATION_ID_RE.fullmatch(str(creation["external_authorization_id"])):
            raise ServiceNowV2Error("MODEL_NOT_ALLOWED", "Draft creation identity is invalid.")
    assessment = request["assessment"]
    assessment_required = {
        "assessment_id",
        "report_id",
        "report_sha256",
        "verdict",
        "risk_level",
        "confidence_level",
        "policy_name",
        "policy_version",
        "commit",
        "assessed_at",
    }
    _exact_keys(assessment, assessment_required, "request.assessment")
    if not _ASSESSMENT_ID_RE.fullmatch(
        str(assessment["assessment_id"])
    ) or not _REPORT_ID_RE.fullmatch(str(assessment["report_id"])):
        raise ServiceNowV2Error("RESPONSE_INVALID", "Assessment identities are invalid.")
    if not _SHA256_RE.fullmatch(str(assessment["report_sha256"])):
        raise ServiceNowV2Error("RESPONSE_INVALID", "Assessment report digest is invalid.")
    if assessment["report_id"].rsplit(":", 1)[-1] != assessment["report_sha256"]:
        raise ServiceNowV2Error("REPLAY_MISMATCH", "Assessment report identity is inconsistent.")
    if assessment["verdict"] not in {
        "BLOCK",
        "INDETERMINATE",
        "READY_FOR_HUMAN_REVIEW",
        "REVIEW_REQUIRED",
    }:
        raise ServiceNowV2Error("RESPONSE_INVALID", "Assessment verdict is invalid.")
    if assessment["risk_level"] not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        raise ServiceNowV2Error("RESPONSE_INVALID", "Assessment risk level is invalid.")
    if assessment["confidence_level"] not in {"LOW", "MEDIUM", "HIGH"}:
        raise ServiceNowV2Error("RESPONSE_INVALID", "Assessment confidence level is invalid.")
    if (
        not isinstance(assessment["policy_name"], str)
        or not 1 <= len(assessment["policy_name"]) <= 128
        or _CONTROL_RE.search(assessment["policy_name"])
        or not isinstance(assessment["policy_version"], str)
        or not 1 <= len(assessment["policy_version"]) <= 64
        or _CONTROL_RE.search(assessment["policy_version"])
    ):
        raise ServiceNowV2Error("RESPONSE_INVALID", "Assessment policy identity is invalid.")
    if not re.fullmatch(r"[0-9a-f]{40}", str(assessment["commit"])):
        raise ServiceNowV2Error("RESPONSE_INVALID", "Assessment commit is invalid.")
    _parse_timestamp(str(assessment["assessed_at"]), "Assessment timestamp")
    delivery = request["delivery"]
    required_delivery = {
        "mapping_profile_id",
        "mapping_sha256",
        "idempotency_key",
        "payload_sha256",
        "evidence_mode",
    }
    if not required_delivery.issubset(delivery) or not set(delivery).issubset(
        required_delivery | {"evidence_url"}
    ):
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow delivery contract is invalid.")
    if (
        not _SHA256_RE.fullmatch(str(delivery["mapping_sha256"]))
        or not _SHA256_RE.fullmatch(str(delivery["payload_sha256"]))
        or not _DELIVERY_KEY_RE.fullmatch(str(delivery["idempotency_key"]))
    ):
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow delivery digests are invalid.")
    if not _ALIAS_RE.fullmatch(str(delivery["mapping_profile_id"])):
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow mapping profile is invalid.")
    if delivery["evidence_mode"] == "attachment" and "evidence_url" in delivery:
        raise ServiceNowV2Error("RESPONSE_INVALID", "Attachment delivery must not include a URL.")
    if delivery["evidence_mode"] == "https_link" and "evidence_url" not in delivery:
        raise ServiceNowV2Error("RESPONSE_INVALID", "Link delivery requires an evidence URL.")
    if delivery["evidence_mode"] not in {"attachment", "https_link"}:
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow evidence mode is invalid.")
    preconditions = request["preconditions"]
    if not isinstance(preconditions, Mapping) or not _SHA256_RE.fullmatch(
        str(preconditions.get("capability_attestation_sha256", ""))
    ):
        raise ServiceNowV2Error("CAPABILITY_MISSING", "ServiceNow capability digest is invalid.")
    if operation == "enrich_existing" and (
        type(preconditions.get("expected_sys_mod_count")) is not int
        or preconditions["expected_sys_mod_count"] < 0
    ):
        raise ServiceNowV2Error("CONCURRENCY_CONFLICT", "Expected sys_mod_count is invalid.")
    expected_preconditions = (
        {"capability_attestation_sha256", "expected_sys_mod_count"}
        if operation == "enrich_existing"
        else {"capability_attestation_sha256"}
    )
    if set(preconditions) != expected_preconditions:
        raise ServiceNowV2Error("CAPABILITY_MISSING", "ServiceNow preconditions are invalid.")


def _map_report(mapping: Mapping[str, Any], sources: Mapping[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    for semantic in _SEMANTIC_SOURCES:
        rule = mapping["fields"][semantic]
        value: Any = sources
        for segment in str(rule["source"]).split("."):
            if not isinstance(value, Mapping):
                value = None
                break
            value = value.get(segment)
        if value is None:
            rendered = ""
        elif isinstance(value, str):
            rendered = " ".join(value.split())
        else:
            rendered = canonical_json(value).decode("utf-8")
        if not rendered and rule.get("omit_empty", True):
            continue
        limit = int(rule["max_length"])
        if len(rendered) > limit:
            marker = "…[truncated]"
            rendered = rendered[: max(0, limit - len(marker))].rstrip() + marker
        output[str(rule["destination"])] = rendered
    return dict(sorted(output.items()))


def _exact_keys(value: Any, expected: set[str], context: str) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ServiceNowV2Error("INVALID_MAPPING", f"{context} must contain only approved fields.")


def _validate_policy_host(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise ServiceNowV2Error("UNTRUSTED_DESTINATION", f"{label} host is invalid.")
    host = value.rstrip(".").lower()
    if (
        not host
        or host != value
        or len(host) > 253
        or "*" in host
        or ".." in host
        or host == "localhost"
        or host.endswith(".localhost")
        or host.endswith(".local")
        or not all(re.fullmatch(r"[a-z0-9-]{1,63}", part) for part in host.split("."))
    ):
        raise ServiceNowV2Error("UNTRUSTED_DESTINATION", f"{label} host is invalid.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise ServiceNowV2Error("UNTRUSTED_DESTINATION", f"{label} host must not be an IP literal.")


def _validate_https_origin(value: str, allowed_hosts: Sequence[str], label: str) -> str:
    if not isinstance(value, str) or _CONTROL_RE.search(value) or "\\" in value:
        raise ServiceNowV2Error("UNTRUSTED_DESTINATION", f"{label} origin is invalid.")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ServiceNowV2Error("UNTRUSTED_DESTINATION", f"{label} origin is malformed.") from exc
    host = parsed.hostname.rstrip(".").lower() if parsed.hostname else ""
    normalized_allowed = {_validate_policy_host(item, label) for item in allowed_hosts}
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or host not in normalized_allowed
    ):
        raise ServiceNowV2Error("UNTRUSTED_DESTINATION", f"{label} origin is not allowlisted.")
    _validate_policy_host(host, label)
    return f"https://{host}"


def _validate_https_resource(value: str, allowed_hosts: Sequence[str], label: str) -> str:
    if not isinstance(value, str) or _CONTROL_RE.search(value) or "\\" in value:
        raise ServiceNowV2Error("UNTRUSTED_DESTINATION", f"{label} URL is invalid.")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ServiceNowV2Error("UNTRUSTED_DESTINATION", f"{label} URL is malformed.") from exc
    host = parsed.hostname.rstrip(".").lower() if parsed.hostname else ""
    normalized_allowed = {_validate_policy_host(item, label) for item in allowed_hosts}
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not parsed.path.startswith("/")
        or parsed.path.startswith("//")
        or parsed.query
        or parsed.fragment
        or host not in normalized_allowed
    ):
        raise ServiceNowV2Error("UNTRUSTED_DESTINATION", f"{label} URL is not allowlisted.")
    return urllib.parse.urlunsplit(("https", host, parsed.path, "", ""))


def _target_from_remote(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow target is invalid.")
    if set(value) != {"number", "sys_id", "sys_mod_count"}:
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow target contract is invalid.")
    number = value["number"]
    sys_id = value["sys_id"]
    raw_count = value["sys_mod_count"]
    if not isinstance(number, str) or not _CHANGE_NUMBER_RE.fullmatch(number):
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow target number is invalid.")
    if not isinstance(sys_id, str) or not _SYS_ID_RE.fullmatch(sys_id):
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow target sys_id is invalid.")
    if isinstance(raw_count, str) and raw_count.isdecimal():
        raw_count = int(raw_count)
    if type(raw_count) is not int or raw_count < 0:
        raise ServiceNowV2Error("RESPONSE_INVALID", "ServiceNow target version is invalid.")
    return {"number": number, "sys_id": sys_id, "sys_mod_count": raw_count}


def _json_object(raw: bytes, context: str) -> dict[str, Any]:
    if not isinstance(raw, bytes) or len(raw) > _MAX_RESPONSE_BYTES:
        raise ServiceNowV2Error("RESPONSE_INVALID", f"{context} response is not bounded.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ServiceNowV2Error("RESPONSE_INVALID", f"{context} response is invalid JSON.") from exc
    if not isinstance(value, dict):
        raise ServiceNowV2Error("RESPONSE_INVALID", f"{context} response must be an object.")
    return value


def _retry_after(headers: Mapping[str, str]) -> float | None:
    value = next((item for key, item in headers.items() if key.lower() == "retry-after"), None)
    if value is None:
        return None
    rendered = str(value).strip()
    if not rendered.isdecimal():
        return None
    return float(rendered)


def _safe_message(value: str) -> str:
    rendered = _CONTROL_RE.sub("", str(value))
    rendered = " ".join(rendered.split())
    if len(rendered) > 320:
        rendered = rendered[:307].rstrip() + "…[truncated]"
    return rendered


def _timestamp(value: dt.datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ServiceNowV2Error("RESPONSE_INVALID", "Execution clock must be timezone-aware.")
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str, context: str) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ServiceNowV2Error("RESPONSE_INVALID", f"{context} must be UTC with Z suffix.")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ServiceNowV2Error("RESPONSE_INVALID", f"{context} is invalid.") from exc
    if parsed.utcoffset() != dt.timedelta(0):
        raise ServiceNowV2Error("RESPONSE_INVALID", f"{context} must be UTC.")
    return parsed


def _target_hash(target: Any) -> str | None:
    if not isinstance(target, Mapping):
        return None
    identity = {key: target[key] for key in ("number", "sys_id") if key in target}
    return hashlib.sha256(canonical_json(identity)).hexdigest()[:24]

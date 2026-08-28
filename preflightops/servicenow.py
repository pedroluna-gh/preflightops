"""Hardened ServiceNow change-evidence integration.

The deterministic PreflightOps assessment remains authoritative.  This module
only prepares and publishes pre-change evidence; it deliberately refuses to
map workflow, approval, assignment, or closure fields.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import re
import urllib.parse
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

from ._version import __version__
from .integration_errors import IntegrationError
from .ticket import generate_ticket_markdown

SERVICENOW_ALLOWED_HOSTS_ENV = "SERVICENOW_ALLOWED_HOSTS"
SERVICENOW_TOKEN_ENV = "SERVICENOW_TOKEN"

_DEFAULT_ALLOWED_SUFFIX = ".service-now.com"
_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_REFERENCE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SYS_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_SAFE_CORRELATION_RE = re.compile(r"[^a-z0-9._:-]+")
_SECRET_KEY_RE = re.compile(
    r"(?:password|passwd|secret|token|credential|private[_-]?key|authorization)", re.I
)

_SAFE_STANDARD_FIELDS = {
    "short_description",
    "description",
    "implementation_plan",
    "backout_plan",
    "test_plan",
    "justification",
    "correlation_id",
    "correlation_display",
    "risk",
    "impact",
}
_DEFAULT_FIELD_LIMITS = {
    "short_description": 160,
    "correlation_id": 100,
    "correlation_display": 100,
}
_DEFAULT_TEXT_LIMIT = 4000
_MAX_EVIDENCE_BYTES = 1024 * 1024

DEFAULT_SERVICENOW_MAPPING: dict[str, Any] = {
    "version": "1",
    "table": "change_request",
    "fields": {
        "short_description": {"source": "summary", "required": True},
        "description": {"source": "ticket_markdown", "required": True},
        "implementation_plan": {"source": "change.description"},
        "backout_plan": {"source": "change.rollback_plan"},
        "test_plan": {"source": "change.validation_plan"},
        "justification": {"source": "result.business_impact"},
        "correlation_display": {"value": "PreflightOps pre-change evidence"},
        "correlation_id": {"source": "correlation_id", "required": True},
    },
}


def _change_section(change_doc: Any) -> dict[str, Any]:
    if isinstance(change_doc, dict) and isinstance(change_doc.get("change"), dict):
        return change_doc["change"]
    return {}


def _legacy_correlation_id(result: Mapping[str, Any], change_doc: Any = None) -> str:
    change = _change_section(change_doc)
    basis = "|".join(
        [
            str(result.get("service") or "").strip(),
            str(result.get("environment") or "").strip(),
            str(change.get("title") or "").strip(),
        ]
    ).lower()
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return f"preflightops-{digest}"


def correlation_id(result: Mapping[str, Any], change_doc: Any = None) -> str:
    """Return a stable external identity, preferring the manifest change id.

    Old title-based identities remain discoverable during lookup so existing
    records are migrated instead of duplicated.
    """

    explicit = str(_change_section(change_doc).get("id") or "").strip().lower()
    if not explicit:
        return _legacy_correlation_id(result, change_doc)
    slug = _SAFE_CORRELATION_RE.sub("-", explicit).strip("-._:")
    candidate = f"preflightops-{slug}" if slug else ""
    if candidate and len(candidate) <= 100:
        return candidate
    digest = hashlib.sha256(explicit.encode("utf-8")).hexdigest()[:24]
    return f"preflightops-change-{digest}"


def _short_description(result: Mapping[str, Any], change_doc: Any = None) -> str:
    change = _change_section(change_doc)
    title = str(change.get("title") or "").strip() or "Production change"
    service = str(result.get("service") or "").strip() or "unknown service"
    level = str(result.get("risk_level") or "").strip() or "UNKNOWN"
    return _truncate(f"[{level}] {title} ({service})", 160)


def validate_instance_url(instance_url: str, env: Mapping[str, str] | None = None) -> str:
    """Validate and normalize the ServiceNow origin before credentials exist."""

    env = os.environ if env is None else env
    raw = str(instance_url or "").strip()
    if not raw:
        raise IntegrationError(
            "ServiceNow instance URL is required (e.g. https://dev12345.service-now.com)."
        )
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise IntegrationError("ServiceNow instance URL is malformed.") from exc
    if parsed.scheme.lower() != "https":
        raise IntegrationError("ServiceNow instance URL must use HTTPS.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise IntegrationError("ServiceNow instance URL must be a credential-free HTTPS origin.")
    if port not in (None, 443):
        raise IntegrationError("ServiceNow instance URL may only use the standard HTTPS port.")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise IntegrationError(
            "ServiceNow instance URL must not include a path, query, or fragment."
        )

    host = parsed.hostname.rstrip(".").lower()
    configured = {
        value.strip().rstrip(".").lower()
        for value in str(env.get(SERVICENOW_ALLOWED_HOSTS_ENV, "")).split(",")
        if value.strip()
    }
    hosted_instance = host.endswith(_DEFAULT_ALLOWED_SUFFIX) and host != _DEFAULT_ALLOWED_SUFFIX[1:]
    if not hosted_instance and host not in configured:
        raise IntegrationError(
            "ServiceNow destination is not trusted. Use a *.service-now.com instance or add the "
            f"exact custom hostname to {SERVICENOW_ALLOWED_HOSTS_ENV}."
        )
    return f"https://{host}"


def load_mapping(mapping: str | Path | Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Load and validate a versioned, deliberately limited field mapping."""

    if mapping is None:
        loaded: Any = copy.deepcopy(DEFAULT_SERVICENOW_MAPPING)
    elif isinstance(mapping, Mapping):
        loaded = copy.deepcopy(dict(mapping))
    elif isinstance(mapping, (str, os.PathLike)):
        try:
            with open(mapping, encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError) as exc:
            raise IntegrationError(f"Unable to load ServiceNow mapping: {exc}") from exc
    else:
        raise IntegrationError("ServiceNow mapping must be a YAML/JSON object or file path.")
    if not isinstance(loaded, dict):
        raise IntegrationError("ServiceNow mapping must be a YAML/JSON object.")
    if str(loaded.get("version")) != "1":
        raise IntegrationError("Unsupported ServiceNow mapping version; expected version 1.")
    if loaded.get("table", "change_request") != "change_request":
        raise IntegrationError("ServiceNow mapping may only target the change_request table.")
    fields = loaded.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise IntegrationError("ServiceNow mapping requires a non-empty fields object.")
    for destination, rule in fields.items():
        if not isinstance(destination, str) or not _FIELD_RE.fullmatch(destination):
            raise IntegrationError(f"Invalid ServiceNow destination field: {destination!r}.")
        if destination not in _SAFE_STANDARD_FIELDS and not destination.startswith("u_"):
            raise IntegrationError(
                f"ServiceNow field {destination!r} is outside the pre-change evidence allowlist."
            )
        if isinstance(rule, str):
            fields[destination] = {"source": rule}
            rule = fields[destination]
        if not isinstance(rule, dict) or ("source" in rule) == ("value" in rule):
            raise IntegrationError(
                f"Mapping for {destination!r} must define exactly one of source or value."
            )
        if "source" in rule and not isinstance(rule["source"], str):
            raise IntegrationError(f"Mapping source for {destination!r} must be a string.")
        if "max_length" in rule:
            limit = rule["max_length"]
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100000:
                raise IntegrationError(
                    f"Mapping max_length for {destination!r} must be between 1 and 100000."
                )
    return loaded


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit == 1:
        return value[:1]
    return value[: limit - 1].rstrip() + "…"


def _render_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        rendered = [_render_value(item) for item in value]
        return "\n".join(f"- {item}" for item in rendered if item)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _safe_evidence_value(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "[depth-limited]"
    if isinstance(value, Mapping):
        return {
            str(key): _safe_evidence_value(item, depth + 1)
            for key, item in list(value.items())[:100]
            if not _SECRET_KEY_RE.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_evidence_value(item, depth + 1) for item in list(value)[:100]]
    if isinstance(value, str):
        return _truncate(value, 4000)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _truncate(str(value), 4000)


def _source_from_env(env: Mapping[str, str]) -> dict[str, str]:
    source = {
        "repository": env.get("GITHUB_REPOSITORY", ""),
        "sha": env.get("GITHUB_SHA", ""),
        "ref": env.get("GITHUB_REF", ""),
        "run_id": env.get("GITHUB_RUN_ID", ""),
        "actor": env.get("GITHUB_ACTOR", ""),
        "workflow": env.get("GITHUB_WORKFLOW", ""),
    }
    server = env.get("GITHUB_SERVER_URL", "")
    if server and source["repository"] and source["run_id"]:
        source["run_url"] = f"{server}/{source['repository']}/actions/runs/{source['run_id']}"
    return {key: value for key, value in source.items() if value}


def build_evidence(
    result: Mapping[str, Any],
    change_doc: Any = None,
    ticket_markdown: str | None = None,
    *,
    source: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a bounded, secret-scrubbed, versioned evidence package."""

    env = os.environ if env is None else env
    change = _change_section(change_doc)
    ticket_markdown = ticket_markdown or generate_ticket_markdown(dict(result), change_doc)
    provenance = _safe_evidence_value(dict(source or _source_from_env(env)))
    assessment_keys = (
        "risk_score",
        "risk_level",
        "recommendation",
        "triggered_rules",
        "missing_controls",
        "business_impact",
        "policy_pack",
        "monitoring_evidence",
        "change_scope",
    )
    semantic = {
        "schema_version": "1.0",
        "producer": {"name": "PreflightOps", "version": __version__},
        "change": _safe_evidence_value(
            {
                "id": change.get("id"),
                "title": change.get("title"),
                "service": result.get("service") or change.get("service"),
                "environment": result.get("environment") or change.get("environment"),
                "change_type": result.get("change_type") or change.get("change_type"),
            }
        ),
        "assessment": _safe_evidence_value(
            {key: result.get(key) for key in assessment_keys if key in result}
        ),
        "report": {"ticket_sha256": hashlib.sha256(ticket_markdown.encode("utf-8")).hexdigest()},
        "provenance": provenance,
        "governance": {
            "purpose": "Automated pre-change evidence",
            "cab_authority": "ServiceNow workflow and human CAB approval remain authoritative",
            "changes_workflow_state": False,
        },
    }
    hash_input = copy.deepcopy(semantic)
    if isinstance(hash_input.get("provenance"), dict):
        for volatile in ("run_id", "run_url", "actor", "workflow"):
            hash_input["provenance"].pop(volatile, None)
    canonical = json.dumps(hash_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    semantic["evidence_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    semantic["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return semantic


def _lookup_source(
    source_name: str,
    *,
    result: Mapping[str, Any],
    change: Mapping[str, Any],
    ticket_markdown: str,
    correlation: str,
    evidence: Mapping[str, Any],
    source: Mapping[str, Any],
) -> Any:
    direct = {
        "summary": _short_description(result, {"change": dict(change)}),
        "ticket_markdown": ticket_markdown,
        "correlation_id": correlation,
        "evidence_hash": evidence["evidence_hash"],
        "evidence_summary": (
            f"PreflightOps automated pre-change evidence: {result.get('risk_level', 'UNKNOWN')} "
            f"({result.get('risk_score', 'unknown')}/100). Evidence "
            f"sha256:{evidence['evidence_hash']}. CAB approval remains authoritative."
        ),
    }
    if source_name in direct:
        return direct[source_name]
    namespace, dot, path = source_name.partition(".")
    roots: dict[str, Mapping[str, Any]] = {
        "result": result,
        "change": change,
        "source": source,
        "evidence": evidence,
    }
    if not dot or namespace not in roots:
        raise IntegrationError(f"Unsupported ServiceNow mapping source: {source_name!r}.")
    value: Any = roots[namespace]
    for segment in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(segment)
    return value


def prepare_payload(
    result: Mapping[str, Any],
    change_doc: Any = None,
    ticket_markdown: str | None = None,
    *,
    mapping: str | Path | Mapping[str, Any] | None = None,
    source: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Prepare the record payload and evidence without making a network call."""

    env = os.environ if env is None else env
    configured = load_mapping(mapping)
    change = _change_section(change_doc)
    ticket_markdown = ticket_markdown or generate_ticket_markdown(dict(result), change_doc)
    correlation = correlation_id(result, change_doc)
    provenance = dict(source or _source_from_env(env))
    evidence = build_evidence(result, change_doc, ticket_markdown, source=provenance, env=env)
    payload: dict[str, str] = {}
    for destination, rule in configured["fields"].items():
        raw = (
            rule["value"]
            if "value" in rule
            else _lookup_source(
                rule["source"],
                result=result,
                change=change,
                ticket_markdown=ticket_markdown,
                correlation=correlation,
                evidence=evidence,
                source=provenance,
            )
        )
        rendered = _render_value(raw)
        if not rendered and rule.get("required"):
            raise IntegrationError(
                f"Required ServiceNow field {destination!r} resolved to an empty value."
            )
        if not rendered and rule.get("omit_empty", True):
            continue
        limit = rule.get("max_length", _DEFAULT_FIELD_LIMITS.get(destination, _DEFAULT_TEXT_LIMIT))
        payload[destination] = _truncate(rendered, limit)

    # Identity is owned by PreflightOps and cannot be redirected by a mapping.
    payload["correlation_id"] = correlation
    return {
        "mapping_version": configured["version"],
        "table": "change_request",
        "correlation_id": correlation,
        "legacy_correlation_id": _legacy_correlation_id(result, change_doc),
        "payload": payload,
        "evidence": evidence,
        "evidence_filename": f"preflightops-evidence-{evidence['evidence_hash'][:16]}.json",
    }


def _query_url(base_url: str, params: Mapping[str, str]) -> str:
    return f"{base_url}?{urllib.parse.urlencode(params)}"


def _records_from_response(data: Any, context: str) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or not isinstance(data.get("result"), list):
        raise IntegrationError(f"ServiceNow returned an invalid {context} response.")
    if not all(isinstance(record, dict) for record in data["result"]):
        raise IntegrationError(f"ServiceNow returned invalid records for {context}.")
    return data["result"]


def _find_record(
    table_url: str,
    headers: Mapping[str, str],
    prepared: Mapping[str, Any],
    request_json: Callable[..., tuple[int, dict[str, Any]]],
    change_reference: str | None,
) -> list[dict[str, Any]]:
    fields = sorted({"sys_id", "number", "correlation_id", *prepared["payload"].keys()})
    if change_reference:
        reference = change_reference.strip()
        if not _REFERENCE_RE.fullmatch(reference):
            raise IntegrationError("ServiceNow change reference contains unsafe characters.")
        query_field = "sys_id" if _SYS_ID_RE.fullmatch(reference) else "number"
        query = f"{query_field}={reference}"
    else:
        candidates = [prepared["correlation_id"]]
        legacy = prepared["legacy_correlation_id"]
        if legacy not in candidates:
            candidates.append(legacy)
        query = f"correlation_idIN{','.join(candidates)}"
    _, found = request_json(
        _query_url(
            table_url,
            {
                "sysparm_query": query,
                "sysparm_limit": "2",
                "sysparm_fields": ",".join(fields),
                "sysparm_exclude_reference_link": "true",
            },
        ),
        "GET",
        headers,
    )
    records = _records_from_response(found, "change lookup")
    if len(records) > 1:
        raise IntegrationError(
            "ServiceNow lookup returned multiple change records; refusing an ambiguous update."
        )
    return records


def _material_update_needed(current: Mapping[str, Any], payload: Mapping[str, str]) -> bool:
    for field, expected in payload.items():
        actual = current.get(field)
        if isinstance(actual, Mapping):
            actual = actual.get("value")
        if str(actual or "") != str(expected):
            return True
    return False


def _verify_record(
    table_url: str,
    sys_id: str,
    headers: Mapping[str, str],
    payload: Mapping[str, str],
    request_json: Callable[..., tuple[int, dict[str, Any]]],
) -> dict[str, Any]:
    fields = sorted({"sys_id", "number", "correlation_id", *payload.keys()})
    _, verified = request_json(
        _query_url(
            f"{table_url}/{sys_id}",
            {
                "sysparm_fields": ",".join(fields),
                "sysparm_exclude_reference_link": "true",
            },
        ),
        "GET",
        headers,
    )
    record = verified.get("result") if isinstance(verified, dict) else None
    if not isinstance(record, dict) or record.get("sys_id") != sys_id:
        raise IntegrationError("ServiceNow post-write verification could not confirm the record.")
    if record.get("correlation_id") != payload["correlation_id"]:
        raise IntegrationError("ServiceNow post-write verification found a correlation mismatch.")
    for field, expected in payload.items():
        actual = record.get(field)
        if isinstance(actual, Mapping):
            actual = actual.get("value")
        if str(actual or "") != str(expected):
            raise IntegrationError(
                f"ServiceNow post-write verification found a mismatch in {field!r}."
            )
    return record


def _attach_evidence(
    instance_url: str,
    sys_id: str,
    headers: Mapping[str, str],
    prepared: Mapping[str, Any],
    request_json: Callable[..., tuple[int, dict[str, Any]]],
) -> dict[str, Any]:
    filename = prepared["evidence_filename"]
    attachment_url = f"{instance_url}/api/now/attachment"
    query = f"table_name=change_request^table_sys_id={sys_id}^file_name={filename}"

    def find() -> list[dict[str, Any]]:
        _, data = request_json(
            _query_url(
                attachment_url,
                {
                    "sysparm_query": query,
                    "sysparm_limit": "2",
                    "sysparm_fields": "sys_id,file_name,size_bytes,table_sys_id",
                },
            ),
            "GET",
            headers,
        )
        records = _records_from_response(data, "attachment lookup")
        if len(records) > 1:
            raise IntegrationError(
                "ServiceNow returned duplicate evidence attachments; refusing to add another."
            )
        return records

    existing = find()
    if existing:
        return {
            "status": "unchanged",
            "sys_id": existing[0].get("sys_id"),
            "filename": filename,
            "sha256": prepared["evidence"]["evidence_hash"],
        }

    raw = json.dumps(prepared["evidence"], ensure_ascii=False, sort_keys=True, indent=2).encode(
        "utf-8"
    )
    if len(raw) > _MAX_EVIDENCE_BYTES:
        raise IntegrationError("ServiceNow evidence exceeds the 1 MiB safety limit.")
    upload_headers = dict(headers)
    upload_headers["Content-Type"] = "application/json"
    _, uploaded = request_json(
        _query_url(
            f"{attachment_url}/file",
            {
                "table_name": "change_request",
                "table_sys_id": sys_id,
                "file_name": filename,
            },
        ),
        "POST",
        upload_headers,
        raw,
    )
    attachment = uploaded.get("result") if isinstance(uploaded, dict) else None
    if not isinstance(attachment, dict) or not attachment.get("sys_id"):
        raise IntegrationError("ServiceNow attachment upload returned an invalid response.")
    verified = find()
    if len(verified) != 1 or verified[0].get("sys_id") != attachment.get("sys_id"):
        raise IntegrationError("ServiceNow could not verify the evidence attachment.")
    return {
        "status": "uploaded",
        "sys_id": attachment.get("sys_id"),
        "filename": filename,
        "sha256": prepared["evidence"]["evidence_hash"],
    }


def push(
    instance_url: str,
    result: Mapping[str, Any],
    change_doc: Any,
    ticket_markdown: str | None,
    *,
    env: Mapping[str, str],
    headers: Mapping[str, str],
    request_json: Callable[..., tuple[int, dict[str, Any]]],
    mapping: str | Path | Mapping[str, Any] | None = None,
    change_reference: str | None = None,
    attach_evidence: bool = False,
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create or safely enrich one ServiceNow change_request."""

    instance_url = validate_instance_url(instance_url, env)
    prepared = prepare_payload(
        result,
        change_doc,
        ticket_markdown,
        mapping=mapping,
        source=source,
        env=env,
    )
    table_url = f"{instance_url}/api/now/v1/table/change_request"
    records = _find_record(table_url, headers, prepared, request_json, change_reference)
    if change_reference and not records:
        raise IntegrationError(
            f"ServiceNow change {change_reference!r} was not found; no record was created."
        )

    if records:
        current = records[0]
        sys_id = current.get("sys_id")
        if not isinstance(sys_id, str) or not _SYS_ID_RE.fullmatch(sys_id):
            raise IntegrationError("ServiceNow lookup returned an invalid sys_id.")
        if _material_update_needed(current, prepared["payload"]):
            _, data = request_json(f"{table_url}/{sys_id}", "PATCH", headers, prepared["payload"])
            record = data.get("result") if isinstance(data, dict) else None
            if not isinstance(record, dict):
                raise IntegrationError("ServiceNow update returned an invalid response.")
            action = "updated"
        else:
            action = "unchanged"
    else:
        _, data = request_json(table_url, "POST", headers, prepared["payload"])
        record = data.get("result") if isinstance(data, dict) else None
        sys_id = record.get("sys_id") if isinstance(record, dict) else None
        if not isinstance(sys_id, str) or not _SYS_ID_RE.fullmatch(sys_id):
            raise IntegrationError("ServiceNow create returned an invalid sys_id.")
        action = "created"

    verified = _verify_record(table_url, sys_id, headers, prepared["payload"], request_json)
    identity_records = _find_record(table_url, headers, prepared, request_json, change_reference)
    if len(identity_records) != 1 or identity_records[0].get("sys_id") != sys_id:
        raise IntegrationError(
            "ServiceNow post-write verification could not confirm a unique change identity."
        )
    attachment = {"status": "not_requested"}
    if attach_evidence:
        attachment = _attach_evidence(instance_url, sys_id, headers, prepared, request_json)

    return {
        "system": "servicenow",
        "action": action,
        "number": verified.get("number"),
        "sys_id": sys_id,
        "url": f"{instance_url}/nav_to.do?uri=change_request.do?sys_id={sys_id}",
        "verified": True,
        "correlation_id": prepared["correlation_id"],
        "evidence": attachment,
        "governance": "pre-change evidence only; CAB remains authoritative",
    }

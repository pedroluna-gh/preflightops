"""Optional, opt-in integrations that push a generated change ticket into
ServiceNow or Jira via their REST APIs.

This is the **live API** counterpart to :mod:`preflightops.ticket`. Where that
module only formats a copy/paste-ready Markdown summary and never touches the
network, this module can create or update a real change record in ServiceNow or
an issue in Jira.

Design rules (kept deliberately strict):

* **Strictly opt-in.** Nothing here runs unless the caller explicitly passes a
  ServiceNow instance URL or a Jira base URL (via the ``--servicenow`` /
  ``--jira`` CLI flags). When neither is supplied, PreflightOps makes no network
  calls and works fully offline.
* **Credentials come from the environment only.** No secret is ever accepted on
  the command line or hard-coded. The non-secret instance/base URL is the only
  value passed as an argument.
* **Standard library only.** HTTP is done with :mod:`urllib`; no extra runtime
  dependency is introduced.

The generated Markdown change summary (see :func:`ticket.generate_ticket_markdown`)
is reused verbatim as the body of the created/updated record, so the live record
carries the same risk rationale as the offline summary.
"""

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .integration_errors import IntegrationError
from .servicenow import (
    SERVICENOW_TOKEN_ENV,
    _short_description,
    correlation_id,
)
from .servicenow import (
    build_evidence as build_servicenow_evidence,
)
from .servicenow import (
    load_mapping as load_servicenow_mapping,
)
from .servicenow import (
    prepare_payload as prepare_servicenow_payload,
)
from .servicenow import (
    push as _push_servicenow,
)
from .servicenow import (
    validate_instance_url as validate_servicenow_instance_url,
)
from .ticket import generate_ticket_markdown

__all__ = [
    "IntegrationError",
    "SERVICENOW_TOKEN_ENV",
    "build_servicenow_evidence",
    "correlation_id",
    "load_servicenow_mapping",
    "prepare_servicenow_payload",
    "push_to_jira",
    "push_to_servicenow",
    "validate_servicenow_instance_url",
]

# Environment variables that supply credentials. These are read at call time and
# never logged or echoed back.
SERVICENOW_USER_ENV = "SERVICENOW_USER"
SERVICENOW_PASSWORD_ENV = "SERVICENOW_PASSWORD"

JIRA_EMAIL_ENV = "JIRA_EMAIL"
JIRA_API_TOKEN_ENV = "JIRA_API_TOKEN"
JIRA_PROJECT_ENV = "JIRA_PROJECT_KEY"
JIRA_ISSUE_TYPE_ENV = "JIRA_ISSUE_TYPE"

# Non-secret instance/base URLs. The CLI passes these as the ``--servicenow`` /
# ``--jira`` arguments; the Streamlit app, which has no command line, reads them
# from these environment variables instead. They are NOT credentials, but
# sourcing them from the environment keeps the whole integration opt-in and out
# of the UI as plain config.
SERVICENOW_INSTANCE_URL_ENV = "SERVICENOW_INSTANCE_URL"
JIRA_BASE_URL_ENV = "JIRA_BASE_URL"

# Default Jira issue type when JIRA_ISSUE_TYPE is not set.
DEFAULT_JIRA_ISSUE_TYPE = "Task"

# Network timeout (seconds) for every API call.
HTTP_TIMEOUT = 30

# ServiceNow short_description has a practical length cap; keep summaries short.
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_RETRYABLE_METHODS = {"GET", "HEAD", "PATCH", "PUT", "DELETE"}
_MAX_HTTP_ATTEMPTS = 3


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Allow redirects only when scheme, hostname, and port stay unchanged."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        old_origin = (old.scheme.lower(), old.hostname, old.port or 443)
        new_origin = (new.scheme.lower(), new.hostname, new.port or 443)
        if old_origin != new_origin:
            raise urllib.error.HTTPError(
                req.full_url,
                403,
                "cross-origin redirect refused",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _safe_http_detail(raw):
    """Return a bounded API error without reflecting arbitrary response data."""

    text = (raw or "").replace("\r", " ").replace("\n", " ").strip()
    try:
        parsed = json.loads(text)
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, dict):
            text = " ".join(
                str(error.get(key) or "").strip() for key in ("message", "detail")
            ).strip()
    except (json.JSONDecodeError, TypeError):
        pass
    return text[:500]


def _http_request(url, method, headers, body=None, timeout=HTTP_TIMEOUT):
    """Perform a JSON HTTP request and return ``(status_code, parsed_json)``.

    Raised :class:`IntegrationError` carries the HTTP status and response body so
    misconfiguration (bad URL, wrong credentials, unknown field) is actionable.
    """
    data = None
    if isinstance(body, (bytes, bytearray)):
        data = bytes(body)
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
    opener = urllib.request.build_opener(_SameOriginRedirectHandler())
    attempts = _MAX_HTTP_ATTEMPTS if method in _RETRYABLE_METHODS else 1
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                try:
                    parsed = json.loads(raw) if raw.strip() else {}
                except json.JSONDecodeError as exc:
                    raise IntegrationError(f"{method} {url} returned invalid JSON.") from exc
                if not isinstance(parsed, dict):
                    raise IntegrationError(f"{method} {url} returned an invalid response object.")
                return response.status, parsed
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRYABLE_STATUSES and attempt < attempts:
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                delay = int(retry_after) if str(retry_after).isdigit() else 2 ** (attempt - 1)
                time.sleep(min(delay, 10))
                continue
            detail = ""
            try:
                detail = _safe_http_detail(exc.read().decode("utf-8", "replace"))
            except Exception:  # pragma: no cover - defensive only
                detail = ""
            suffix = f" {detail}" if detail else ""
            raise IntegrationError(
                f"{method} {url} failed: HTTP {exc.code} {exc.reason}{suffix}"
            ) from exc
        except urllib.error.URLError as exc:
            if attempt < attempts:
                time.sleep(2 ** (attempt - 1))
                continue
            raise IntegrationError(f"{method} {url} failed: {exc.reason}") from exc
    raise IntegrationError(f"{method} {url} failed after retry attempts.")


def _basic_auth_header(username, secret):
    token = base64.b64encode(f"{username}:{secret}".encode()).decode("ascii")
    return f"Basic {token}"


# ---------------------------------------------------------------------------
# ServiceNow
# ---------------------------------------------------------------------------
def push_to_servicenow(
    instance_url,
    result,
    change_doc=None,
    ticket_markdown=None,
    env=None,
    *,
    mapping=None,
    change_reference=None,
    attach_evidence=False,
    source=None,
):
    """Create or update a ServiceNow ``change_request`` from the risk result.

    Parameters
    ----------
    instance_url : str
        The ServiceNow instance base URL, e.g. ``https://dev12345.service-now.com``.
        This is **not** a secret and is the only value passed as an argument.
    result, change_doc : dict
        The risk result and parsed change document (payload source).
    ticket_markdown : str, optional
        Pre-rendered change summary. Generated from ``result``/``change_doc`` when
        omitted, so the live record matches the offline summary.
    env : mapping, optional
        Environment lookup (defaults to ``os.environ``). Injected in tests.

    Returns
    -------
    dict
        ``{"system", "action", "number", "sys_id", "url"}`` describing the record.
    """
    env = os.environ if env is None else env
    instance_url = validate_servicenow_instance_url(instance_url, env)
    token = env.get(SERVICENOW_TOKEN_ENV)
    if token:
        authorization = f"Bearer {token}"
    else:
        user = env.get(SERVICENOW_USER_ENV)
        password = env.get(SERVICENOW_PASSWORD_ENV)
        if not user or not password:
            raise IntegrationError(
                f"ServiceNow integration requires {SERVICENOW_TOKEN_ENV}, or both "
                f"{SERVICENOW_USER_ENV} and {SERVICENOW_PASSWORD_ENV}."
            )
        authorization = _basic_auth_header(user, password)
    headers = {
        "Authorization": authorization,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    return _push_servicenow(
        instance_url,
        result,
        change_doc,
        ticket_markdown,
        env=env,
        headers=headers,
        request_json=_http_request,
        mapping=mapping,
        change_reference=change_reference,
        attach_evidence=attach_evidence,
        source=source,
    )


# ---------------------------------------------------------------------------
# Jira
# ---------------------------------------------------------------------------
def push_to_jira(base_url, result, change_doc=None, ticket_markdown=None, env=None):
    """Create or update a Jira issue from the risk result.

    Parameters
    ----------
    base_url : str
        The Jira base URL, e.g. ``https://example.atlassian.net``. Not a secret.
    result, change_doc : dict
        The risk result and parsed change document (payload source).
    ticket_markdown : str, optional
        Pre-rendered change summary; generated when omitted.
    env : mapping, optional
        Environment lookup (defaults to ``os.environ``). Injected in tests.

    Returns
    -------
    dict
        ``{"system", "action", "key", "url"}`` describing the issue.
    """
    env = os.environ if env is None else env
    base_url = (base_url or "").rstrip("/")
    if not base_url:
        raise IntegrationError("Jira base URL is required (e.g. https://example.atlassian.net).")

    email = env.get(JIRA_EMAIL_ENV)
    token = env.get(JIRA_API_TOKEN_ENV)
    project = env.get(JIRA_PROJECT_ENV)
    if not email or not token:
        raise IntegrationError(
            "Jira integration requires the "
            f"{JIRA_EMAIL_ENV} and {JIRA_API_TOKEN_ENV} environment variables."
        )
    if not project:
        raise IntegrationError(
            f"Jira integration requires the {JIRA_PROJECT_ENV} environment variable."
        )

    headers = {
        "Authorization": _basic_auth_header(email, token),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    if ticket_markdown is None:
        ticket_markdown = generate_ticket_markdown(result, change_doc)

    corr = correlation_id(result, change_doc)
    summary = _short_description(result, change_doc)
    issue_type = env.get(JIRA_ISSUE_TYPE_ENV) or DEFAULT_JIRA_ISSUE_TYPE

    # The correlation id is stored as a label so a re-run finds and updates the
    # same issue instead of creating a duplicate.
    jql = f'project = "{project}" AND labels = "{corr}" ORDER BY created DESC'
    search_query = urllib.parse.urlencode({"jql": jql, "maxResults": "1"})
    _, found = _http_request(f"{base_url}/rest/api/2/search?{search_query}", "GET", headers)
    issues = found.get("issues") or []

    if issues:
        key = issues[0].get("key")
        update_fields = {"summary": summary, "description": ticket_markdown}
        _http_request(
            f"{base_url}/rest/api/2/issue/{key}",
            "PUT",
            headers,
            {"fields": update_fields},
        )
        action = "updated"
    else:
        create_fields = {
            "project": {"key": project},
            "issuetype": {"name": issue_type},
            "summary": summary,
            "description": ticket_markdown,
            "labels": ["preflightops", corr],
        }
        _, data = _http_request(
            f"{base_url}/rest/api/2/issue", "POST", headers, {"fields": create_fields}
        )
        key = data.get("key")
        action = "created"

    return {
        "system": "jira",
        "action": action,
        "key": key,
        "url": f"{base_url}/browse/{key}" if key else base_url,
    }

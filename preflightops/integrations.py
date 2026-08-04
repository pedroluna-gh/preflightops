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
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .ticket import generate_ticket_markdown

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
_SHORT_DESCRIPTION_MAX = 160


class IntegrationError(Exception):
    """Raised when an opt-in integration is misconfigured or its API call fails.

    The CLI catches this, prints the message to stderr, and exits non-zero. It is
    deliberately distinct from input/validation errors so the offline paths are
    never affected by an integration problem.
    """


def _change_section(change_doc):
    """Return the inner ``change`` mapping from a parsed change document."""
    if isinstance(change_doc, dict):
        nested = change_doc.get("change")
        if isinstance(nested, dict):
            return nested
    return {}


def correlation_id(result, change_doc=None):
    """Return a deterministic identifier for this change.

    The same service + environment + change title always produces the same id, so
    a second run updates the existing record instead of creating a duplicate.
    """
    change = _change_section(change_doc)
    title = (change.get("title") or "").strip()
    service = (result.get("service") or "").strip()
    environment = (result.get("environment") or "").strip()
    basis = "|".join([service, environment, title]).lower()
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return f"preflightops-{digest}"


def _short_description(result, change_doc=None):
    """Build a concise one-line summary for the record title."""
    change = _change_section(change_doc)
    title = (change.get("title") or "").strip() or "Production change"
    service = (result.get("service") or "").strip() or "unknown service"
    level = (result.get("risk_level") or "").strip() or "UNKNOWN"
    summary = f"[{level}] {title} ({service})"
    if len(summary) > _SHORT_DESCRIPTION_MAX:
        summary = summary[: _SHORT_DESCRIPTION_MAX - 1].rstrip() + "\u2026"
    return summary


def _http_request(url, method, headers, body=None, timeout=HTTP_TIMEOUT):
    """Perform a JSON HTTP request and return ``(status_code, parsed_json)``.

    Raised :class:`IntegrationError` carries the HTTP status and response body so
    misconfiguration (bad URL, wrong credentials, unknown field) is actionable.
    """
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw) if raw.strip() else {}
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # pragma: no cover - defensive only
            detail = ""
        raise IntegrationError(
            f"{method} {url} failed: HTTP {exc.code} {exc.reason} {detail}".strip()
        ) from exc
    except urllib.error.URLError as exc:
        raise IntegrationError(f"{method} {url} failed: {exc.reason}") from exc


def _basic_auth_header(username, secret):
    token = base64.b64encode(f"{username}:{secret}".encode()).decode("ascii")
    return f"Basic {token}"


# ---------------------------------------------------------------------------
# ServiceNow
# ---------------------------------------------------------------------------
def push_to_servicenow(instance_url, result, change_doc=None, ticket_markdown=None, env=None):
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
    instance_url = (instance_url or "").rstrip("/")
    if not instance_url:
        raise IntegrationError(
            "ServiceNow instance URL is required (e.g. https://dev12345.service-now.com)."
        )

    user = env.get(SERVICENOW_USER_ENV)
    password = env.get(SERVICENOW_PASSWORD_ENV)
    if not user or not password:
        raise IntegrationError(
            "ServiceNow integration requires the "
            f"{SERVICENOW_USER_ENV} and {SERVICENOW_PASSWORD_ENV} "
            "environment variables."
        )

    headers = {
        "Authorization": _basic_auth_header(user, password),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    if ticket_markdown is None:
        ticket_markdown = generate_ticket_markdown(result, change_doc)

    corr = correlation_id(result, change_doc)
    payload = {
        "short_description": _short_description(result, change_doc),
        "description": ticket_markdown,
        "correlation_id": corr,
    }

    table_url = f"{instance_url}/api/now/table/change_request"
    query = urllib.parse.urlencode(
        {"sysparm_query": f"correlation_id={corr}", "sysparm_limit": "1"}
    )
    _, found = _http_request(f"{table_url}?{query}", "GET", headers)
    records = found.get("result") or []

    if records:
        sys_id = records[0].get("sys_id")
        _, data = _http_request(f"{table_url}/{sys_id}", "PATCH", headers, payload)
        action = "updated"
    else:
        _, data = _http_request(table_url, "POST", headers, payload)
        action = "created"

    record = data.get("result") or {}
    sys_id = record.get("sys_id")
    return {
        "system": "servicenow",
        "action": action,
        "number": record.get("number"),
        "sys_id": sys_id,
        "url": (
            f"{instance_url}/nav_to.do?uri=change_request.do?sys_id={sys_id}"
            if sys_id
            else instance_url
        ),
    }


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

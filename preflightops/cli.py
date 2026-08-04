"""Command-line interface for PreflightOps.

Example
-------
    python -m preflightops.cli \\
        --services examples/services-critical-risk.yaml \\
        --change examples/change-critical-risk.yaml \\
        --terraform examples/terraform-critical.txt \\
        --k8s examples/k8s-risk.yaml \\
        --output report.md \\
        --json-output report.json

Exit codes
----------
    1  if the assessed risk level is CRITICAL
    0  otherwise
"""

import argparse
import sys

import yaml

from ._version import __version__
from .risk_engine import assess_risk
from .report import generate_markdown_report, generate_json_report
from .ticket import generate_ticket_markdown, load_template_file
from .integrations import (
    push_to_servicenow,
    push_to_jira,
    correlation_id,
    IntegrationError,
)


def _confirm_push(system, target, corr, assume_yes):
    """Print what a live push will do and ask for an explicit confirmation.

    Returns ``True`` to proceed with the network call, ``False`` to skip it.

    A live ``--servicenow`` / ``--jira`` push can create or update a real
    production change record, so a single typo or copy-pasted command should not
    silently reach a change-management system. This mirrors the web app, which
    requires an explicit confirmation before its "Send to ..." buttons fire.

    The ``--yes`` / ``--assume-yes`` flag skips the prompt for CI/automation. If
    there is no interactive terminal and ``--yes`` was not passed, the push is
    skipped (no API call) so unattended runs fail safe.
    """
    print(f"About to push a change record to {system}:")
    print(f"  Target:         {target}")
    print(f"  Correlation id: {corr}")
    print("  A matching record is updated if it exists, otherwise a new one is created.")
    if assume_yes:
        print("  Proceeding without prompt (--yes).")
        return True
    if not sys.stdin.isatty():
        print(
            f"Skipping {system} push: no interactive terminal and --yes was not "
            "given. No API call was made.",
            file=sys.stderr,
        )
        return False
    try:
        answer = input(f"  Proceed with {system} push? [y/N] ").strip().lower()
    except EOFError:
        answer = ""
    if answer in ("y", "yes"):
        return True
    print(f"Skipping {system} push (not confirmed). No API call was made.")
    return False


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _load_text(path):
    if not path:
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="preflightops",
        description="Pre-deployment risk assessment for SRE and Platform teams.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("--services", required=True, help="Path to the service catalog YAML file")
    parser.add_argument("--change", required=True, help="Path to the change request YAML file")
    parser.add_argument("--terraform", default=None, help="Optional path to a Terraform plan/diff text file")
    parser.add_argument("--k8s", default=None, help="Optional path to a Kubernetes manifest YAML file")
    parser.add_argument("--output", default="report.md", help="Where to write the Markdown report")
    parser.add_argument(
        "--json-output",
        default=None,
        help="Optional path to also write the machine-readable JSON report",
    )
    parser.add_argument(
        "--ticket-output",
        default=None,
        help=(
            "Optional path to write a copy/paste-ready ServiceNow/Jira change "
            "ticket summary (Markdown). Not a real ServiceNow/Jira API integration."
        ),
    )
    parser.add_argument(
        "--ticket-template",
        default=None,
        help=(
            "Optional path to a YAML/JSON template that customizes the change "
            "ticket layout (section order, headings, approval and "
            "deployment-window wording). Defaults to the built-in layout."
        ),
    )
    parser.add_argument(
        "--servicenow",
        default=None,
        metavar="INSTANCE_URL",
        help=(
            "Opt-in: create/update a ServiceNow change_request from the ticket "
            "summary. Pass the instance URL (e.g. https://dev123.service-now.com). "
            "Credentials come from the SERVICENOW_USER / SERVICENOW_PASSWORD "
            "environment variables only."
        ),
    )
    parser.add_argument(
        "--jira",
        default=None,
        metavar="BASE_URL",
        help=(
            "Opt-in: create/update a Jira issue from the ticket summary. Pass the "
            "base URL (e.g. https://example.atlassian.net). Credentials come from "
            "the JIRA_EMAIL / JIRA_API_TOKEN / JIRA_PROJECT_KEY environment "
            "variables only."
        ),
    )
    parser.add_argument(
        "--yes",
        "--assume-yes",
        dest="assume_yes",
        action="store_true",
        help=(
            "Skip the interactive confirmation before a live --servicenow / "
            "--jira push. Use in CI/automation where no terminal is attached."
        ),
    )

    args = parser.parse_args(argv)

    try:
        services = _load_yaml(args.services)
        change = _load_yaml(args.change)
        terraform_text = _load_text(args.terraform)
        k8s_text = _load_text(args.k8s)
    except (OSError, yaml.YAMLError) as exc:
        print(f"Error loading input files: {exc}", file=sys.stderr)
        return 2

    try:
        result = assess_risk(services, change, terraform_text, k8s_text)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    report = generate_markdown_report(result)

    try:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(report)
    except OSError as exc:
        print(f"Error writing report: {exc}", file=sys.stderr)
        return 2

    if args.json_output:
        json_report = generate_json_report(result)
        try:
            with open(args.json_output, "w", encoding="utf-8") as handle:
                handle.write(json_report)
        except OSError as exc:
            print(f"Error writing JSON report: {exc}", file=sys.stderr)
            return 2

    # The same change summary backs the offline file and the opt-in API push.
    # A custom --ticket-template (when provided) shapes that summary everywhere.
    ticket_markdown = None
    if args.ticket_output or args.servicenow or args.jira:
        try:
            ticket_template = (
                load_template_file(args.ticket_template) if args.ticket_template else None
            )
        except (OSError, yaml.YAMLError, ValueError) as exc:
            print(f"Error loading ticket template: {exc}", file=sys.stderr)
            return 2
        ticket_markdown = generate_ticket_markdown(result, change, ticket_template)

    if args.ticket_output:
        try:
            with open(args.ticket_output, "w", encoding="utf-8") as handle:
                handle.write(ticket_markdown)
        except OSError as exc:
            print(f"Error writing ticket summary: {exc}", file=sys.stderr)
            return 2

    # Opt-in live integrations. These only run when the caller supplies an
    # instance/base URL; otherwise no network call is ever made. Each push is
    # gated behind an explicit confirmation (or --yes) so a typo never silently
    # creates/updates a real production change record.
    integration_results = []
    corr = correlation_id(result, change) if (args.servicenow or args.jira) else None
    if args.servicenow:
        if _confirm_push("ServiceNow", args.servicenow, corr, args.assume_yes):
            try:
                integration_results.append(
                    push_to_servicenow(args.servicenow, result, change, ticket_markdown)
                )
            except IntegrationError as exc:
                print(f"ServiceNow integration error: {exc}", file=sys.stderr)
                return 2
    if args.jira:
        if _confirm_push("Jira", args.jira, corr, args.assume_yes):
            try:
                integration_results.append(
                    push_to_jira(args.jira, result, change, ticket_markdown)
                )
            except IntegrationError as exc:
                print(f"Jira integration error: {exc}", file=sys.stderr)
                return 2

    print(f"Service:     {result['service']}")
    print(f"Environment: {result['environment']}")
    print(f"Risk Score:  {result['risk_score']}/100")
    print(f"Risk Level:  {result['risk_level']}")
    print(f"Report written to: {args.output}")
    if args.json_output:
        print(f"JSON report written to: {args.json_output}")
    if args.ticket_output:
        print(f"Change ticket summary written to {args.ticket_output}")
    for info in integration_results:
        system = info["system"].replace("servicenow", "ServiceNow").replace("jira", "Jira")
        reference = info.get("number") or info.get("key") or "(unknown)"
        print(f"{system} change record {info['action']}: {reference} ({info['url']})")

    return 1 if result["risk_level"] == "CRITICAL" else 0


if __name__ == "__main__":
    sys.exit(main())

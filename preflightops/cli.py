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
import json
import sys
from pathlib import Path

import yaml

from ._version import __version__
from .auditable_report import (
    AuditableReportConfig,
    AuditableReportError,
    build_auditable_report_v1,
    render_assessment_markdown_v1,
    render_pr_summary_v1,
    render_ticket_summary_v1,
    serialize_auditable_report_v1,
)
from .changed_files import (
    classify_changed_files,
    load_auto_scanner_inputs,
    load_changed_files,
)
from .evidence import evidence_cli
from .integrations import (
    IntegrationError,
    correlation_id,
    load_servicenow_mapping,
    prepare_servicenow_payload,
    push_to_jira,
    push_to_servicenow,
    validate_servicenow_instance_url,
)
from .policy import load_policy_pack
from .policy_governance import (
    apply_verified_waivers,
    governance_cli,
    load_governance_document,
    read_governance_key,
    validate_waiver,
    waiver_cli,
)
from .report import (
    generate_github_comment,
    generate_html_report,
    generate_json_report,
    generate_markdown_report,
)
from .risk_engine import assess_risk
from .ticket import generate_ticket_markdown, load_template_file


def _confirm_push(system, target, corr, assume_yes, change_reference=None):
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
    if change_reference:
        print(f"  Existing change: {change_reference}")
        print("  The existing record is enriched; a missing record fails closed.")
    else:
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
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _load_text(path):
    if not path:
        return ""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _load_terraform_json(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as handle:
        # Keep the raw representation so the Terraform parser can require the
        # explicit format version and enforce its byte budget before decoding.
        return handle.read()


def _render_assessment_report_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="preflightops report render",
        description="Render deterministic, offline outputs from Assessment Contract v1.",
    )
    parser.add_argument("--assessment", required=True, help="Assessment Contract v1 JSON path.")
    parser.add_argument("--json-output", help="Explicit Assessment Report v1 JSON path.")
    parser.add_argument("--markdown-output", help="Explicit full Markdown report path.")
    parser.add_argument("--pr-summary-output", help="Explicit compact PR summary path.")
    parser.add_argument("--ticket-summary-output", help="Explicit compact ticket summary path.")
    parser.add_argument(
        "--full-report-url",
        help="Optional safe HTTPS artifact URL for compact summaries; never fetched.",
    )
    parser.add_argument(
        "--without-automation-details",
        action="store_true",
        help="Omit the Automation Details block from human output.",
    )
    parser.add_argument("--max-text-length", type=int, default=320)
    parser.add_argument("--top-blockers-limit", type=int, default=5)
    parser.add_argument("--next-actions-limit", type=int, default=8)
    parser.add_argument("--pr-summary-max-characters", type=int, default=3500)
    parser.add_argument("--ticket-summary-max-characters", type=int, default=8000)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly allow replacement of requested local output files.",
    )
    args = parser.parse_args(argv)

    requested = {
        "json": args.json_output,
        "markdown": args.markdown_output,
        "pr": args.pr_summary_output,
        "ticket": args.ticket_summary_output,
    }
    destinations = {name: Path(value) for name, value in requested.items() if value}
    if not destinations:
        parser.error("at least one explicit output path is required")
    resolved = [str(path.resolve()) for path in destinations.values()]
    if len(resolved) != len(set(resolved)):
        parser.error("output paths must be unique")
    if not args.overwrite:
        existing = [str(path) for path in destinations.values() if path.exists()]
        if existing:
            print(
                "Report error: output already exists; pass --overwrite to replace it: "
                + ", ".join(existing),
                file=sys.stderr,
            )
            return 2

    try:
        with open(args.assessment, encoding="utf-8") as handle:
            assessment = json.load(handle)
        if not isinstance(assessment, dict):
            raise AuditableReportError("Assessment Contract v1 must be a JSON object.")
        config = AuditableReportConfig(
            include_automation_details=not args.without_automation_details,
            max_text_length=args.max_text_length,
            top_blockers_limit=args.top_blockers_limit,
            next_actions_limit=args.next_actions_limit,
            pr_summary_max_characters=args.pr_summary_max_characters,
            ticket_summary_max_characters=args.ticket_summary_max_characters,
        )
        report = build_auditable_report_v1(assessment, config)
        documents = {
            "json": serialize_auditable_report_v1(report).decode("utf-8"),
            "markdown": render_assessment_markdown_v1(report),
            "pr": render_pr_summary_v1(report, args.full_report_url),
            "ticket": render_ticket_summary_v1(report, args.full_report_url),
        }
        mode = "w" if args.overwrite else "x"
        for name, path in destinations.items():
            with path.open(mode, encoding="utf-8", newline="\n") as handle:
                handle.write(documents[name])
    except (AuditableReportError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Report error: {exc}", file=sys.stderr)
        return 2

    for name, path in destinations.items():
        print(f"Assessment report {name} written to: {path}")
    return 0


def main(argv=None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv[:1] == ["evidence"]:
        return evidence_cli(effective_argv[1:])
    if effective_argv[:1] == ["policy"]:
        return governance_cli(effective_argv[1:])
    if effective_argv[:1] == ["waiver"]:
        return waiver_cli(effective_argv[1:])
    if effective_argv[:2] == ["report", "render"]:
        return _render_assessment_report_cli(effective_argv[2:])

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
    parser.add_argument(
        "--terraform", default=None, help="Optional path to a Terraform plan/diff text file"
    )
    parser.add_argument(
        "--terraform-json",
        default=None,
        help="Optional path to structured output from 'terraform show -json'.",
    )
    parser.add_argument(
        "--k8s", default=None, help="Optional path to a Kubernetes manifest YAML file"
    )
    parser.add_argument(
        "--policy",
        default=None,
        metavar="PACK_OR_FILE",
        help=(
            "Built-in policy pack (saas, fintech, ecommerce, healthcare, "
            "critical-platform, startup) or a versioned policy YAML file."
        ),
    )
    parser.add_argument(
        "--policy-public-key",
        default=None,
        metavar="PEM_OR_PATH",
        help=(
            "Trusted Ed25519 public-key path for an active Policy Bundle v2. "
            "May also be supplied by PREFLIGHTOPS_POLICY_PUBLIC_KEY."
        ),
    )
    parser.add_argument(
        "--waiver",
        action="append",
        default=[],
        metavar="WAIVER_YAML",
        help=(
            "Optional signed Waiver Contract v1. Repeat for multiple waivers. "
            "Verified waivers annotate risk but never reduce the score or approve a change."
        ),
    )
    parser.add_argument(
        "--waiver-public-key",
        default=None,
        metavar="PEM_OR_PATH",
        help=(
            "Trusted Ed25519 waiver public-key path; may also be supplied by "
            "PREFLIGHTOPS_WAIVER_PUBLIC_KEY."
        ),
    )
    parser.add_argument(
        "--monitors",
        default=None,
        metavar="INVENTORY_YAML",
        help="Optional offline monitor inventory for Datadog/Grafana/Prometheus/Zabbix/GCP validation.",
    )
    parser.add_argument(
        "--changed-files",
        default=None,
        metavar="MANIFEST",
        help=(
            "Optional newline or JSON PR file manifest. Infers scanner scope and "
            "automatically loads unambiguous Terraform JSON/Kubernetes inputs."
        ),
    )
    parser.add_argument(
        "--repository-root",
        default=".",
        help="Checkout root used to resolve paths from --changed-files (default: current directory).",
    )
    parser.add_argument("--output", default="report.md", help="Where to write the Markdown report")
    parser.add_argument(
        "--json-output",
        default=None,
        help="Optional path to also write the machine-readable JSON report",
    )
    parser.add_argument(
        "--html-output",
        default=None,
        help="Optional path to write a dependency-free static HTML report.",
    )
    parser.add_argument(
        "--github-comment-output",
        default=None,
        help="Optional path to write a compact GitHub pull-request comment.",
    )
    parser.add_argument(
        "--full-report-url",
        default=None,
        help="Optional HTTP(S) workflow/artifact URL included in HTML and GitHub reports.",
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
        "--servicenow-mapping",
        default=None,
        metavar="YAML_OR_JSON",
        help=(
            "Optional versioned field mapping. Only pre-change evidence fields and "
            "u_ custom fields are allowed; workflow and approval fields are refused."
        ),
    )
    parser.add_argument(
        "--servicenow-change",
        default=None,
        metavar="NUMBER_OR_SYS_ID",
        help=(
            "Enrich this existing ServiceNow Change number/sys_id. When supplied, a "
            "missing record fails closed and no new Change is created."
        ),
    )
    parser.add_argument(
        "--servicenow-attach-evidence",
        action="store_true",
        help=(
            "Attach a versioned, secret-scrubbed JSON evidence package. Identical "
            "evidence is deduplicated by SHA-256."
        ),
    )
    parser.add_argument(
        "--servicenow-dry-run",
        action="store_true",
        help="Prepare and validate the ServiceNow payload without credentials or network access.",
    )
    parser.add_argument(
        "--servicenow-preview-output",
        default="servicenow-preview.json",
        metavar="PATH",
        help="Dry-run payload output (default: servicenow-preview.json).",
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

    args = parser.parse_args(effective_argv)

    try:
        services = _load_yaml(args.services)
        change = _load_yaml(args.change)
        changed_scope = None
        auto_inputs: dict = {
            "terraform_json": None,
            "kubernetes_text": "",
            "terraform_json_files": [],
            "kubernetes_files": [],
        }
        if args.changed_files:
            changed_paths = load_changed_files(args.changed_files)
            changed_scope = classify_changed_files(changed_paths, args.repository_root)
            auto_inputs = load_auto_scanner_inputs(changed_scope, args.repository_root)

        terraform_text = _load_text(args.terraform)
        terraform_json = _load_terraform_json(args.terraform_json)
        if terraform_json is None:
            terraform_json = auto_inputs["terraform_json"]
        k8s_text = _load_text(args.k8s)
        if not k8s_text:
            k8s_text = auto_inputs["kubernetes_text"]
        monitor_inventory = _load_yaml(args.monitors) if args.monitors else None
        policy = load_policy_pack(args.policy, public_key=args.policy_public_key)
    except (OSError, yaml.YAMLError, json.JSONDecodeError, ValueError) as exc:
        print(f"Error loading input files: {exc}", file=sys.stderr)
        return 2

    try:
        result = assess_risk(
            services,
            change,
            terraform_text,
            k8s_text,
            terraform_json=terraform_json,
            policy=policy,
            monitor_inventory=monitor_inventory,
        )
        if args.waiver:
            waiver_key = read_governance_key(
                args.waiver_public_key, "PREFLIGHTOPS_WAIVER_PUBLIC_KEY"
            )
            waiver_context = {
                "service": str(result.get("service", "")),
                "environment": str(result.get("environment", "")),
                "change_class": str(
                    (change.get("change") or {}).get("change_class")
                    or (change.get("change") or {}).get("classification")
                    or "normal"
                ),
                "change_type": str(result.get("change_type", "")),
            }
            verified_waivers = [
                validate_waiver(
                    load_governance_document(path),
                    public_key=waiver_key,
                    policy_digest=str(result["policy_pack"]["digest"]),
                    context=waiver_context,
                )
                for path in args.waiver
            ]
            result = apply_verified_waivers(result, verified_waivers)
        if changed_scope is not None:
            changed_scope["selected_inputs"] = {
                "terraform_text": [args.terraform] if args.terraform else [],
                "terraform_json": (
                    [args.terraform_json]
                    if args.terraform_json
                    else auto_inputs["terraform_json_files"]
                ),
                "kubernetes": [args.k8s] if args.k8s else auto_inputs["kubernetes_files"],
            }
            result["change_scope"] = changed_scope
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

    if args.html_output:
        html_report = generate_html_report(result, args.full_report_url)
        try:
            with open(args.html_output, "w", encoding="utf-8") as handle:
                handle.write(html_report)
        except OSError as exc:
            print(f"Error writing HTML report: {exc}", file=sys.stderr)
            return 2

    if args.github_comment_output:
        github_comment = generate_github_comment(result, args.full_report_url)
        try:
            with open(args.github_comment_output, "w", encoding="utf-8") as handle:
                handle.write(github_comment)
        except OSError as exc:
            print(f"Error writing GitHub comment: {exc}", file=sys.stderr)
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

    servicenow_mapping = None
    if args.servicenow and args.servicenow_mapping:
        try:
            servicenow_mapping = load_servicenow_mapping(args.servicenow_mapping)
        except IntegrationError as exc:
            print(f"ServiceNow integration error: {exc}", file=sys.stderr)
            return 2

    if args.ticket_output:
        assert ticket_markdown is not None
        try:
            with open(args.ticket_output, "w", encoding="utf-8") as handle:
                handle.write(ticket_markdown)
        except OSError as exc:
            print(f"Error writing ticket summary: {exc}", file=sys.stderr)
            return 2

    if args.servicenow_dry_run and not args.servicenow:
        print(
            "ServiceNow integration error: --servicenow-dry-run requires --servicenow.",
            file=sys.stderr,
        )
        return 2

    if args.servicenow_dry_run:
        assert ticket_markdown is not None
        try:
            target = validate_servicenow_instance_url(args.servicenow)
            prepared = prepare_servicenow_payload(
                result,
                change,
                ticket_markdown,
                mapping=servicenow_mapping,
            )
            preview = {
                "mode": "enrich_existing" if args.servicenow_change else "upsert",
                "target": target,
                "change_reference": args.servicenow_change,
                "attach_evidence": args.servicenow_attach_evidence,
                **prepared,
            }
            with open(args.servicenow_preview_output, "w", encoding="utf-8") as handle:
                json.dump(preview, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
        except (IntegrationError, OSError) as exc:
            print(f"ServiceNow integration error: {exc}", file=sys.stderr)
            return 2
        print(
            f"ServiceNow dry run written to: {args.servicenow_preview_output}. "
            "No credentials were read and no API call was made."
        )

    # Opt-in live integrations. These only run when the caller supplies an
    # instance/base URL; otherwise no network call is ever made. Each push is
    # gated behind an explicit confirmation (or --yes) so a typo never silently
    # creates/updates a real production change record.
    integration_results = []
    corr = correlation_id(result, change) if (args.servicenow or args.jira) else None
    if args.servicenow and not args.servicenow_dry_run:
        if _confirm_push(
            "ServiceNow",
            args.servicenow,
            corr,
            args.assume_yes,
            args.servicenow_change,
        ):
            try:
                integration_results.append(
                    push_to_servicenow(
                        args.servicenow,
                        result,
                        change,
                        ticket_markdown,
                        **(
                            {"mapping": servicenow_mapping}
                            if servicenow_mapping is not None
                            else {}
                        ),
                        **(
                            {"change_reference": args.servicenow_change}
                            if args.servicenow_change
                            else {}
                        ),
                        **({"attach_evidence": True} if args.servicenow_attach_evidence else {}),
                    )
                )
            except IntegrationError as exc:
                print(f"ServiceNow integration error: {exc}", file=sys.stderr)
                return 2
    if args.jira:
        if _confirm_push("Jira", args.jira, corr, args.assume_yes):
            try:
                integration_results.append(push_to_jira(args.jira, result, change, ticket_markdown))
            except IntegrationError as exc:
                print(f"Jira integration error: {exc}", file=sys.stderr)
                return 2

    print(f"Service:     {result['service']}")
    print(f"Environment: {result['environment']}")
    print(f"Risk Score:  {result['risk_score']}/100")
    print(f"Risk Level:  {result['risk_level']}")
    print(f"Policy Pack: {result['policy_pack']['name']}")
    print(f"Report written to: {args.output}")
    if args.json_output:
        print(f"JSON report written to: {args.json_output}")
    if args.html_output:
        print(f"HTML report written to: {args.html_output}")
    if args.github_comment_output:
        print(f"GitHub comment written to: {args.github_comment_output}")
    if changed_scope is not None:
        scanners = ", ".join(changed_scope["scanners"]) or "none"
        print(f"Changed-file scanner scope: {scanners}")
    if args.ticket_output:
        print(f"Change ticket summary written to {args.ticket_output}")
    for info in integration_results:
        system = info["system"].replace("servicenow", "ServiceNow").replace("jira", "Jira")
        reference = info.get("number") or info.get("key") or "(unknown)"
        print(f"{system} change record {info['action']}: {reference} ({info['url']})")

    return 1 if result["risk_level"] == "CRITICAL" else 0


if __name__ == "__main__":
    sys.exit(main())

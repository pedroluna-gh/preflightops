"""Safe pull-request changed-file discovery and scanner-scope inference."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yaml

from .terraform_plan import parse_terraform_plan_json

KUBERNETES_KINDS = {
    "ConfigMap",
    "CronJob",
    "DaemonSet",
    "Deployment",
    "Ingress",
    "Job",
    "NetworkPolicy",
    "Pod",
    "Secret",
    "Service",
    "StatefulSet",
}
SCANNER_ORDER = ["terraform", "kubernetes", "service-catalog", "change-request"]


def load_changed_files(path: str | Path) -> list[str]:
    """Load filenames from newline text, a JSON list, or GitHub API JSON."""
    raw = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return [line.strip() for line in raw.splitlines() if line.strip()]

    if isinstance(payload, dict):
        payload = payload.get("files", [])
    if not isinstance(payload, list):
        raise ValueError(
            "Changed-files input must be a JSON list/object or newline-delimited text."
        )

    filenames = []
    for item in payload:
        if isinstance(item, str):
            filenames.append(item)
        elif isinstance(item, dict) and isinstance(item.get("filename"), str):
            filenames.append(item["filename"])
    return filenames


def _safe_workspace_file(root: Path, filename: str) -> Path | None:
    """Resolve a PR filename without allowing traversal outside the checkout."""
    candidate = (root / filename).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _looks_like_kubernetes_yaml(root: Path | None, filename: str) -> bool:
    path = PurePosixPath(filename.replace("\\", "/"))
    lower = str(path).lower()
    if path.suffix.lower() not in {".yaml", ".yml"}:
        return False
    path_hint = any(
        hint in f"/{lower}"
        for hint in ("/k8s/", "/kubernetes/", "/manifests/", "/helm/", "/templates/")
    )
    if root is None:
        return path_hint
    local = _safe_workspace_file(root, filename)
    if local is None:
        return path_hint
    try:
        documents = yaml.safe_load_all(local.read_text(encoding="utf-8"))
        return any(
            isinstance(document, dict)
            and (
                document.get("kind") in KUBERNETES_KINDS
                or (document.get("kind") == "List" and isinstance(document.get("items"), list))
            )
            for document in documents
        )
    except (OSError, UnicodeError, yaml.YAMLError):
        return path_hint


def _looks_like_terraform_json_plan(root: Path | None, filename: str) -> bool:
    lower = filename.lower()
    name_hint = lower.endswith((".tfplan.json", "tfplan.json", "terraform-plan.json"))
    if root is None:
        return name_hint
    local = _safe_workspace_file(root, filename)
    if local is None or local.suffix.lower() != ".json":
        return name_hint
    try:
        payload = json.loads(local.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return name_hint
    return isinstance(payload, dict) and any(
        key in payload for key in ("resource_changes", "planned_values", "prior_state")
    )


def classify_changed_files(
    filenames: Iterable[str], repository_root: str | Path | None = None
) -> dict:
    """Classify PR filenames and infer relevant scanners and usable inputs."""
    root = Path(repository_root).resolve() if repository_root is not None else None
    normalized = list(dict.fromkeys(str(name).strip() for name in filenames if str(name).strip()))
    categories: dict[str, list[str]] = {
        "terraform": [],
        "kubernetes": [],
        "service_catalog": [],
        "change_request": [],
        "other": [],
    }
    terraform_json_candidates: list[str] = []
    kubernetes_candidates: list[str] = []

    for filename in normalized:
        posix = filename.replace("\\", "/")
        path = PurePosixPath(posix)
        lower = posix.lower()
        basename = path.name.lower()
        matched = False

        terraform_related = (
            lower.endswith((".tf", ".tf.json", ".tfplan", ".tfplan.json"))
            or basename
            in {"tfplan.json", "tfplan.txt", "terraform-plan.json", "terraform-plan.txt"}
            or "/terraform/" in f"/{lower}"
        )
        if terraform_related:
            categories["terraform"].append(filename)
            matched = True
            if _looks_like_terraform_json_plan(root, filename):
                terraform_json_candidates.append(filename)

        if _looks_like_kubernetes_yaml(root, filename):
            categories["kubernetes"].append(filename)
            kubernetes_candidates.append(filename)
            matched = True

        if basename in {
            "services.yaml",
            "services.yml",
            "service-catalog.yaml",
            "service-catalog.yml",
        }:
            categories["service_catalog"].append(filename)
            matched = True
        if basename in {"change.yaml", "change.yml", "change-request.yaml", "change-request.yml"}:
            categories["change_request"].append(filename)
            matched = True
        if not matched:
            categories["other"].append(filename)

    scanners = []
    if categories["terraform"]:
        scanners.append("terraform")
    if categories["kubernetes"]:
        scanners.append("kubernetes")
    if categories["service_catalog"]:
        scanners.append("service-catalog")
    if categories["change_request"]:
        scanners.append("change-request")
    scanners.sort(key=SCANNER_ORDER.index)

    warnings = []
    if categories["terraform"] and not terraform_json_candidates:
        warnings.append(
            "Terraform changed, but no structured plan is available; generate "
            "'terraform show -json' for resource-level risk evidence."
        )
    return {
        "changed_file_count": len(normalized),
        "scanners": scanners,
        "categories": categories,
        "auto_inputs": {
            "terraform_json_candidates": terraform_json_candidates,
            "kubernetes_manifest_candidates": kubernetes_candidates,
        },
        "warnings": warnings,
    }


def load_auto_scanner_inputs(scope: dict, repository_root: str | Path) -> dict:
    """Load unambiguous, safe scanner inputs discovered in a checkout."""
    root = Path(repository_root).resolve()
    auto_inputs = scope.get("auto_inputs", {})
    terraform_json = None
    terraform_candidates = [
        path
        for name in auto_inputs.get("terraform_json_candidates", [])
        if (path := _safe_workspace_file(root, name)) is not None
    ]
    if len(terraform_candidates) == 1:
        raw_plan = terraform_candidates[0].read_text(encoding="utf-8")
        parse_terraform_plan_json(raw_plan)
        terraform_json = json.loads(raw_plan)
    elif len(terraform_candidates) > 1:
        scope.setdefault("warnings", []).append(
            "Multiple Terraform JSON plans changed; pass --terraform-json explicitly."
        )

    kubernetes_paths = [
        path
        for name in auto_inputs.get("kubernetes_manifest_candidates", [])
        if (path := _safe_workspace_file(root, name)) is not None
    ]
    kubernetes_text = "\n---\n".join(path.read_text(encoding="utf-8") for path in kubernetes_paths)
    return {
        "terraform_json": terraform_json,
        "kubernetes_text": kubernetes_text,
        "terraform_json_files": [
            str(path.relative_to(root)).replace("\\", "/") for path in terraform_candidates[:1]
        ],
        "kubernetes_files": [
            str(path.relative_to(root)).replace("\\", "/") for path in kubernetes_paths
        ],
    }


def _event_pull_request_number(event_path: str | Path) -> int | None:
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    number = event.get("number")
    if not isinstance(number, int):
        pull_request = event.get("pull_request", {})
        number = pull_request.get("number") if isinstance(pull_request, dict) else None
    return number if isinstance(number, int) and number > 0 else None


def fetch_pull_request_files(
    *,
    api_url: str,
    repository: str,
    pull_request: int,
    token: str = "",
    per_page: int = 100,
    max_pages: int = 30,
) -> list[dict]:
    """Fetch a bounded, metadata-only PR file list from the GitHub REST API."""
    if "/" not in repository or not api_url.startswith("https://"):
        raise ValueError("A valid HTTPS GitHub API URL and owner/repository are required.")
    files: list[dict] = []
    for page in range(1, max_pages + 1):
        query = urlencode({"per_page": per_page, "page": page})
        url = f"{api_url.rstrip('/')}/repos/{repository}/pulls/{pull_request}/files?{query}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "preflightops-changed-files",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(url, headers=headers)
        with urlopen(request, timeout=15) as response:  # noqa: S310 - validated HTTPS host input
            payload = json.load(response)
        if not isinstance(payload, list):
            raise ValueError("GitHub returned an invalid pull-request files response.")
        for item in payload:
            if isinstance(item, dict) and isinstance(item.get("filename"), str):
                files.append(
                    {
                        "filename": item["filename"],
                        "status": item.get("status", "modified"),
                    }
                )
        if len(payload) < per_page:
            break
        if page == max_pages:
            raise ValueError(
                f"Pull request exceeds the {per_page * max_pages}-file detection limit."
            )
    return files


def write_github_changed_files(
    output: str | Path,
    *,
    event_path: str | Path,
    api_url: str,
    repository: str,
    token: str = "",
) -> dict:
    """Fetch and persist the minimal PR file metadata consumed by the CLI."""
    pull_request = _event_pull_request_number(event_path)
    files = (
        fetch_pull_request_files(
            api_url=api_url,
            repository=repository,
            pull_request=pull_request,
            token=token,
        )
        if pull_request
        else []
    )
    payload = {
        "version": "1",
        "source": "github-pull-request" if pull_request else "non-pull-request-event",
        "pull_request": pull_request,
        "files": files,
    }
    Path(output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch metadata-only GitHub PR changed files.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--event-path", default=os.getenv("GITHUB_EVENT_PATH", ""))
    parser.add_argument("--api-url", default=os.getenv("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    args = parser.parse_args(argv)
    if not args.event_path or not args.repository:
        print("GitHub event path and repository are required.", file=sys.stderr)
        return 2
    try:
        payload = write_github_changed_files(
            args.output,
            event_path=args.event_path,
            api_url=args.api_url,
            repository=args.repository,
            token=os.getenv("GITHUB_TOKEN", ""),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Unable to detect pull-request files: {exc}", file=sys.stderr)
        return 2
    print(f"Detected {len(payload['files'])} changed pull-request files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

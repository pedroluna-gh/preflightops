"""Tests for pull-request file detection and scanner-scope inference."""

import io
import json

import pytest

from preflightops import changed_files


def test_classifies_terraform_kubernetes_and_control_files(tmp_path):
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / "main.tf").write_text("resource {}", encoding="utf-8")
    (tmp_path / "k8s").mkdir()
    (tmp_path / "k8s" / "deployment.yaml").write_text(
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: api\n", encoding="utf-8"
    )

    scope = changed_files.classify_changed_files(
        ["infra/main.tf", "k8s/deployment.yaml", "services.yaml", "change.yaml", "README.md"],
        tmp_path,
    )

    assert scope["scanners"] == [
        "terraform",
        "kubernetes",
        "service-catalog",
        "change-request",
    ]
    assert scope["categories"]["terraform"] == ["infra/main.tf"]
    assert scope["categories"]["kubernetes"] == ["k8s/deployment.yaml"]
    assert scope["categories"]["other"] == ["README.md"]
    assert "no structured plan" in scope["warnings"][0]


def test_detects_content_based_kubernetes_manifest(tmp_path):
    manifest = tmp_path / "deploy.yaml"
    manifest.write_text(
        "apiVersion: v1\nkind: Service\nmetadata:\n  name: checkout\n", encoding="utf-8"
    )
    scope = changed_files.classify_changed_files(["deploy.yaml"], tmp_path)
    assert scope["scanners"] == ["kubernetes"]


def test_loads_json_api_and_newline_manifests(tmp_path):
    api_manifest = tmp_path / "api.json"
    api_manifest.write_text(
        json.dumps({"files": [{"filename": "main.tf"}, {"filename": "k8s/app.yaml"}]}),
        encoding="utf-8",
    )
    text_manifest = tmp_path / "files.txt"
    text_manifest.write_text("main.tf\n\nchange.yaml\n", encoding="utf-8")

    assert changed_files.load_changed_files(api_manifest) == ["main.tf", "k8s/app.yaml"]
    assert changed_files.load_changed_files(text_manifest) == ["main.tf", "change.yaml"]


def test_auto_loads_one_json_plan_and_multiple_kubernetes_files(tmp_path):
    plan = tmp_path / "tfplan.json"
    plan.write_text(json.dumps({"format_version": "1.2", "resource_changes": []}), encoding="utf-8")
    k8s = tmp_path / "k8s"
    k8s.mkdir()
    (k8s / "a.yaml").write_text("apiVersion: v1\nkind: Service\n", encoding="utf-8")
    (k8s / "b.yaml").write_text("apiVersion: v1\nkind: Secret\n", encoding="utf-8")

    scope = changed_files.classify_changed_files(
        ["tfplan.json", "k8s/a.yaml", "k8s/b.yaml"], tmp_path
    )
    loaded = changed_files.load_auto_scanner_inputs(scope, tmp_path)

    assert loaded["terraform_json"]["resource_changes"] == []
    assert loaded["terraform_json_files"] == ["tfplan.json"]
    assert loaded["kubernetes_files"] == ["k8s/a.yaml", "k8s/b.yaml"]
    assert "\n---\n" in loaded["kubernetes_text"]


def test_path_traversal_is_never_loaded(tmp_path):
    scope = changed_files.classify_changed_files(["../secret.tfplan.json"], tmp_path)
    loaded = changed_files.load_auto_scanner_inputs(scope, tmp_path)
    assert loaded["terraform_json"] is None
    assert loaded["terraform_json_files"] == []


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_fetch_pull_request_files_is_paginated_and_metadata_only(monkeypatch):
    pages = [
        [{"filename": "a.tf", "status": "modified", "patch": "secret"}, {"filename": "b.tf"}],
        [{"filename": "k8s/app.yaml", "status": "added", "sha": "abc"}],
    ]
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return _Response(json.dumps(pages.pop(0)).encode())

    monkeypatch.setattr(changed_files, "urlopen", fake_urlopen)
    result = changed_files.fetch_pull_request_files(
        api_url="https://api.github.com",
        repository="acme/api",
        pull_request=7,
        token="test-token",
        per_page=2,
    )

    assert result == [
        {"filename": "a.tf", "status": "modified"},
        {"filename": "b.tf", "status": "modified"},
        {"filename": "k8s/app.yaml", "status": "added"},
    ]
    assert len(requests) == 2
    assert requests[0][0].get_header("Authorization") == "Bearer test-token"
    assert "patch" not in result[0]


def test_fetch_pull_request_files_fails_closed_at_limit(monkeypatch):
    monkeypatch.setattr(
        changed_files,
        "urlopen",
        lambda request, timeout: _Response(json.dumps([{"filename": "a.tf"}]).encode()),
    )
    with pytest.raises(ValueError, match="1-file detection limit"):
        changed_files.fetch_pull_request_files(
            api_url="https://api.github.com",
            repository="acme/api",
            pull_request=7,
            per_page=1,
            max_pages=1,
        )


def test_write_github_manifest_uses_event_number(tmp_path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"number": 12, "pull_request": {}}), encoding="utf-8")
    output = tmp_path / "changed.json"
    calls = []

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        return [{"filename": "main.tf", "status": "modified"}]

    monkeypatch.setattr(changed_files, "fetch_pull_request_files", fake_fetch)
    payload = changed_files.write_github_changed_files(
        output,
        event_path=event,
        api_url="https://api.github.com",
        repository="acme/api",
        token="token",
    )

    assert payload["pull_request"] == 12
    assert calls[0]["pull_request"] == 12
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["files"][0]["filename"] == "main.tf"

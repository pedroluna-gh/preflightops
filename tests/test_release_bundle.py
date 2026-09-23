"""Exact release manifests fail closed on substitution and unsafe paths."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "release_bundle", Path(__file__).resolve().parents[1] / "scripts/release_bundle.py"
)
assert SPEC and SPEC.loader
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


@pytest.fixture
def directory(tmp_path):
    for name in (
        "preflightops-0.4.2-py3-none-any.whl",
        "preflightops-0.4.2.tar.gz",
        "preflightops.spdx.json",
        "reproducible-build.json",
        "preflightops-lock.cdx.json",
    ):
        (tmp_path / name).write_bytes(b"fixture-payload")
    (tmp_path / "reproducible-build.json").write_text(
        json.dumps(
            {
                "schema_version": "reproducible-build-v1",
                "byte_identical": True,
                "independent_builds": 2,
                "authenticated_provenance": False,
                "artifacts": {
                    name: bundle.sha256(tmp_path / name)
                    for name in (
                        "preflightops-0.4.2-py3-none-any.whl",
                        "preflightops-0.4.2.tar.gz",
                    )
                },
            }
        )
    )
    (tmp_path / "preflightops.spdx.json").write_text(
        json.dumps(
            {
                "spdxVersion": "SPDX-2.3",
                "packages": [
                    {
                        "SPDXID": "SPDXRef-package",
                        "name": "preflightops",
                        "versionInfo": "0.4.2",
                    }
                ],
            }
        )
    )
    return tmp_path


def test_round_trip_and_no_overwrite(directory):
    bundle.create(directory)
    assert len(bundle.verify(directory)) == 5
    before = (directory / bundle.MANIFEST).read_bytes()
    with pytest.raises(FileExistsError):
        bundle.create(directory)
    assert (directory / bundle.MANIFEST).read_bytes() == before


@pytest.mark.parametrize("attack", ["tamper", "missing", "extra", "empty", "directory", "version"])
def test_rejects_changed_inventory(directory, attack):
    bundle.create(directory)
    source = directory / "preflightops-0.4.2.tar.gz"
    if attack == "tamper":
        source.write_bytes(b"altered")
    elif attack == "missing":
        source.unlink()
    elif attack == "extra":
        (directory / "unexpected.txt").write_text("extra")
    elif attack == "empty":
        source.write_bytes(b"")
    elif attack == "directory":
        (directory / "nested").mkdir()
    else:
        source.rename(directory / "preflightops-0.4.3.tar.gz")
    with pytest.raises(ValueError):
        bundle.verify(directory)


@pytest.mark.parametrize(
    "attack", ["duplicate", "traversal", "absolute", "backslash", "omitted", "oversize"]
)
def test_rejects_malformed_manifest(directory, attack):
    bundle.create(directory)
    manifest = directory / bundle.MANIFEST
    lines = manifest.read_text().splitlines()
    if attack == "duplicate":
        lines.append(lines[0])
    elif attack == "omitted":
        lines.pop()
    elif attack == "oversize":
        lines = ["x" * 5000]
    else:
        names = {"traversal": "../escape", "absolute": "/escape", "backslash": "a\\b"}
        lines[0] = "0" * 64 + "  " + names[attack]
    manifest.write_text("\n".join(lines) + "\n", encoding="ascii")
    with pytest.raises(ValueError):
        bundle.verify(directory)


@pytest.mark.parametrize(
    "field,value",
    [
        ("artifacts", {}),
        ("byte_identical", False),
        ("independent_builds", True),
        ("independent_builds", 1),
        ("authenticated_provenance", True),
    ],
)
def test_rejects_false_build_claims_before_checksumming(directory, field, value):
    path = directory / "reproducible-build.json"
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        bundle.create(directory)
    assert not (directory / bundle.MANIFEST).exists()


@pytest.mark.parametrize("attack", ["missing", "wrong-version", "duplicate", "json-duplicate"])
def test_rejects_invalid_sbom(directory, attack):
    path = directory / "preflightops.spdx.json"
    record = json.loads(path.read_text())
    if attack == "missing":
        record["packages"] = []
    elif attack == "wrong-version":
        record["packages"][0]["versionInfo"] = "0.0.0"
    elif attack == "duplicate":
        record["packages"].append(record["packages"][0])
    path.write_text(json.dumps(record) if attack != "json-duplicate" else '{"a":1,"a":2}')
    with pytest.raises(ValueError):
        bundle.create(directory)

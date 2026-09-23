"""Release builds never promote mismatching or stale artifacts."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location("release_build", SCRIPTS / "release_build.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(SCRIPTS))
try:
    SPEC.loader.exec_module(module)
finally:
    sys.path.pop(0)


@pytest.mark.parametrize("failure", ["content", "missing", "extra", "empty"])
def test_compare_fails_closed(tmp_path, failure):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    if failure != "empty":
        (first / "package.whl").write_bytes(b"same")
        if failure != "missing":
            (second / "package.whl").write_bytes(b"different" if failure == "content" else b"same")
        if failure == "extra":
            (second / "extra.whl").write_bytes(b"extra")
    with pytest.raises(ValueError, match="not byte-identical"):
        module.compare_artifacts(first, second)


def test_compare_equal(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for directory in (first, second):
        (directory / "package.whl").write_bytes(b"same")
    assert module.compare_artifacts(first, second) == {
        "package.whl": module.digest(first / "package.whl")
    }


def test_existing_destination_is_not_modified(tmp_path):
    marker = tmp_path / "existing"
    marker.write_text("preserve")
    with pytest.raises(ValueError, match="already exist"):
        module.build_release(tmp_path, tmp_path, 1704067200)
    assert marker.read_text() == "preserve"


def test_snapshot_excludes_generated_metadata_and_cache(tmp_path):
    source, target = tmp_path / "source", tmp_path / "snapshot"
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        (source / name).write_text("input")
    for name in ("preflightops", "tests", "preflightops.egg-info"):
        directory = source / name
        directory.mkdir()
        (directory / "code.py").write_text("pass")
    (source / "preflightops" / "__pycache__").mkdir()
    (source / "preflightops" / "__pycache__" / "stale.pyc").write_bytes(b"stale")
    module.source_snapshot(source, target)
    assert (target / "preflightops" / "code.py").read_text() == "pass"
    assert not (target / "preflightops.egg-info").exists()
    assert not (target / "preflightops" / "__pycache__").exists()

"""Canonical packaging preserves payload while rejecting unsafe archives."""

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "reproducible_sdist", Path(__file__).resolve().parents[1] / "scripts/reproducible_sdist.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
ROOT = "preflightops-0.4.2"


def make_archive(path, timestamp=1, extra=None):
    with tarfile.open(path, "w:gz") as archive:
        for name in ("pyproject.toml", "PKG-INFO", "preflightops/cli.py"):
            member = tarfile.TarInfo(f"{ROOT}/{name}")
            member.size = 7
            member.mtime = timestamp
            archive.addfile(member, io.BytesIO(b"payload"))
        if extra is not None:
            archive.addfile(extra, io.BytesIO(b""))


def test_same_payload_has_same_archive_bytes(tmp_path):
    results = []
    for timestamp in (100, 999):
        source = tmp_path / f"source{timestamp}.tgz"
        result = tmp_path / f"result{timestamp}.tgz"
        make_archive(source, timestamp)
        module.canonical_sdist(source, result, 1704067200)
        results.append(result.read_bytes())
        with tarfile.open(result) as archive:
            assert all(member.mtime == 1704067200 for member in archive)
            assert archive.extractfile(f"{ROOT}/preflightops/cli.py").read() == b"payload"
    assert results[0] == results[1]


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "C:/drive", "x/../escape", f"{ROOT}/PKG-INFO"]
)
def test_rejects_unsafe_and_duplicate_names(tmp_path, name):
    source = tmp_path / "source.tgz"
    make_archive(source, extra=tarfile.TarInfo(name))
    with pytest.raises(ValueError):
        module.canonical_sdist(source, tmp_path / "result.tgz", 1704067200)
    assert not (tmp_path / "result.tgz").exists()


def test_rejects_links(tmp_path):
    member = tarfile.TarInfo(f"{ROOT}/link")
    member.type = tarfile.SYMTYPE
    member.linkname = "../../escape"
    source = tmp_path / "source.tgz"
    make_archive(source, extra=member)
    with pytest.raises(ValueError):
        module.canonical_sdist(source, tmp_path / "result.tgz", 1704067200)


def test_does_not_overwrite_existing_artifact(tmp_path):
    source = tmp_path / "source.tgz"
    make_archive(source)
    before = source.read_bytes()
    with pytest.raises(FileExistsError):
        module.canonical_sdist(source, source, 1704067200)
    assert source.read_bytes() == before

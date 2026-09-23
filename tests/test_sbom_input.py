"""SBOM scanning cannot accidentally include the complete developer checkout."""

import importlib.util
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "sbom_input", Path(__file__).resolve().parents[1] / "scripts/sbom_input.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def setup_source(tmp_path, member="preflightops-0.4.2.dist-info/METADATA"):
    source, dist = tmp_path / "source", tmp_path / "dist"
    source.mkdir()
    dist.mkdir()
    for name in ("uv.lock", "pyproject.toml", "not-for-upload.txt"):
        (source / name).write_text("fixture")
    with zipfile.ZipFile(dist / "preflightops-0.4.2-py3-none-any.whl", "w") as wheel:
        entry = zipfile.ZipInfo()
        entry.filename = member  # Preserve adversarial backslashes on Windows.
        wheel.writestr(entry, "Name: preflightops\nVersion: 0.4.2\n")
        wheel.writestr("preflightops/__init__.py", "raise RuntimeError('must not execute')")
    return source, dist


def test_exact_staging_and_expanded_metadata(tmp_path):
    source, dist = setup_source(tmp_path)
    output = tmp_path / "scan"
    module.stage(source, dist, output)
    assert not (output / "not-for-upload.txt").exists()
    assert (output / "wheel-metadata/preflightops-0.4.2.dist-info/METADATA").is_file()
    assert not (output / "wheel-metadata/preflightops").exists()
    with pytest.raises(ValueError):
        module.stage(source, dist, output)


@pytest.mark.parametrize("member", ["../escape", "/escape", "C:/escape", "x\\escape"])
def test_unsafe_wheel_entries_rejected(tmp_path, member):
    source, dist = setup_source(tmp_path, member)
    with pytest.raises(ValueError):
        module.stage(source, dist, tmp_path / "scan")

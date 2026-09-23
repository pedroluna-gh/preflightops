"""Build twice from clean source snapshots; publish only byte-identical artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from importlib.metadata import version
from pathlib import Path

from reproducible_sdist import canonical_sdist


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_snapshot(source: Path, target: Path) -> None:
    """Copy explicit packaging inputs, excluding caches and generated metadata."""
    target.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        item = source / name
        if item.is_symlink() or not item.is_file():
            raise ValueError("packaging input must be a regular file")
        shutil.copyfile(item, target / name)
    for name in ("preflightops", "tests"):
        directory = source / name
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("packaging source directory is invalid")
        for item in sorted(directory.rglob("*")):
            if "__pycache__" in item.parts or item.suffix == ".pyc":
                continue
            if item.is_symlink():
                raise ValueError("packaging source cannot contain symbolic links")
            if item.is_file():
                destination = target / item.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, destination)


def build_once(source: Path, work: Path, epoch: int) -> Path:
    snapshot = work / "source"
    source_snapshot(source, snapshot)
    raw, artifacts = work / "raw", work / "artifacts"
    artifacts.mkdir()
    env = {**os.environ, "SOURCE_DATE_EPOCH": str(epoch), "PYTHONHASHSEED": "0"}
    command = [sys.executable, "-m", "build", "--no-isolation"]
    subprocess.run(
        [*command, "--sdist", "--outdir", str(raw), str(snapshot)],
        env=env,
        check=True,
        timeout=300,
    )
    sdists = list(raw.glob("*.tar.gz"))
    if len(sdists) != 1:
        raise ValueError("expected one source distribution")
    canonical = artifacts / sdists[0].name
    canonical_sdist(sdists[0], canonical, epoch)
    unpacked = work / "unpacked"
    unpacked.mkdir()
    with tarfile.open(canonical) as archive:
        archive.extractall(unpacked, filter="data")
    roots = list(unpacked.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise ValueError("unexpected canonical source root")
    subprocess.run(
        [*command, "--wheel", "--outdir", str(artifacts), str(roots[0])],
        env=env,
        check=True,
        timeout=300,
    )
    if len(list(artifacts.glob("*.whl"))) != 1:
        raise ValueError("expected one wheel")
    return artifacts


def compare_artifacts(first: Path, second: Path) -> dict[str, str]:
    left = {path.name: digest(path) for path in first.iterdir() if path.is_file()}
    right = {path.name: digest(path) for path in second.iterdir() if path.is_file()}
    if not left or left != right:
        raise ValueError("independent builds are not byte-identical")
    return dict(sorted(left.items()))


def build_release(source: Path, output: Path, epoch: int) -> None:
    if output.exists():
        raise ValueError("release destination must not already exist")
    with tempfile.TemporaryDirectory(prefix="preflightops-release-") as directory:
        work = Path(directory)
        for name in ("first", "second"):
            (work / name).mkdir()
        first = build_once(source, work / "first", epoch)
        second = build_once(source, work / "second", epoch)
        hashes = compare_artifacts(first, second)
        record = {
            "schema_version": "reproducible-build-v1",
            "source_date_epoch": epoch,
            "python": platform.python_version(),
            "platform": sys.platform,
            "toolchain": {name: version(name) for name in ("build", "setuptools", "wheel")},
            "artifacts": hashes,
            "independent_builds": 2,
            "byte_identical": True,
            "authenticated_provenance": False,
        }
        # No artifact is promoted until both independent builds match.
        output.mkdir(parents=True)
        for name in hashes:
            shutil.copyfile(first / name, output / name)
        (output / "reproducible-build.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epoch", type=int, required=True)
    args = parser.parse_args()
    build_release(args.source.resolve(), args.output.resolve(), args.epoch)


if __name__ == "__main__":
    main()

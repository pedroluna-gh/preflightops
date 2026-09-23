"""Stage only public packaging metadata and the built wheel for SBOM scanning."""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path, PurePosixPath


def stage(source: Path, distributions: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("SBOM staging destination already exists")
    wheels = list(distributions.glob("preflightops-*.whl"))
    if len(wheels) != 1:
        raise ValueError("SBOM requires one built wheel")
    files = [source / "uv.lock", source / "pyproject.toml", wheels[0]]
    if any(path.is_symlink() or not path.is_file() for path in files):
        raise ValueError("SBOM inputs must be regular files")
    output.mkdir(parents=True)
    for path in files:
        shutil.copyfile(path, output / path.name)
    # Syft directory scanning needs expanded distribution metadata to identify
    # the actual wheel version/license rather than the dynamic project version.
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set()
        total = 0
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in info.orig_filename
                or "\x00" in info.orig_filename
                or ":" in info.filename
                or info.filename in names
            ):
                raise ValueError("unsafe wheel metadata path")
            names.add(info.filename)
            if not path.parts or not path.parts[0].endswith(".dist-info") or info.is_dir():
                continue
            total += info.file_size
            if total > 16 * 1024 * 1024:
                raise ValueError("wheel metadata exceeds limit")
            destination = output / "wheel-metadata" / info.filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(info))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distributions", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    stage(args.source, args.distributions, args.output)


if __name__ == "__main__":
    main()

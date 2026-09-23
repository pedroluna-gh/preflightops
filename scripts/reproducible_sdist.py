"""Canonicalize generated source archives before hashing or attesting them.

This is a packaging step, not a verifier of publisher identity. Payload bytes
are preserved; archive ownership, permissions, ordering and timestamps are fixed.
No archive member is extracted to the filesystem.
"""

from __future__ import annotations

import argparse
import gzip
import io
import re
import tarfile
from pathlib import Path, PurePosixPath

MAX_BYTES = 100 * 1024 * 1024
MAX_MEMBERS = 10000


def canonical_sdist(source: Path, destination: Path, epoch: int) -> None:
    if not 315532800 <= epoch <= 4294967295:
        raise ValueError("epoch must be within the supported archive timestamp range")
    if source.is_symlink() or source.stat().st_size > MAX_BYTES:
        raise ValueError("source archive is not a bounded regular input")
    entries: dict[str, bytes | None] = {}
    size = 0
    with tarfile.open(source, mode="r:gz") as archive:
        for member in archive:
            name = member.name
            path = PurePosixPath(name)
            if (
                len(entries) >= MAX_MEMBERS
                or not name
                or name != path.as_posix()
                or path.is_absolute()
                or any(part in (".", "..") for part in path.parts)
                or not re.fullmatch(r"[A-Za-z0-9._/+-]+", name)
                or name in entries
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("unsafe or ambiguous source archive member")
            size += member.size
            if size > MAX_BYTES:
                raise ValueError("expanded archive exceeds packaging limit")
            if member.isdir():
                entries[name] = None
            else:
                payload = archive.extractfile(member)
                if payload is None:
                    raise ValueError("missing archive payload")
                entries[name] = payload.read()
    roots = {PurePosixPath(name).parts[0] for name in entries}
    if len(roots) != 1 or not entries:
        raise ValueError("source archive must have one root")
    root = next(iter(roots))
    if not re.fullmatch(r"preflightops-[A-Za-z0-9.+-]+", root):
        raise ValueError("unexpected source distribution root")
    for required in ("pyproject.toml", "PKG-INFO"):
        if not entries.get(f"{root}/{required}"):
            raise ValueError("source archive lacks required metadata")
    for name in entries:
        for parent in PurePosixPath(name).parents:
            if parent.as_posix() in entries and entries[parent.as_posix()] is not None:
                raise ValueError("archive file is used as a directory")
    # Exclusive creation prevents silently overwriting artifacts already approved.
    with destination.open("xb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for name, payload in sorted(entries.items()):
                    info = tarfile.TarInfo(name)
                    info.mtime = epoch
                    info.mode = 0o755 if payload is None else 0o644
                    info.type = tarfile.DIRTYPE if payload is None else tarfile.REGTYPE
                    info.size = 0 if payload is None else len(payload)
                    archive.addfile(info, None if payload is None else io.BytesIO(payload))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--epoch", required=True, type=int)
    args = parser.parse_args()
    canonical_sdist(args.source, args.destination, args.epoch)


if __name__ == "__main__":
    main()

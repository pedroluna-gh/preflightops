"""Create or verify an exact offline release checksum manifest (not authenticity)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

MANIFEST = "SHA256SUMS"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,199}")


def inventory(directory: Path) -> dict[str, Path]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("bundle must be a regular directory")
    result = {}
    for item in directory.iterdir():
        if item.is_symlink() or not item.is_file() or not NAME.fullmatch(item.name):
            raise ValueError("bundle contains unsafe entries")
        if item.name != MANIFEST:
            result[item.name] = item
    wheels = [name for name in result if name.endswith(".whl")]
    sources = [name for name in result if name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("bundle requires exactly one wheel and source distribution")
    wheel = re.fullmatch(r"preflightops-([0-9][A-Za-z0-9.+]*)-py3-none-any\.whl", wheels[0])
    if wheel is None or sources[0] != f"preflightops-{wheel[1]}.tar.gz":
        raise ValueError("distribution names or versions disagree")
    expected = {
        wheels[0],
        sources[0],
        "preflightops.spdx.json",
        "reproducible-build.json",
        "preflightops-lock.cdx.json",
    }
    if set(result) != expected or any(item.stat().st_size == 0 for item in result.values()):
        raise ValueError("bundle inventory is incomplete or unexpected")
    return result


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate release metadata key")
        result[key] = value
    return result


def _metadata(path: Path) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("release metadata exceeds limit")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, RecursionError, json.JSONDecodeError) as error:
        raise ValueError("invalid release metadata JSON") from error
    if not isinstance(value, dict):
        raise ValueError("release metadata must be an object")
    return value


def validate_metadata(files: dict[str, Path]) -> None:
    record = _metadata(files["reproducible-build.json"])
    distributions = {
        name: sha256(path) for name, path in files.items() if name.endswith((".whl", ".tar.gz"))
    }
    if (
        record.get("schema_version") != "reproducible-build-v1"
        or record.get("artifacts") != distributions
        or record.get("byte_identical") is not True
        or type(record.get("independent_builds")) is not int
        or record["independent_builds"] != 2
        or record.get("authenticated_provenance") is not False
    ):
        raise ValueError("reproducibility record does not match release distributions")
    sbom = _metadata(files["preflightops.spdx.json"])
    # A minimal structural gate, not a replacement for SPDX schema validation
    # or complete dependency/license review.
    if sbom.get("spdxVersion") not in {"SPDX-2.2", "SPDX-2.3"}:
        raise ValueError("unsupported SPDX inventory version")
    packages = sbom.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("SBOM package inventory is absent")
    wheel_name = next(name for name in distributions if name.endswith(".whl"))
    release_version = wheel_name.split("-")[1]
    identities = set()
    found_release = False
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError("invalid SBOM package entry")
        identity = package.get("SPDXID")
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError("missing or duplicate SBOM package identity")
        identities.add(identity)
        if package.get("name") == "preflightops" and package.get("versionInfo") == release_version:
            found_release = True
    if not found_release:
        raise ValueError("SBOM does not identify the released package version")


def create(directory: Path) -> None:
    files = inventory(directory)
    validate_metadata(files)
    lines = [f"{sha256(path)}  {name}\n" for name, path in sorted(files.items())]
    with (directory / MANIFEST).open("x", encoding="ascii", newline="\n") as stream:
        stream.writelines(lines)


def verify(directory: Path) -> dict[str, str]:
    files = inventory(directory)
    manifest = directory / MANIFEST
    if manifest.stat().st_size > 4096:
        raise ValueError("checksum manifest exceeds limit")
    expected = {}
    for line in manifest.read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._+-]{0,199})", line)
        if match is None or match[2] in expected:
            raise ValueError("checksum manifest is unsafe or ambiguous")
        expected[match[2]] = match[1]
    if set(expected) != set(files):
        raise ValueError("checksum manifest does not cover exact bundle")
    if any(sha256(files[name]) != value for name, value in expected.items()):
        raise ValueError("release artifact checksum mismatch")
    validate_metadata(files)
    return expected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("create", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.operation == "create":
        create(args.directory)
    verify(args.directory)
    print(
        "Bundle integrity verified; publisher identity requires separate attestation verification."
    )


if __name__ == "__main__":
    main()

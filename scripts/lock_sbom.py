"""Export and verify all locked dependency identities; licenses remain separate."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def validate(lock: dict, sbom: dict) -> None:
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.5":
        raise ValueError("unexpected lock SBOM format")
    expected = set()
    for package in lock["package"]:
        source = package.get("source", {})
        if "registry" in source:
            expected.add((normalize(package["name"]), package["version"]))
        elif package["name"] != "preflightops" or source != {"editable": "."}:
            raise ValueError("unsupported non-registry dependency requires review")
    components = sbom.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("missing lock SBOM components")
    actual = set()
    refs = set()
    for component in components:
        if not isinstance(component, dict):
            raise ValueError("invalid lock SBOM component")
        name, version, ref = (component.get(key) for key in ("name", "version", "bom-ref"))
        if not all(isinstance(value, str) and value for value in (name, version, ref)):
            raise ValueError("incomplete lock SBOM identity")
        identity = (normalize(name), version)
        if identity in actual or ref in refs:
            raise ValueError("duplicate lock SBOM identity")
        actual.add(identity)
        refs.add(ref)
    if expected != actual:
        raise ValueError("lock SBOM differs from complete locked dependency inventory")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--uv", default=shutil.which("uv"))
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if args.output.exists() or args.uv is None:
        parser.error("output must not exist and uv must be available")
    output = args.output.resolve()
    subprocess.run(
        [
            str(Path(args.uv).resolve()),
            "export",
            "--locked",
            "--offline",
            "--all-groups",
            "--all-extras",
            "--format",
            "cyclonedx1.5",
            "--output-file",
            str(output),
        ],
        cwd=args.source,
        check=True,
        stdout=subprocess.DEVNULL,
        timeout=120,
    )
    validate(
        tomllib.loads((args.source / "uv.lock").read_text(encoding="utf-8")),
        json.loads(output.read_text(encoding="utf-8")),
    )
    print("Complete locked dependency inventory verified; license review remains required.")


if __name__ == "__main__":
    main()

"""Install the built wheel in an empty venv and exercise the public CLI."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def _venv_executable(environment: Path, executable: str) -> Path:
    scripts = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return environment / scripts / f"{executable}{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("distribution_dir", type=Path)
    parser.add_argument("--requirements", required=True, type=Path)
    parser.add_argument("--uv", type=Path, default=shutil.which("uv"))
    args = parser.parse_args()

    if args.uv is None:
        parser.error("uv is required on PATH or via --uv")

    wheels = sorted(args.distribution_dir.glob("preflightops-*.whl"))
    if len(wheels) != 1:
        parser.error(f"expected exactly one PreflightOps wheel, found {len(wheels)}")

    with tempfile.TemporaryDirectory(prefix="preflightops-wheel-") as directory:
        environment = Path(directory)
        venv.EnvBuilder(with_pip=False, clear=True).create(environment)
        wheel = environment / wheels[0].name
        shutil.copy2(wheels[0], wheel)
        python = _venv_executable(environment, "python")
        cli = _venv_executable(environment, "preflightops")

        subprocess.run(
            [
                str(args.uv),
                "pip",
                "install",
                "--python",
                str(python),
                "--requirement",
                str(args.requirements.resolve()),
            ],
            check=True,
        )
        subprocess.run(
            [
                str(args.uv),
                "pip",
                "install",
                "--python",
                str(python),
                "--no-deps",
                str(wheel),
            ],
            check=True,
        )
        completed = subprocess.run(
            [str(cli), "--version"], check=True, capture_output=True, text=True
        )
        if "preflightops" not in completed.stdout.lower():
            raise RuntimeError(f"unexpected CLI version output: {completed.stdout!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

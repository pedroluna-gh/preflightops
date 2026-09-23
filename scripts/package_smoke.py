"""Install the built wheel in an empty venv and exercise the public CLI."""

from __future__ import annotations

import argparse
import json
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


def _assessment_smoke(cli: Path, workspace: Path, examples: Path, risk: str) -> None:
    """Exercise the installed CLI outside the checkout, including its risk exit code."""
    case = workspace / risk.lower()
    case.mkdir()
    for kind in ("services", "change"):
        shutil.copy2(examples / f"{kind}-{risk.lower()}-risk.yaml", case / f"{kind}.yaml")
    command = [
        str(cli),
        "--services",
        "services.yaml",
        "--change",
        "change.yaml",
        "--output",
        "report.md",
        "--json-output",
        "report.json",
        "--html-output",
        "report.html",
        "--github-comment-output",
        "comment.md",
    ]
    if risk == "CRITICAL":
        shutil.copy2(examples / "terraform-critical.txt", case / "terraform.txt")
        command.extend(["--terraform", "terraform.txt"])
    result = subprocess.run(command, cwd=case, capture_output=True, text=True, timeout=60)
    expected_exit = 1 if risk == "CRITICAL" else 0
    if result.returncode != expected_exit:
        raise RuntimeError(f"installed {risk} assessment returned unexpected exit code")
    report = json.loads((case / "report.json").read_text(encoding="utf-8"))
    if report.get("risk_level") != risk:
        raise RuntimeError(f"installed {risk} assessment returned unexpected risk")
    for name in ("report.md", "report.html", "comment.md"):
        if not (case / name).is_file() or (case / name).stat().st_size == 0:
            raise RuntimeError("installed assessment did not produce every report")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("distribution_dir", type=Path)
    parser.add_argument("--requirements", required=True, type=Path)
    parser.add_argument("--uv", type=Path, default=shutil.which("uv"))
    args = parser.parse_args()

    if args.uv is None:
        parser.error("uv is required on PATH or via --uv")
    args.uv = args.uv.resolve()

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
                "--require-hashes",
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
            [str(cli), "--version"],
            check=True,
            capture_output=True,
            text=True,
            cwd=environment,
            timeout=60,
        )
        if "preflightops" not in completed.stdout.lower():
            raise RuntimeError(f"unexpected CLI version output: {completed.stdout!r}")
        subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "from preflightops.gcp_provider import GcpProvider; "
                "from preflightops.gcp_scope import GcpConfig; "
                "p = GcpProvider(GcpConfig('example-project', ('example-project',), 'p1', 'u1')); "
                "assert p.capabilities.read_only is True; "
                "assert p.capabilities.controls == ('p1.identity',)",
            ],
            check=True,
            cwd=environment,
            timeout=60,
        )
        examples = Path(__file__).resolve().parents[1] / "examples"
        for risk in ("LOW", "CRITICAL"):
            _assessment_smoke(cli, environment, examples, risk)

    return 0


if __name__ == "__main__":
    sys.exit(main())

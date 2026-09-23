"""SBOM completeness must include optional and toolchain lock entries."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "lock_sbom", Path(__file__).resolve().parents[1] / "scripts/lock_sbom.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fixtures():
    lock = {
        "package": [
            {
                "name": "some_package",
                "version": "1.0",
                "source": {"registry": "https://pypi.org/simple"},
            }
        ]
    }
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": [{"name": "some-package", "version": "1.0", "bom-ref": "p1"}],
    }
    return lock, bom


def test_complete_inventory():
    module.validate(*fixtures())


@pytest.mark.parametrize("attack", ["missing", "extra", "version", "duplicate", "local"])
def test_incomplete_or_ambiguous_inventory(attack):
    lock, bom = fixtures()
    if attack == "missing":
        bom["components"] = []
    elif attack == "extra":
        bom["components"].append({"name": "extra", "version": "1.0", "bom-ref": "p2"})
    elif attack == "version":
        bom["components"][0]["version"] = "2.0"
    elif attack == "duplicate":
        bom["components"].append(bom["components"][0].copy())
    else:
        lock["package"][0]["source"] = {"editable": "../other"}
    with pytest.raises(ValueError):
        module.validate(lock, bom)

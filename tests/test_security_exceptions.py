"""Security exceptions are bounded records, never automatic scanner bypasses."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "security_exceptions", Path(__file__).resolve().parents[1] / "scripts/security_exceptions.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
AT = module.timestamp("2026-09-16T00:00:00Z")


def registry():
    record = dict.fromkeys(module.FIELDS, "non-sensitive-reference")
    record.update(
        id="SEC-1",
        category="dependency",
        owner="maintainer",
        approved_by="reviewer",
        created_at="2026-09-01T00:00:00Z",
        expires_at="2026-10-01T00:00:00Z",
    )
    return {"schema_version": "security-exceptions-v1", "exceptions": [record]}


def test_valid_record_and_empty_registry():
    module.validate(registry(), AT)
    module.validate({"schema_version": "security-exceptions-v1", "exceptions": []}, AT)


@pytest.mark.parametrize(
    "field,value",
    [
        ("expires_at", "2026-09-16T00:00:00Z"),
        ("expires_at", "2027-01-01T00:00:00Z"),
        ("created_at", "2026-09-17T00:00:00Z"),
        ("created_at", "2026-09-01"),
        ("approved_by", " MAINTAINER "),
        ("scope", ""),
        ("category", "all"),
    ],
)
def test_invalid_record(field, value):
    document = registry()
    document["exceptions"][0][field] = value
    with pytest.raises(ValueError):
        module.validate(document, AT)


def test_missing_owner_and_duplicate_ids():
    document = registry()
    document["exceptions"].append(document["exceptions"][0].copy())
    with pytest.raises(ValueError):
        module.validate(document, AT)
    document = registry()
    del document["exceptions"][0]["owner"]
    with pytest.raises(ValueError):
        module.validate(document, AT)


def test_duplicate_json_keys():
    with pytest.raises(ValueError):
        module.unique_object([("exceptions", []), ("exceptions", [])])

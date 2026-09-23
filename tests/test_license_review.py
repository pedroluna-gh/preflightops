"""Uncertainty and stale license reviews must never authorize publication."""

import hashlib
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location("license_review", SCRIPTS / "license_review.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(SCRIPTS))
try:
    SPEC.loader.exec_module(module)
finally:
    sys.path.pop(0)
AT = datetime(2026, 9, 18, tzinfo=UTC)


def record(status="approved"):
    return {
        "schema_version": "license-review-v1",
        "lock_sha256_lf": hashlib.sha256(b"lock\n").hexdigest(),
        "status": status,
        "owner": "owner",
        "reviewed_at": "2026-09-17T00:00:00Z",
        "expires_at": "2026-10-01T00:00:00Z",
        "evidence_ref": "review-reference",
    }


def test_explicit_review_and_line_ending_compatibility():
    module.check(record(), b"lock\r\n", AT, publishing=True)


def test_pending_is_trackable_but_never_publishable():
    review = record("pending")
    review.update(reviewed_at=None, expires_at=None)
    module.check(review, b"lock\n", AT)
    with pytest.raises(ValueError, match="publication requires"):
        module.check(review, b"lock\n", AT, publishing=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "rejected"),
        ("lock_sha256_lf", "0" * 64),
        ("owner", ""),
        ("expires_at", "2026-09-18T00:00:00Z"),
        ("reviewed_at", "2026-09-19T00:00:00Z"),
        ("expires_at", "2027-10-01T00:00:00Z"),
        ("reviewed_at", None),
    ],
)
def test_invalid_review_blocks_publication(field, value):
    review = record()
    review[field] = value
    with pytest.raises(ValueError):
        module.check(review, b"lock\n", AT, publishing=True)

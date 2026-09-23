"""Require explicit, current license review before publishing a locked release."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from security_exceptions import timestamp, unique_object


def check(record: dict, lock: bytes, at: datetime, *, publishing: bool = False) -> None:
    fields = {
        "schema_version",
        "lock_sha256_lf",
        "status",
        "owner",
        "reviewed_at",
        "expires_at",
        "evidence_ref",
    }
    if not isinstance(record, dict) or set(record) != fields:
        raise ValueError("invalid license review record")
    if record["schema_version"] != "license-review-v1":
        raise ValueError("unsupported license review version")
    if record["lock_sha256_lf"] != hashlib.sha256(lock.replace(b"\r\n", b"\n")).hexdigest():
        raise ValueError("license review does not cover current lockfile")
    for field in ("owner", "evidence_ref"):
        if (
            not isinstance(record[field], str)
            or not record[field].strip()
            or len(record[field]) > 250
        ):
            raise ValueError("license review lacks bounded owner/evidence")
    if record["status"] not in {"pending", "approved", "rejected"}:
        raise ValueError("invalid license review status")
    if record["status"] == "pending":
        if record["reviewed_at"] is not None or record["expires_at"] is not None:
            raise ValueError("pending review cannot claim a review date")
    else:
        if not all(isinstance(record[field], str) for field in ("reviewed_at", "expires_at")):
            raise ValueError("license review requires explicit timestamps")
        reviewed, expires = timestamp(record["reviewed_at"]), timestamp(record["expires_at"])
        if (
            at.tzinfo is None
            or not reviewed <= at < expires
            or expires - reviewed > timedelta(days=90)
        ):
            raise ValueError("license review is inactive or expired")
    if publishing and record["status"] != "approved":
        raise ValueError("publication requires approved license review; findings remain unresolved")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--lock", type=Path, default=Path("uv.lock"))
    parser.add_argument("--publishing", action="store_true")
    args = parser.parse_args()
    with args.record.open("rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("license review record exceeds limit")
    record = json.loads(raw, object_pairs_hook=unique_object)
    check(record, args.lock.read_bytes(), datetime.now(UTC), publishing=args.publishing)
    print(f"License review record valid; publication status: {record['status']}.")


if __name__ == "__main__":
    main()

"""Validate time-bounded security records; never suppress scanner findings."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

FIELDS = {
    "id",
    "category",
    "finding",
    "scope",
    "owner",
    "approved_by",
    "reason",
    "compensating_control",
    "evidence_ref",
    "created_at",
    "expires_at",
}


def timestamp(value: str) -> datetime:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError("exception timestamps require UTC seconds")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate(document: object, at: datetime) -> None:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("evaluation time must have a timezone")
    if not isinstance(document, dict) or set(document) != {"schema_version", "exceptions"}:
        raise ValueError("invalid exception registry")
    if document["schema_version"] != "security-exceptions-v1":
        raise ValueError("unsupported exception registry")
    records = document["exceptions"]
    if not isinstance(records, list) or len(records) > 100:
        raise ValueError("exception registry exceeds bounds")
    ids = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != FIELDS:
            raise ValueError("incomplete or unknown exception fields")
        if any(not isinstance(v, str) or not v.strip() or len(v) > 500 for v in record.values()):
            raise ValueError("invalid exception field")
        if record["id"] in ids:
            raise ValueError("duplicate exception identifier")
        ids.add(record["id"])
        if record["category"] not in {"dependency", "license", "sast", "secret-scanning"}:
            raise ValueError("unknown exception category")
        if record["owner"].strip().casefold() == record["approved_by"].strip().casefold():
            raise ValueError("exception requires an independent approver")
        created, expires = timestamp(record["created_at"]), timestamp(record["expires_at"])
        if not created <= at < expires or expires - created > timedelta(days=90):
            raise ValueError("exception is inactive, expired or exceeds 90 days")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate registry key")
        result[key] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    parser.add_argument("--at", help="Explicit UTC timestamp for historical audit only")
    args = parser.parse_args()
    with args.registry.open("rb") as stream:
        raw = stream.read(262145)
    if len(raw) > 262144:
        raise ValueError("registry exceeds size limit")
    document = json.loads(raw, object_pairs_hook=unique_object)
    validate(document, timestamp(args.at) if args.at else datetime.now(UTC))
    print("Exception registry valid; scanner enforcement remains unchanged.")


if __name__ == "__main__":
    main()

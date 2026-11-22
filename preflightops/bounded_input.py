"""Content-safe limits before local input decoding and YAML construction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent, CollectionEndEvent, CollectionStartEvent

MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_YAML_BYTES = 4 * 1024 * 1024
MAX_YAML_NODES = 100_000
MAX_YAML_DEPTH = 64
MAX_ALIASES = 128


def read_text(path: str | Path, *, max_bytes: int = MAX_TEXT_BYTES) -> str:
    source = Path(path)
    if not source.is_file():
        raise ValueError("Input must be an existing regular file.")
    with source.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("Input exceeds the configured byte limit.")
    try:
        return raw.decode("utf-8")
    except UnicodeError:
        raise ValueError("Input must use UTF-8 encoding.") from None


def validate_yaml_structure(text: str) -> None:
    depth = aliases = 0
    try:
        for index, event in enumerate(yaml.parse(text, Loader=yaml.SafeLoader)):
            if isinstance(event, AliasEvent):
                aliases += 1
            if isinstance(event, CollectionStartEvent):
                depth += 1
            elif isinstance(event, CollectionEndEvent):
                depth -= 1
            if depth > MAX_YAML_DEPTH or aliases > MAX_ALIASES or index > MAX_YAML_NODES * 3:
                raise ValueError("Input exceeds the YAML structural budget.")
    except (yaml.YAMLError, RecursionError):
        raise ValueError("Input contains invalid YAML syntax.") from None


def load_yaml(path: str | Path) -> Any:
    text = read_text(path, max_bytes=MAX_YAML_BYTES)
    validate_yaml_structure(text)
    try:
        value = yaml.safe_load(text)
    except (yaml.YAMLError, RecursionError):
        raise ValueError("Input contains invalid YAML syntax.") from None
    # Count expanded references, not just unique nodes; stop alias bombs/cycles.
    stack = [(value, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > MAX_YAML_NODES or depth > MAX_YAML_DEPTH:
            raise ValueError("Input exceeds the expanded YAML budget.")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value

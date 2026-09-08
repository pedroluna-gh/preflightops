"""Bounded, unambiguous offline input for signed governance documents."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent, CollectionEndEvent, CollectionStartEvent

MAX_BYTES = 1024 * 1024
MAX_DEPTH = 32
MAX_NODES = 20000


def validate_json_tree(value: Any) -> None:
    """Reject cycles, non-JSON values and resource exhaustion before hashing."""
    nodes = 0
    ancestors: set[int] = set()

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise ValueError("Governance document exceeds structural limits.")
        if type(item) in (dict, list):
            identity = id(item)
            if identity in ancestors:
                raise ValueError("Governance document contains a cycle.")
            ancestors.add(identity)
            if type(item) is dict:
                if any(type(key) is not str for key in item):
                    raise ValueError("Governance document keys must be strings.")
                for child in item.values():
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
            ancestors.remove(identity)
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError("Governance document requires finite numbers.")
        elif item is not None and type(item) not in (str, int, bool):
            raise ValueError("Governance document requires JSON-compatible values.")

    visit(value, 0)


class _UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        mapping: dict = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in mapping:
                raise ValueError("Governance document has duplicate or non-string keys.")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def load_document(path: str | Path) -> dict:
    """Load JSON-compatible YAML without aliases, merge keys or duplicate keys."""
    source = Path(path)
    if not source.is_file():
        raise ValueError("Governance document does not exist.")
    with source.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Governance document exceeds the 1 MiB limit.")
    try:
        text = raw.decode("utf-8")
        depth = 0
        for index, event in enumerate(yaml.parse(text, Loader=yaml.SafeLoader)):
            if isinstance(event, AliasEvent):
                raise ValueError("Governance document aliases are not supported.")
            if isinstance(event, CollectionStartEvent):
                depth += 1
            elif isinstance(event, CollectionEndEvent):
                depth -= 1
            if depth > MAX_DEPTH or index > MAX_NODES * 3:
                raise ValueError("Governance document exceeds structural limits.")
        value = yaml.load(text, Loader=_UniqueLoader)
    except (UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("Could not load governance document: invalid encoding or syntax.") from exc
    if not isinstance(value, dict):
        raise ValueError("Governance document must be a YAML/JSON mapping.")
    validate_json_tree(value)
    return value

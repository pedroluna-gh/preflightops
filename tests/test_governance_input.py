"""Ambiguous signed input must never be normalized into trusted policy."""

from __future__ import annotations

import json

import pytest
from test_policy_governance import _bundle

from preflightops.governance_input import load_document, validate_json_tree
from preflightops.policy import load_policy_pack
from preflightops.policy_governance import governance_digest


@pytest.mark.parametrize(
    "content",
    [
        "owner: first\nowner: second\n",
        '{"owner":"first","owner":"second"}',
        "a: &a [*a]",
        "a: &a [1]\nb: *a",
        "a: {<<: {owner: hidden}}",
        "a: .nan",
        "a: .inf",
        "1: value",
        "a: !!python/object:danger {}",
        "a: 2026-01-01",
        "a: 1\n---\na: 2",
        "a: [" * 40 + "0" + "]" * 40,
    ],
)
def test_ambiguous_or_non_json_input_is_rejected(tmp_path, content):
    path = tmp_path / "input.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_document(path)


def test_valid_json_preserves_digest(tmp_path):
    document = _bundle()
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert load_document(path) == document
    assert governance_digest(load_document(path)) == governance_digest(document)


def test_policy_loader_cannot_bypass_duplicate_protection(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("version: '1'\nname: first\nname: second\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_policy_pack(str(path))


def test_syntax_errors_do_not_echo_input(tmp_path):
    path = tmp_path / "input.yaml"
    path.write_text("credential: [do-not-echo-this", encoding="utf-8")
    with pytest.raises(ValueError) as error:
        load_document(path)
    assert "do-not-echo-this" not in str(error.value)


@pytest.mark.parametrize("value", [{1: "bad"}, {"a": float("nan")}, {"a": {1, 2}}])
def test_direct_api_non_json_hash_rejected(value):
    with pytest.raises(ValueError):
        governance_digest(value)


def test_direct_api_cycle_rejected():
    value = {}
    value["cycle"] = value
    with pytest.raises(ValueError, match="cycle"):
        governance_digest(value)


def test_structural_node_limit():
    with pytest.raises(ValueError, match="structural limits"):
        validate_json_tree({"items": [None] * 20001})


def test_invalid_utf8_rejected_without_payload(tmp_path):
    path = tmp_path / "input.yaml"
    path.write_bytes(b"sensitive: \xff")
    with pytest.raises(ValueError, match="invalid encoding or syntax"):
        load_document(path)

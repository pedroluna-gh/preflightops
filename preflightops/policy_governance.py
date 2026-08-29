"""Signed policy bundles, scoped waivers, lineage, diff, and decision records.

This module deliberately keeps technical recommendations separate from human
change authority.  A verified waiver annotates accepted risk; it never reduces
the deterministic score and never records approval on behalf of CAB/ITSM.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

POLICY_API_VERSION = "preflightops.dev/policy/v2"
WAIVER_API_VERSION = "preflightops.dev/waiver/v1"
MAX_GOVERNANCE_DOCUMENT_BYTES = 1024 * 1024
_CLOSED_FAILURES = {"policy_validation", "signature", "context_conflict"}
_MATCH_FIELDS = {"environment", "tier", "change_class", "change_type"}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _unsigned_document(document: dict) -> dict:
    unsigned = deepcopy(document)
    unsigned.pop("signature", None)
    return unsigned


def governance_digest(document: dict) -> str:
    """Return the stable SHA-256 digest of a document excluding its signature."""
    return "sha256:" + hashlib.sha256(_canonical_json(_unsigned_document(document))).hexdigest()


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an RFC 3339 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC 3339 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Validation time must include a timezone.")
    return current.astimezone(timezone.utc)


def _load_document(path: str | Path) -> dict:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"Governance document does not exist: {source}")
    if source.stat().st_size > MAX_GOVERNANCE_DOCUMENT_BYTES:
        raise ValueError("Governance document exceeds the 1 MiB limit.")
    try:
        value = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not load governance document: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Governance document must be a YAML/JSON mapping.")
    return value


def load_governance_document(path: str | Path) -> dict:
    """Load a bounded YAML/JSON policy or waiver document."""
    return _load_document(path)


def _read_key(value: str | None, env_name: str) -> str:
    candidate = value or os.environ.get(env_name)
    if not candidate:
        raise ValueError(f"A key is required via a file or {env_name}.")
    path = Path(candidate)
    if "\n" not in candidate and path.is_file():
        return path.read_text(encoding="utf-8")
    return candidate


def read_governance_key(value: str | None, env_name: str) -> str:
    """Read a PEM key from an explicit path/value or a named environment variable."""
    return _read_key(value, env_name)


def _private_key(value: str) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(value.encode(), password=None)
    except (ValueError, TypeError) as exc:
        raise ValueError("Private key must be an unencrypted Ed25519 PEM key.") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Private key must be Ed25519.")
    return key


def _public_key(value: str) -> Ed25519PublicKey:
    try:
        key = serialization.load_pem_public_key(value.encode())
    except (ValueError, TypeError) as exc:
        raise ValueError("Public key must be an Ed25519 PEM key.") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Public key must be Ed25519.")
    return key


def _signature_bytes(document: dict) -> bytes:
    return _canonical_json(_unsigned_document(document))


def sign_governance_document(document: dict, private_key: str, key_id: str) -> dict:
    """Sign a policy or waiver without mutating the caller's object."""
    if not isinstance(key_id, str) or not key_id.strip():
        raise ValueError("key_id is required.")
    signed = deepcopy(document)
    signed.pop("signature", None)
    if signed.get("kind") == "PolicyBundle":
        signed.setdefault("metadata", {})["status"] = "active"
    signature = _private_key(private_key).sign(_signature_bytes(signed))
    signed["signature"] = {
        "algorithm": "ed25519",
        "key_id": key_id.strip(),
        "value": base64.b64encode(signature).decode("ascii"),
    }
    return signed


def verify_governance_signature(document: dict, public_key: str) -> str:
    signature = document.get("signature")
    if not isinstance(signature, dict):
        raise ValueError("Active governance document requires a signature.")
    if signature.get("algorithm") != "ed25519":
        raise ValueError("Only Ed25519 governance signatures are supported.")
    if not isinstance(signature.get("key_id"), str) or not signature["key_id"].strip():
        raise ValueError("signature.key_id is required.")
    try:
        raw = base64.b64decode(signature.get("value", ""), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Governance signature is not valid base64.") from exc
    try:
        _public_key(public_key).verify(raw, _signature_bytes(document))
    except InvalidSignature as exc:
        raise ValueError("Governance signature verification failed.") from exc
    return str(signature["key_id"])


def _validate_weights(value: Any, field: str = "risk_weights") -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping.")
    normalized: dict[str, int] = {}
    for rule_id, weight in value.items():
        if not isinstance(rule_id, str) or not rule_id.strip():
            raise ValueError(f"{field} rule ids must be non-empty strings.")
        if not isinstance(weight, int) or isinstance(weight, bool) or not 0 <= weight <= 100:
            raise ValueError(f"Weight for '{rule_id}' must be an integer between 0 and 100.")
        normalized[rule_id] = weight
    return normalized


def _validate_thresholds(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("risk_level_thresholds must be a mapping.")
    values = [value.get(level) for level in ("low", "medium", "high")]
    if any(not isinstance(item, int) or isinstance(item, bool) for item in values):
        raise ValueError("Risk thresholds low, medium, and high must be integers.")
    low, medium, high = cast(tuple[int, int, int], tuple(values))
    if not (0 <= low < medium < high < 100):
        raise ValueError("Risk thresholds must be ordered: 0 <= low < medium < high < 100.")
    return {"low": low, "medium": medium, "high": high}


def _validate_monitoring(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("monitoring must be a mapping.")
    minimum = value.get("minimum_enabled_monitors", 0)
    providers = value.get("required_providers", [])
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
        raise ValueError("minimum_enabled_monitors must be a non-negative integer.")
    if not isinstance(providers, list) or not all(
        isinstance(provider, str) and provider.strip() for provider in providers
    ):
        raise ValueError("required_providers must be a list of provider names.")
    return {
        "minimum_enabled_monitors": minimum,
        "required_providers": sorted({provider.strip().lower() for provider in providers}),
    }


def validate_policy_bundle(
    document: dict,
    *,
    public_key: str | None = None,
    at: datetime | None = None,
    for_assessment: bool = True,
) -> dict:
    """Validate Policy Bundle v2 and optionally verify its active signature."""
    if document.get("api_version") != POLICY_API_VERSION or document.get("kind") != "PolicyBundle":
        raise ValueError(f"Policy bundle must use {POLICY_API_VERSION} and kind PolicyBundle.")
    metadata = document.get("metadata")
    spec = document.get("spec")
    if not isinstance(metadata, dict) or not isinstance(spec, dict):
        raise ValueError("Policy bundle requires metadata and spec mappings.")
    for field in ("name", "version", "owner", "effective_from"):
        if not isinstance(metadata.get(field), str) or not metadata[field].strip():
            raise ValueError(f"metadata.{field} is required.")
    status = metadata.get("status", "draft")
    if status not in {"draft", "active", "retired"}:
        raise ValueError("metadata.status must be draft, active, or retired.")
    effective = _parse_time(metadata["effective_from"], "metadata.effective_from")
    expires = (
        _parse_time(metadata["expires_at"], "metadata.expires_at")
        if metadata.get("expires_at")
        else None
    )
    if expires and expires <= effective:
        raise ValueError("metadata.expires_at must be after effective_from.")
    current = _now(at)
    if for_assessment:
        if status != "active":
            raise ValueError("Only an active Policy Bundle v2 may drive an assessment.")
        if current < effective:
            raise ValueError("Policy bundle is not yet effective.")
        if expires and current >= expires:
            raise ValueError("Policy bundle has expired.")

    failure_modes = spec.get("failure_modes")
    if not isinstance(failure_modes, dict):
        raise ValueError("spec.failure_modes is required.")
    for name in (*sorted(_CLOSED_FAILURES), "evidence_unavailable"):
        if failure_modes.get(name) not in {"open", "closed"}:
            raise ValueError(f"failure_modes.{name} must be open or closed.")
    if any(failure_modes[name] != "closed" for name in _CLOSED_FAILURES):
        raise ValueError("Policy validation, signature, and context conflicts must fail closed.")

    base = spec.get("base")
    if not isinstance(base, dict):
        raise ValueError("spec.base is required.")
    normalized_base = {
        "risk_weights": _validate_weights(base.get("risk_weights", {})),
        "risk_level_thresholds": _validate_thresholds(
            base.get("risk_level_thresholds", {"low": 30, "medium": 60, "high": 80})
        ),
        "monitoring": _validate_monitoring(base.get("monitoring", {})),
    }
    mandatory = spec.get("mandatory_controls", [])
    if not isinstance(mandatory, list) or not all(
        isinstance(item, str) and item.strip() for item in mandatory
    ):
        raise ValueError("spec.mandatory_controls must be a list of rule ids.")
    mandatory_set = set(mandatory)
    missing_mandatory = mandatory_set - set(normalized_base["risk_weights"])
    if missing_mandatory:
        raise ValueError(
            "Mandatory controls require base weights: " + ", ".join(sorted(missing_mandatory))
        )

    overlays = spec.get("overlays", [])
    if not isinstance(overlays, list):
        raise ValueError("spec.overlays must be a list.")
    normalized_overlays = []
    seen_ids = set()
    for overlay in overlays:
        if not isinstance(overlay, dict):
            raise ValueError("Each policy overlay must be a mapping.")
        overlay_id = overlay.get("id")
        if not isinstance(overlay_id, str) or not overlay_id.strip() or overlay_id in seen_ids:
            raise ValueError("Each policy overlay requires a unique non-empty id.")
        seen_ids.add(overlay_id)
        priority = overlay.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise ValueError(f"Overlay '{overlay_id}' priority must be an integer.")
        match = overlay.get("match", {})
        if not isinstance(match, dict) or not match or set(match) - _MATCH_FIELDS:
            raise ValueError(f"Overlay '{overlay_id}' has invalid or empty match criteria.")
        normalized_match: dict[str, list[str]] = {}
        for field, expected in match.items():
            values = expected if isinstance(expected, list) else [expected]
            if not values or not all(isinstance(item, str) and item.strip() for item in values):
                raise ValueError(f"Overlay '{overlay_id}' match.{field} is invalid.")
            normalized_match[field] = sorted({item.strip().lower() for item in values})
        changes = overlay.get("apply", {})
        if not isinstance(changes, dict) or not changes:
            raise ValueError(f"Overlay '{overlay_id}' requires apply changes.")
        unknown = set(changes) - {"risk_weights", "risk_level_thresholds", "monitoring"}
        if unknown:
            raise ValueError(
                f"Overlay '{overlay_id}' has unsupported apply fields: {sorted(unknown)}"
            )
        normalized_apply: dict[str, Any] = {}
        if "risk_weights" in changes:
            normalized_apply["risk_weights"] = _validate_weights(
                changes["risk_weights"], f"overlay {overlay_id} risk_weights"
            )
            for rule_id, weight in normalized_apply["risk_weights"].items():
                if rule_id in mandatory_set and weight < normalized_base["risk_weights"][rule_id]:
                    raise ValueError(
                        f"Overlay '{overlay_id}' weakens mandatory control '{rule_id}'."
                    )
        if "risk_level_thresholds" in changes:
            normalized_apply["risk_level_thresholds"] = _validate_thresholds(
                changes["risk_level_thresholds"]
            )
        if "monitoring" in changes:
            normalized_apply["monitoring"] = _validate_monitoring(changes["monitoring"])
        normalized_overlays.append(
            {
                "id": overlay_id,
                "priority": priority,
                "match": normalized_match,
                "apply": normalized_apply,
            }
        )

    normalized = deepcopy(document)
    normalized["metadata"]["status"] = status
    normalized["spec"]["base"] = normalized_base
    normalized["spec"]["mandatory_controls"] = sorted(mandatory_set)
    normalized["spec"]["overlays"] = normalized_overlays
    normalized["digest"] = governance_digest(document)
    if status == "active":
        if not public_key:
            raise ValueError("Active Policy Bundle v2 requires a trusted public key.")
        normalized["verified_key_id"] = verify_governance_signature(document, public_key)
    elif for_assessment:
        raise ValueError("Only active signed policies may drive an assessment.")
    return normalized


def _matches(match: dict[str, list[str]], context: dict[str, str]) -> bool:
    return all(str(context.get(field, "")).lower() in expected for field, expected in match.items())


def resolve_policy_bundle(bundle: dict, context: dict[str, str]) -> dict:
    """Resolve deterministic hierarchy and reject same-priority conflicts."""
    spec = bundle["spec"]
    resolved = deepcopy(spec["base"])
    lineage = ["base"]
    applied_at_priority: dict[tuple[int, str], tuple[str, Any]] = {}
    for overlay in sorted(spec["overlays"], key=lambda item: (item["priority"], item["id"])):
        if not _matches(overlay["match"], context):
            continue
        for section, value in overlay["apply"].items():
            if isinstance(value, dict):
                for key, item in value.items():
                    conflict_key = (overlay["priority"], f"{section}.{key}")
                    previous = applied_at_priority.get(conflict_key)
                    if previous and previous[1] != item:
                        raise ValueError(
                            f"Policy context conflict at priority {overlay['priority']}: "
                            f"{previous[0]} and {overlay['id']} set {section}.{key} differently."
                        )
                    applied_at_priority[conflict_key] = (overlay["id"], item)
                resolved.setdefault(section, {}).update(deepcopy(value))
            else:
                resolved[section] = deepcopy(value)
        lineage.append(overlay["id"])
    return {
        "version": str(bundle["metadata"]["version"]),
        "name": str(bundle["metadata"]["name"]),
        "owner": str(bundle["metadata"]["owner"]),
        "effective_from": str(bundle["metadata"]["effective_from"]),
        "expires_at": bundle["metadata"].get("expires_at"),
        "digest": bundle["digest"],
        "risk_weights": resolved["risk_weights"],
        "risk_level_thresholds": resolved["risk_level_thresholds"],
        "monitoring": resolved["monitoring"],
        "mandatory_controls": spec["mandatory_controls"],
        "failure_modes": deepcopy(spec["failure_modes"]),
        "lineage": lineage,
        "context": {field: str(context.get(field, "")) for field in sorted(_MATCH_FIELDS)},
        "verified_key_id": bundle.get("verified_key_id"),
    }


def policy_diff(base: dict, candidate: dict, context: dict[str, str]) -> dict:
    """Return a deterministic field diff and flag candidate weakening."""
    before = resolve_policy_bundle(base, context)
    after = resolve_policy_bundle(candidate, context)
    changes = []
    all_rules = sorted(set(before["risk_weights"]) | set(after["risk_weights"]))
    for rule_id in all_rules:
        old = before["risk_weights"].get(rule_id)
        new = after["risk_weights"].get(rule_id)
        if old != new:
            direction = (
                "added"
                if old is None
                else "removed"
                if new is None
                else "strengthened"
                if new > old
                else "weakened"
            )
            changes.append(
                {
                    "field": f"risk_weights.{rule_id}",
                    "before": old,
                    "after": new,
                    "direction": direction,
                }
            )
    for level in ("low", "medium", "high"):
        old = before["risk_level_thresholds"][level]
        new = after["risk_level_thresholds"][level]
        if old != new:
            changes.append(
                {
                    "field": f"risk_level_thresholds.{level}",
                    "before": old,
                    "after": new,
                    "direction": "weakened" if new > old else "strengthened",
                }
            )
    old_minimum = before["monitoring"]["minimum_enabled_monitors"]
    new_minimum = after["monitoring"]["minimum_enabled_monitors"]
    if old_minimum != new_minimum:
        changes.append(
            {
                "field": "monitoring.minimum_enabled_monitors",
                "before": old_minimum,
                "after": new_minimum,
                "direction": "weakened" if new_minimum < old_minimum else "strengthened",
            }
        )
    old_providers = set(before["monitoring"]["required_providers"])
    new_providers = set(after["monitoring"]["required_providers"])
    for provider in sorted(old_providers | new_providers):
        if (provider in old_providers) != (provider in new_providers):
            changes.append(
                {
                    "field": f"monitoring.required_providers.{provider}",
                    "before": provider in old_providers,
                    "after": provider in new_providers,
                    "direction": "strengthened" if provider in new_providers else "weakened",
                }
            )
    old_mandatory = set(before["mandatory_controls"])
    new_mandatory = set(after["mandatory_controls"])
    for rule_id in sorted(old_mandatory | new_mandatory):
        if (rule_id in old_mandatory) != (rule_id in new_mandatory):
            changes.append(
                {
                    "field": f"mandatory_controls.{rule_id}",
                    "before": rule_id in old_mandatory,
                    "after": rule_id in new_mandatory,
                    "direction": "strengthened" if rule_id in new_mandatory else "weakened",
                }
            )
    old_evidence_mode = before["failure_modes"]["evidence_unavailable"]
    new_evidence_mode = after["failure_modes"]["evidence_unavailable"]
    if old_evidence_mode != new_evidence_mode:
        changes.append(
            {
                "field": "failure_modes.evidence_unavailable",
                "before": old_evidence_mode,
                "after": new_evidence_mode,
                "direction": "weakened" if new_evidence_mode == "open" else "strengthened",
            }
        )
    return {
        "base_digest": base["digest"],
        "candidate_digest": candidate["digest"],
        "context": context,
        "changes": changes,
        "weakening": any(change["direction"] in {"weakened", "removed"} for change in changes),
        "base_lineage": before["lineage"],
        "candidate_lineage": after["lineage"],
    }


def validate_waiver(
    document: dict,
    *,
    public_key: str,
    policy_digest: str,
    context: dict[str, str],
    at: datetime | None = None,
    enforce_current: bool = True,
) -> dict:
    """Verify a scoped, expiring waiver and separation of duties."""
    if document.get("api_version") != WAIVER_API_VERSION or document.get("kind") != "Waiver":
        raise ValueError(f"Waiver must use {WAIVER_API_VERSION} and kind Waiver.")
    metadata = document.get("metadata")
    scope = document.get("scope")
    if not isinstance(metadata, dict) or not isinstance(scope, dict):
        raise ValueError("Waiver requires metadata and scope mappings.")
    for field in ("id", "issued_at", "expires_at"):
        if not isinstance(metadata.get(field), str) or not metadata[field].strip():
            raise ValueError(f"metadata.{field} is required.")
    issued = _parse_time(metadata["issued_at"], "metadata.issued_at")
    expires = _parse_time(metadata["expires_at"], "metadata.expires_at")
    current = _now(at)
    if expires <= issued:
        raise ValueError("Waiver expiry must be after issuance.")
    if enforce_current and (current < issued or current >= expires):
        raise ValueError("Waiver is not currently valid or has expired.")
    requester = document.get("requester")
    approver = document.get("approver")
    if not isinstance(requester, str) or not requester.strip():
        raise ValueError("Waiver requester is required.")
    if not isinstance(approver, str) or not approver.strip():
        raise ValueError("Waiver approver is required.")
    if requester.strip().lower() == approver.strip().lower():
        raise ValueError("Waiver requester and approver must be different identities.")
    for field in ("reason_code", "justification"):
        if not isinstance(document.get(field), str) or not document[field].strip():
            raise ValueError(f"Waiver {field} is required.")
    for field in ("evidence_references", "compensating_controls"):
        values = document.get(field)
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(item, str) and item.strip() for item in values)
        ):
            raise ValueError(f"Waiver {field} must be a non-empty list.")
    if scope.get("policy_digest") != policy_digest:
        raise ValueError("Waiver policy digest does not match the active policy.")
    rules = scope.get("rules")
    if not isinstance(rules, list) or not rules or not all(isinstance(item, str) for item in rules):
        raise ValueError("Waiver scope.rules must be a non-empty list.")
    for field in ("service", "environment", "change_class", "change_type"):
        if not isinstance(scope.get(field), str) or not scope[field].strip():
            raise ValueError(f"Waiver scope.{field} is required.")
    for field in ("service", "environment", "change_class", "change_type"):
        expected = scope.get(field)
        if (
            expected not in {None, "*"}
            and str(expected).lower() != str(context.get(field, "")).lower()
        ):
            raise ValueError(f"Waiver scope does not match {field}.")
    key_id = verify_governance_signature(document, public_key)
    return {
        "id": metadata["id"],
        "digest": governance_digest(document),
        "policy_digest": policy_digest,
        "rules": sorted(set(rules)),
        "requester": requester,
        "approver": approver,
        "reason_code": document["reason_code"],
        "evidence_references": list(document["evidence_references"]),
        "compensating_controls": list(document["compensating_controls"]),
        "expires_at": metadata["expires_at"],
        "verified_key_id": key_id,
        "status": "verified",
    }


def apply_verified_waivers(result: dict, waivers: list[dict]) -> dict:
    """Annotate findings while preserving score and external decision authority."""
    enriched = deepcopy(result)
    covered: dict[str, list[str]] = {}
    for waiver in waivers:
        for rule_id in waiver["rules"]:
            covered.setdefault(rule_id, []).append(waiver["id"])
    for finding in enriched.get("triggered_rules", []):
        ids = covered.get(finding.get("id"), [])
        if ids:
            finding["waiver_ids"] = sorted(ids)
            finding["waiver_status"] = "verified_exception_recorded"
    enriched["verified_waivers"] = waivers
    enriched["decision_record"] = {
        "technical_recommendation": {
            "risk_score": enriched.get("risk_score"),
            "risk_level": enriched.get("risk_level"),
            "recommendation": enriched.get("recommendation"),
        },
        "verified_exception_count": len(waivers),
        "human_decision": {
            "status": "not_recorded",
            "authority": "external_cab_or_change_management",
        },
        "automatic_approval": False,
    }
    return enriched


def governance_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="preflightops policy")
    sub = parser.add_subparsers(dest="command", required=True)
    lint = sub.add_parser("lint", help="Validate policy metadata, hierarchy, dates, and signature.")
    lint.add_argument("--policy", required=True)
    lint.add_argument("--public-key")
    lint.add_argument("--draft", action="store_true", help="Allow an unsigned draft policy.")
    sign = sub.add_parser(
        "sign", help="Sign a policy bundle using PREFLIGHTOPS_POLICY_PRIVATE_KEY."
    )
    sign.add_argument("--policy", required=True)
    sign.add_argument("--output", required=True)
    sign.add_argument("--key-id", required=True)
    diff = sub.add_parser("diff", help="Compare two bundles for one deterministic context.")
    diff.add_argument("--base", required=True)
    diff.add_argument("--candidate", required=True)
    diff.add_argument("--context", required=True, help="YAML/JSON context file.")
    diff.add_argument("--base-public-key")
    diff.add_argument("--candidate-public-key")
    diff.add_argument("--output", default="policy-diff.json")
    simulate = sub.add_parser(
        "simulate", help="Compare assessment outcomes before activating a candidate bundle."
    )
    simulate.add_argument("--base", required=True)
    simulate.add_argument("--candidate", required=True)
    simulate.add_argument("--services", required=True)
    simulate.add_argument("--change", required=True)
    simulate.add_argument("--output", default="policy-simulation.json")
    args = parser.parse_args(argv)
    try:
        if args.command == "lint":
            document = _load_document(args.policy)
            public_key = (
                _read_key(args.public_key, "PREFLIGHTOPS_POLICY_PUBLIC_KEY")
                if not args.draft
                else None
            )
            bundle = validate_policy_bundle(
                document, public_key=public_key, for_assessment=not args.draft
            )
            print(
                json.dumps(
                    {
                        "status": "valid",
                        "digest": bundle["digest"],
                        "mode": "draft" if args.draft else "active",
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "sign":
            document = _load_document(args.policy)
            validate_policy_bundle(document, for_assessment=False)
            signed = sign_governance_document(
                document,
                _read_key(None, "PREFLIGHTOPS_POLICY_PRIVATE_KEY"),
                args.key_id,
            )
            Path(args.output).write_text(yaml.safe_dump(signed, sort_keys=False), encoding="utf-8")
            print(f"Signed policy written to: {args.output}")
            return 0
        if args.command == "simulate":
            from .risk_engine import assess_risk

            services = _load_document(args.services)
            change = _load_document(args.change)
            change_body = change.get("change", {})
            service_name = str(change_body.get("service", ""))
            service = next(
                (
                    item
                    for item in services.get("services", [])
                    if isinstance(item, dict) and item.get("name") == service_name
                ),
                {},
            )
            context = {
                "environment": str(change_body.get("environment", "")),
                "tier": str(service.get("tier") or service.get("criticality") or ""),
                "change_class": str(
                    change_body.get("change_class") or change_body.get("classification") or "normal"
                ),
                "change_type": str(change_body.get("change_type", "")),
            }
            base_bundle = validate_policy_bundle(_load_document(args.base), for_assessment=False)
            candidate_bundle = validate_policy_bundle(
                _load_document(args.candidate), for_assessment=False
            )
            before = assess_risk(
                services, change, policy=resolve_policy_bundle(base_bundle, context)
            )
            after = assess_risk(
                services, change, policy=resolve_policy_bundle(candidate_bundle, context)
            )
            output = {
                "mode": "non_authoritative_simulation",
                "context": context,
                "base": {
                    "policy_digest": base_bundle["digest"],
                    "risk_score": before["risk_score"],
                    "risk_level": before["risk_level"],
                },
                "candidate": {
                    "policy_digest": candidate_bundle["digest"],
                    "risk_score": after["risk_score"],
                    "risk_level": after["risk_level"],
                },
                "score_delta": after["risk_score"] - before["risk_score"],
                "human_decision": "not_recorded",
                "automatic_approval": False,
            }
            Path(args.output).write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
            print(f"Policy simulation written to: {args.output}")
            return 0
        context = _load_document(args.context)
        if set(context) - _MATCH_FIELDS:
            raise ValueError("Policy context has unsupported fields.")
        base_document = _load_document(args.base)
        candidate_document = _load_document(args.candidate)
        base = validate_policy_bundle(
            base_document,
            public_key=(
                _read_key(args.base_public_key, "PREFLIGHTOPS_POLICY_PUBLIC_KEY")
                if base_document.get("metadata", {}).get("status") == "active"
                else None
            ),
            for_assessment=False,
        )
        candidate = validate_policy_bundle(
            candidate_document,
            public_key=(
                _read_key(args.candidate_public_key, "PREFLIGHTOPS_POLICY_PUBLIC_KEY")
                if candidate_document.get("metadata", {}).get("status") == "active"
                else None
            ),
            for_assessment=False,
        )
        output = policy_diff(base, candidate, {key: str(value) for key, value in context.items()})
        Path(args.output).write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
        print(f"Policy diff written to: {args.output}")
        return 0
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Policy governance error: {exc}", file=sys.stderr)
        return 2


def waiver_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="preflightops waiver")
    sub = parser.add_subparsers(dest="command", required=True)
    sign = sub.add_parser("sign")
    sign.add_argument("--waiver", required=True)
    sign.add_argument("--output", required=True)
    sign.add_argument("--key-id", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--waiver", required=True)
    verify.add_argument("--public-key")
    verify.add_argument("--policy-digest", required=True)
    verify.add_argument("--context", required=True)
    args = parser.parse_args(argv)
    try:
        document = _load_document(args.waiver)
        if args.command == "sign":
            private_key_text = _read_key(None, "PREFLIGHTOPS_WAIVER_PRIVATE_KEY")
            signed = sign_governance_document(
                document,
                private_key_text,
                args.key_id,
            )
            signer_public_key = (
                _private_key(private_key_text)
                .public_key()
                .public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
                .decode()
            )
            scope = signed.get("scope", {})
            validate_waiver(
                signed,
                public_key=signer_public_key,
                policy_digest=str(scope.get("policy_digest", "")),
                context={
                    field: str(scope.get(field, ""))
                    for field in ("service", "environment", "change_class", "change_type")
                },
                enforce_current=False,
            )
            Path(args.output).write_text(yaml.safe_dump(signed, sort_keys=False), encoding="utf-8")
            print(f"Signed waiver written to: {args.output}")
            return 0
        context = _load_document(args.context)
        verdict = validate_waiver(
            document,
            public_key=_read_key(args.public_key, "PREFLIGHTOPS_WAIVER_PUBLIC_KEY"),
            policy_digest=args.policy_digest,
            context={key: str(value) for key, value in context.items()},
        )
        print(json.dumps(verdict, sort_keys=True))
        return 0
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Waiver governance error: {exc}", file=sys.stderr)
        return 2

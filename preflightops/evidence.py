"""Authenticated, portable evidence for PreflightOps assessments.

Evidence Contract v2 uses an in-toto Statement carried by a DSSE envelope and
signed with Ed25519.  Verification is deliberately offline: the caller supplies
the trusted public key and, when required by policy, the expected execution
identity and input files.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ._version import __version__

PAYLOAD_TYPE = "application/vnd.in-toto+json"
PREDICATE_TYPE = "https://preflightops.dev/attestations/evidence/v2"
PRIVATE_KEY_ENV = "PREFLIGHTOPS_EVIDENCE_PRIVATE_KEY"
PUBLIC_KEY_ENV = "PREFLIGHTOPS_EVIDENCE_PUBLIC_KEY"
MAX_EVIDENCE_BYTES = 1024 * 1024

_SECRET_KEY_RE = re.compile(
    r"(?:password|passwd|secret|token|credential|private[_-]?key|authorization|cookie)", re.I
)


class EvidenceError(ValueError):
    """Raised when evidence cannot be safely generated or parsed."""


def canonical_json(value: Any) -> bytes:
    """Return the stable UTF-8 JSON representation used by all digests."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def redact_evidence(value: Any, depth: int = 0) -> Any:
    """Apply deterministic key redaction and collection/length bounds."""

    if depth > 8:
        return "[depth-limited]"
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))[:100]:
            rendered_key = str(key)
            if _SECRET_KEY_RE.search(rendered_key):
                continue
            redacted[rendered_key] = redact_evidence(item, depth + 1)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_evidence(item, depth + 1) for item in list(value)[:100]]
    if isinstance(value, str):
        return value[:4000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:4000]


def _normalize_digest(value: str) -> str:
    digest = str(value or "").strip().lower()
    if digest.startswith("sha256:"):
        digest = digest[7:]
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise EvidenceError("Expected a SHA-256 digest as 64 hexadecimal characters.")
    return digest


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _timestamp(value: dt.datetime | None) -> str:
    moment = value or _utc_now()
    if moment.tzinfo is None:
        raise EvidenceError("Evidence timestamps must include a timezone.")
    return moment.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> dt.datetime:
    if not isinstance(value, str):
        raise EvidenceError("Evidence generated_at must be an RFC 3339 timestamp.")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("Evidence generated_at is not a valid RFC 3339 timestamp.") from exc
    if parsed.tzinfo is None:
        raise EvidenceError("Evidence generated_at must include a timezone.")
    return parsed.astimezone(dt.timezone.utc)


def _load_document(path: str | Path) -> Any:
    location = Path(path)
    try:
        text = location.read_text(encoding="utf-8")
        if location.suffix.lower() == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise EvidenceError(f"Unable to load {location}: {exc}") from exc


def _key_material(source: str | bytes | Path | None, env_name: str) -> bytes:
    configured: str | bytes | Path | None = source
    if configured is None:
        configured = os.environ.get(env_name)
    if configured is None or configured == "":
        raise EvidenceError(f"A signing key is required via a key file or {env_name}.")
    if isinstance(configured, bytes):
        return configured
    rendered = str(configured)
    if "-----BEGIN" in rendered:
        return rendered.encode("utf-8")
    try:
        return Path(rendered).read_bytes()
    except OSError as exc:
        raise EvidenceError(f"Unable to read key material from {rendered!r}.") from exc


def load_private_key(source: str | bytes | Path | None = None) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(_key_material(source, PRIVATE_KEY_ENV), None)
    except (TypeError, ValueError) as exc:
        raise EvidenceError("The evidence private key is not valid unencrypted PEM.") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise EvidenceError("Evidence signing requires an Ed25519 private key.")
    return key


def load_public_key(source: str | bytes | Path | None = None) -> Ed25519PublicKey:
    try:
        key = serialization.load_pem_public_key(_key_material(source, PUBLIC_KEY_ENV))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("The trusted evidence public key is not valid PEM.") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise EvidenceError("Evidence verification requires an Ed25519 public key.")
    return key


def public_key_id(key: Ed25519PublicKey) -> str:
    encoded = key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return f"sha256:{sha256_digest(encoded)}"


def dsse_pae(payload_type: str, payload: bytes) -> bytes:
    """Produce DSSE Pre-Authentication Encoding exactly as specified."""

    type_bytes = payload_type.encode("utf-8")
    return b"DSSEv1 %d %s %d %s" % (len(type_bytes), type_bytes, len(payload), payload)


def _change_section(change_doc: Any) -> dict[str, Any]:
    if isinstance(change_doc, Mapping) and isinstance(change_doc.get("change"), Mapping):
        return dict(change_doc["change"])
    return {}


def _source_from_env(env: Mapping[str, str]) -> dict[str, str]:
    mapping = {
        "organization": env.get("GITHUB_REPOSITORY_OWNER", ""),
        "repository": env.get("GITHUB_REPOSITORY", ""),
        "commit": env.get("GITHUB_SHA", ""),
        "ref": env.get("GITHUB_REF", ""),
        "workflow": env.get("GITHUB_WORKFLOW", ""),
        "run_id": env.get("GITHUB_RUN_ID", ""),
        "run_attempt": env.get("GITHUB_RUN_ATTEMPT", ""),
        "actor": env.get("GITHUB_ACTOR", ""),
    }
    server = env.get("GITHUB_SERVER_URL", "")
    if server and mapping["repository"] and mapping["run_id"]:
        mapping["run_url"] = f"{server}/{mapping['repository']}/actions/runs/{mapping['run_id']}"
    return {key: value for key, value in mapping.items() if value}


def _named_input_digests(inputs: Mapping[str, bytes] | None) -> list[dict[str, Any]]:
    records = []
    for name, content in sorted((inputs or {}).items()):
        if not name or len(name) > 256:
            raise EvidenceError("Evidence input names must contain 1 to 256 characters.")
        records.append({"name": name, "digest": {"sha256": sha256_digest(content)}})
    return records


def build_statement_v2(
    assessment: Mapping[str, Any],
    change_doc: Any = None,
    *,
    provenance: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    inputs: Mapping[str, bytes] | None = None,
    data_classification: str = "internal",
    generated_at: dt.datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the unsigned Evidence Contract v2 in-toto Statement."""

    if data_classification not in {"public", "internal", "confidential", "restricted"}:
        raise EvidenceError("Unsupported data classification.")
    environment = os.environ if env is None else env
    safe_assessment = redact_evidence(dict(assessment))
    change = redact_evidence(_change_section(change_doc))
    source = redact_evidence(dict(provenance or _source_from_env(environment)))
    configured_policy = redact_evidence(
        dict(policy or assessment.get("policy_pack") or {"name": "unknown", "version": "unknown"})
    )
    policy_digest = sha256_digest(canonical_json(configured_policy))
    assessment_digest = sha256_digest(canonical_json(safe_assessment))
    input_records = _named_input_digests(inputs)
    service = str(assessment.get("service") or change.get("service") or "")
    target_environment = str(assessment.get("environment") or change.get("environment") or "")
    repository = str(source.get("repository") or "unknown-repository")
    commit = str(source.get("commit") or "unknown-commit")
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {
                "name": f"preflightops-assessment:{repository}@{commit}",
                "digest": {"sha256": assessment_digest},
            }
        ],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "schema_version": "2.0",
            "generated_at": _timestamp(generated_at),
            "producer": {"name": "PreflightOps", "version": __version__},
            "organization": str(source.get("organization") or ""),
            "context": {
                "repository": repository,
                "commit": commit,
                "ref": str(source.get("ref") or ""),
                "service": service,
                "environment": target_environment,
                "change_id": str(change.get("id") or ""),
            },
            "provenance": source,
            "policy": {
                "name": str(configured_policy.get("name") or "unknown"),
                "version": str(configured_policy.get("version") or "unknown"),
                "digest": {"sha256": policy_digest},
            },
            "inputs": input_records,
            "assessment": safe_assessment,
            "assessment_digest": {"sha256": assessment_digest},
            "data": {
                "classification": data_classification,
                "redaction_profile": "preflightops-default-v1",
                "content_embedded": False,
            },
            "governance": {
                "purpose": "Automated pre-change technical evidence",
                "cab_authority": "External ITSM workflow and authorized CAB remain authoritative",
                "changes_workflow_state": False,
                "grants_approval": False,
            },
        },
    }
    if len(canonical_json(statement)) > MAX_EVIDENCE_BYTES:
        raise EvidenceError("Evidence statement exceeds the 1 MiB safety limit.")
    return statement


def sign_statement(
    statement: Mapping[str, Any], private_key: str | bytes | Path | Ed25519PrivateKey | None = None
) -> dict[str, Any]:
    """Wrap and sign one statement as a DSSE envelope."""

    key = (
        private_key if isinstance(private_key, Ed25519PrivateKey) else load_private_key(private_key)
    )
    payload = canonical_json(dict(statement))
    signature = key.sign(dsse_pae(PAYLOAD_TYPE, payload))
    return {
        "payloadType": PAYLOAD_TYPE,
        "payload": base64.b64encode(payload).decode("ascii"),
        "signatures": [
            {
                "keyid": public_key_id(key.public_key()),
                "sig": base64.b64encode(signature).decode("ascii"),
            }
        ],
    }


def generate_evidence_v2(
    assessment: Mapping[str, Any],
    change_doc: Any = None,
    *,
    private_key: str | bytes | Path | Ed25519PrivateKey | None = None,
    provenance: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    inputs: Mapping[str, bytes] | None = None,
    data_classification: str = "internal",
    generated_at: dt.datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    statement = build_statement_v2(
        assessment,
        change_doc,
        provenance=provenance,
        policy=policy,
        inputs=inputs,
        data_classification=data_classification,
        generated_at=generated_at,
        env=env,
    )
    return sign_statement(statement, private_key)


def _decode_envelope(envelope: Mapping[str, Any]) -> tuple[bytes, bytes, str]:
    if envelope.get("payloadType") != PAYLOAD_TYPE:
        raise EvidenceError("Unsupported DSSE payloadType.")
    signatures = envelope.get("signatures")
    if not isinstance(signatures, list) or len(signatures) != 1:
        raise EvidenceError("Evidence must contain exactly one trusted signature.")
    signature = signatures[0]
    if not isinstance(signature, Mapping):
        raise EvidenceError("Evidence signature is malformed.")
    try:
        payload = base64.b64decode(str(envelope.get("payload") or ""), validate=True)
        signature_bytes = base64.b64decode(str(signature.get("sig") or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EvidenceError("Evidence contains invalid base64.") from exc
    if not payload or len(payload) > MAX_EVIDENCE_BYTES:
        raise EvidenceError("Evidence payload is empty or exceeds the 1 MiB limit.")
    return payload, signature_bytes, str(signature.get("keyid") or "")


def verify_evidence_v2(
    envelope: Mapping[str, Any],
    public_key: str | bytes | Path | Ed25519PublicKey | None = None,
    *,
    trusted_policy_digest: str | None = None,
    expected_repository: str | None = None,
    expected_commit: str | None = None,
    expected_workflow: str | None = None,
    expected_inputs: Mapping[str, bytes] | None = None,
    max_age_seconds: int | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Verify signature, integrity, trust pins, execution identity, and age."""

    checks: dict[str, bool] = {}
    errors: list[str] = []
    statement: dict[str, Any] | None = None
    keyid = ""
    try:
        payload, signature, keyid = _decode_envelope(envelope)
        key = (
            public_key if isinstance(public_key, Ed25519PublicKey) else load_public_key(public_key)
        )
        trusted_keyid = public_key_id(key)
        checks["key_identity"] = keyid == trusted_keyid
        if not checks["key_identity"]:
            raise EvidenceError("Evidence keyid does not match the trusted public key.")
        key.verify(signature, dsse_pae(PAYLOAD_TYPE, payload))
        checks["signature"] = True
        decoded = json.loads(payload.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise EvidenceError("Evidence payload is not a JSON object.")
        statement = decoded
        predicate_candidate = statement.get("predicate")
        checks["contract"] = (
            statement.get("_type") == "https://in-toto.io/Statement/v1"
            and statement.get("predicateType") == PREDICATE_TYPE
            and isinstance(statement.get("subject"), list)
            and bool(statement.get("subject"))
            and isinstance(predicate_candidate, Mapping)
            and predicate_candidate.get("schema_version") == "2.0"
            and isinstance(predicate_candidate.get("assessment"), Mapping)
            and isinstance(predicate_candidate.get("assessment_digest"), Mapping)
            and isinstance(predicate_candidate.get("policy"), Mapping)
            and isinstance(predicate_candidate.get("context"), Mapping)
            and isinstance(predicate_candidate.get("provenance"), Mapping)
            and isinstance(predicate_candidate.get("inputs"), list)
        )
        if not checks["contract"]:
            raise EvidenceError("Evidence does not match Contract v2.")
        predicate = statement["predicate"]
        assessment = predicate.get("assessment")
        digest = predicate.get("assessment_digest", {}).get("sha256")
        checks["assessment_digest"] = isinstance(assessment, Mapping) and digest == sha256_digest(
            canonical_json(dict(assessment))
        )
        if not checks["assessment_digest"]:
            errors.append("Assessment digest mismatch.")
        policy_record = predicate.get("policy")
        policy_digest_record = (
            policy_record.get("digest") if isinstance(policy_record, Mapping) else {}
        )
        policy_digest = str(
            policy_digest_record.get("sha256") if isinstance(policy_digest_record, Mapping) else ""
        )
        if trusted_policy_digest is not None:
            checks["policy_trust"] = policy_digest == _normalize_digest(trusted_policy_digest)
            if not checks["policy_trust"]:
                errors.append("Policy digest is not trusted.")
        context = predicate.get("context") if isinstance(predicate.get("context"), Mapping) else {}
        provenance = (
            predicate.get("provenance") if isinstance(predicate.get("provenance"), Mapping) else {}
        )
        for check_name, expected, actual in (
            ("repository_identity", expected_repository, context.get("repository")),
            ("commit_identity", expected_commit, context.get("commit")),
            ("workflow_identity", expected_workflow, provenance.get("workflow")),
        ):
            if expected is not None:
                checks[check_name] = str(actual or "") == expected
                if not checks[check_name]:
                    errors.append(f"{check_name.replace('_', ' ').title()} mismatch.")
        input_records = predicate.get("inputs")
        recorded_inputs = {
            str(record.get("name")): str(record.get("digest", {}).get("sha256") or "")
            for record in (input_records if isinstance(input_records, list) else [])
            if isinstance(record, Mapping) and isinstance(record.get("digest"), Mapping)
        }
        for name, content in sorted((expected_inputs or {}).items()):
            check_name = f"input:{name}"
            checks[check_name] = recorded_inputs.get(name) == sha256_digest(content)
            if not checks[check_name]:
                errors.append(f"Input digest mismatch for {name!r}.")
        if max_age_seconds is not None:
            if max_age_seconds < 0:
                raise EvidenceError("max_age_seconds cannot be negative.")
            generated = _parse_timestamp(predicate.get("generated_at"))
            current = now or _utc_now()
            if current.tzinfo is None:
                raise EvidenceError("Verification time must include a timezone.")
            age = (current.astimezone(dt.timezone.utc) - generated).total_seconds()
            checks["freshness"] = -300 <= age <= max_age_seconds
            if not checks["freshness"]:
                errors.append("Evidence is outside the accepted freshness window.")
    except InvalidSignature:
        checks["signature"] = False
        errors.append("Evidence signature is invalid.")
    except (EvidenceError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    valid = bool(checks) and all(checks.values()) and not errors
    predicate = statement.get("predicate", {}) if isinstance(statement, Mapping) else {}
    context = predicate.get("context", {}) if isinstance(predicate, Mapping) else {}
    result_policy = predicate.get("policy") if isinstance(predicate, Mapping) else {}
    result_policy_digest = result_policy.get("digest") if isinstance(result_policy, Mapping) else {}
    return {
        "valid": valid,
        "status": "verified" if valid else "rejected",
        "contract": "preflightops-evidence-v2",
        "keyid": keyid,
        "checks": checks,
        "errors": errors,
        "subject": {
            "repository": context.get("repository") if isinstance(context, Mapping) else None,
            "commit": context.get("commit") if isinstance(context, Mapping) else None,
        },
        "policy_digest": (
            result_policy_digest.get("sha256")
            if isinstance(result_policy_digest, Mapping)
            else None
        ),
    }


def _named_paths(values: Sequence[str]) -> dict[str, bytes]:
    inputs: dict[str, bytes] = {}
    for value in values:
        name, separator, path = value.partition("=")
        if not separator or not name or not path:
            raise EvidenceError("Input bindings must use NAME=PATH.")
        if name in inputs:
            raise EvidenceError(f"Input name {name!r} was provided more than once.")
        try:
            inputs[name] = Path(path).read_bytes()
        except OSError as exc:
            raise EvidenceError(f"Unable to read input {name!r} from {path!r}.") from exc
    return inputs


def _write_json(path: str | Path, value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    Path(path).write_text(rendered, encoding="utf-8")


def evidence_cli(argv: Sequence[str]) -> int:
    """Entry point for ``preflightops evidence generate|verify``."""

    parser = argparse.ArgumentParser(prog="preflightops evidence")
    commands = parser.add_subparsers(dest="evidence_command", required=True)
    generate = commands.add_parser("generate", help="Generate signed DSSE evidence v2.")
    generate.add_argument("--assessment", required=True, help="Risk report JSON path.")
    generate.add_argument("--change", required=True, help="Change YAML/JSON path.")
    generate.add_argument("--output", required=True, help="DSSE evidence output path.")
    generate.add_argument("--private-key", default=None, help="Ed25519 PEM file path.")
    generate.add_argument("--policy", default=None, help="Resolved policy YAML/JSON path.")
    generate.add_argument("--input", action="append", default=[], metavar="NAME=PATH")
    generate.add_argument(
        "--classification",
        default="internal",
        choices=("public", "internal", "confidential", "restricted"),
    )
    generate.add_argument(
        "--legacy-output",
        default=None,
        help="Optional v1 evidence output during the compatibility window.",
    )

    verify = commands.add_parser("verify", help="Verify signed DSSE evidence v2.")
    verify.add_argument("--evidence", required=True, help="DSSE evidence JSON path.")
    verify.add_argument("--public-key", default=None, help="Trusted Ed25519 PEM file path.")
    verify.add_argument("--output", required=True, help="Machine-readable result JSON path.")
    verify.add_argument("--trusted-policy-digest", default=None)
    verify.add_argument("--expected-repository", default=None)
    verify.add_argument("--expected-commit", default=None)
    verify.add_argument("--expected-workflow", default=None)
    verify.add_argument("--expected-input", action="append", default=[], metavar="NAME=PATH")
    verify.add_argument("--max-age-seconds", type=int, default=None)

    args = parser.parse_args(list(argv))
    try:
        if args.evidence_command == "generate":
            assessment = _load_document(args.assessment)
            change = _load_document(args.change)
            policy = _load_document(args.policy) if args.policy else None
            if not isinstance(assessment, Mapping):
                raise EvidenceError("Assessment must be a JSON object.")
            if policy is not None and not isinstance(policy, Mapping):
                raise EvidenceError("Policy must be a YAML/JSON object.")
            envelope = generate_evidence_v2(
                assessment,
                change,
                private_key=args.private_key,
                policy=policy,
                inputs=_named_paths(args.input),
                data_classification=args.classification,
            )
            _write_json(args.output, envelope)
            if args.legacy_output:
                from .servicenow import build_evidence

                _write_json(args.legacy_output, build_evidence(assessment, change))
            print(f"Signed Evidence Contract v2 written to: {args.output}")
            if args.legacy_output:
                print(f"Compatibility Evidence Contract v1 written to: {args.legacy_output}")
            return 0
        envelope = _load_document(args.evidence)
        if not isinstance(envelope, Mapping):
            raise EvidenceError("Evidence envelope must be a JSON object.")
        result = verify_evidence_v2(
            envelope,
            args.public_key,
            trusted_policy_digest=args.trusted_policy_digest,
            expected_repository=args.expected_repository,
            expected_commit=args.expected_commit,
            expected_workflow=args.expected_workflow,
            expected_inputs=_named_paths(args.expected_input),
            max_age_seconds=args.max_age_seconds,
        )
        _write_json(args.output, result)
        print(f"Evidence verification {result['status']}; result written to: {args.output}")
        return 0 if result["valid"] else 3
    except (EvidenceError, OSError) as exc:
        print(f"Evidence error: {exc}", file=sys.stderr)
        return 2


__all__ = [
    "EvidenceError",
    "PAYLOAD_TYPE",
    "PREDICATE_TYPE",
    "build_statement_v2",
    "canonical_json",
    "dsse_pae",
    "evidence_cli",
    "generate_evidence_v2",
    "load_private_key",
    "load_public_key",
    "public_key_id",
    "redact_evidence",
    "sign_statement",
    "verify_evidence_v2",
]

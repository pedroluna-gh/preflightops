"""Evidence Contract v2 authenticity, compatibility, and replay controls."""

import base64
import datetime as dt
import json
from pathlib import Path

import jsonschema
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from preflightops import cli
from preflightops.evidence import (
    PAYLOAD_TYPE,
    EvidenceError,
    build_statement_v2,
    canonical_json,
    dsse_pae,
    generate_evidence_v2,
    public_key_id,
    verify_evidence_v2,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "evidence"
SCHEMAS = ROOT / "schemas"
NOW = dt.datetime(2026, 8, 28, 20, 0, tzinfo=dt.timezone.utc)
PROVENANCE = {
    "organization": "acme",
    "repository": "acme/payments-api",
    "commit": "a" * 40,
    "ref": "refs/heads/main",
    "workflow": "PreflightOps enterprise gate",
    "run_id": "42",
    "run_attempt": "1",
    "actor": "release-bot",
    "run_url": "https://github.com/acme/payments-api/actions/runs/42",
}


def _document(name):
    path = FIXTURES / name
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _key():
    # Deterministic test-only seed. It is not trusted or shipped as a product key.
    return Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))


def _envelope():
    return generate_evidence_v2(
        _document("assessment.json"),
        _document("change.yaml"),
        private_key=_key(),
        provenance=PROVENANCE,
        policy=_document("policy.json"),
        inputs={"terraform-plan": (FIXTURES / "terraform-plan.txt").read_bytes()},
        generated_at=NOW,
    )


def _statement(envelope):
    return json.loads(base64.b64decode(envelope["payload"]))


def test_dsse_pae_uses_length_delimited_encoding():
    assert dsse_pae("text/plain", b"hello") == b"DSSEv1 10 text/plain 5 hello"


def test_generated_envelope_and_statement_match_public_schemas():
    envelope = _envelope()
    envelope_schema = json.loads(
        (SCHEMAS / "evidence-dsse-v1.schema.json").read_text(encoding="utf-8")
    )
    statement_schema = json.loads(
        (SCHEMAS / "evidence-statement-v2.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(envelope, envelope_schema)
    jsonschema.validate(_statement(envelope), statement_schema)


def test_statement_is_complete_bounded_and_deterministically_redacted():
    first = build_statement_v2(
        _document("assessment.json"),
        _document("change.yaml"),
        provenance=PROVENANCE,
        policy=_document("policy.json"),
        generated_at=NOW,
        env={},
    )
    second = build_statement_v2(
        _document("assessment.json"),
        _document("change.yaml"),
        provenance=PROVENANCE,
        policy=_document("policy.json"),
        generated_at=NOW,
        env={},
    )
    assert canonical_json(first) == canonical_json(second)
    serialized = canonical_json(first)
    assert b"must-never-enter-evidence" not in serialized
    predicate = first["predicate"]
    assert predicate["context"]["repository"] == "acme/payments-api"
    assert predicate["context"]["commit"] == "a" * 40
    assert predicate["provenance"]["workflow"] == "PreflightOps enterprise gate"
    assert predicate["governance"]["changes_workflow_state"] is False
    assert predicate["governance"]["grants_approval"] is False


def test_verification_pins_signature_policy_execution_identity_input_and_age():
    envelope = _envelope()
    statement = _statement(envelope)
    policy_digest = statement["predicate"]["policy"]["digest"]["sha256"]
    result = verify_evidence_v2(
        envelope,
        _key().public_key(),
        trusted_policy_digest=f"sha256:{policy_digest}",
        expected_repository="acme/payments-api",
        expected_commit="a" * 40,
        expected_workflow="PreflightOps enterprise gate",
        expected_inputs={"terraform-plan": (FIXTURES / "terraform-plan.txt").read_bytes()},
        max_age_seconds=3600,
        now=NOW + dt.timedelta(minutes=5),
    )
    assert result["valid"] is True
    assert result["status"] == "verified"
    assert all(result["checks"].values())
    assert result["keyid"] == public_key_id(_key().public_key())


def test_modifying_one_payload_byte_invalidates_signature():
    envelope = _envelope()
    payload = bytearray(base64.b64decode(envelope["payload"]))
    payload[-2] ^= 1
    envelope["payload"] = base64.b64encode(payload).decode("ascii")
    result = verify_evidence_v2(envelope, _key().public_key())
    assert result["valid"] is False
    assert result["checks"]["signature"] is False
    assert "Evidence signature is invalid." in result["errors"]


def test_untrusted_policy_and_changed_input_fail_closed():
    result = verify_evidence_v2(
        _envelope(),
        _key().public_key(),
        trusted_policy_digest="0" * 64,
        expected_inputs={"terraform-plan": b"different input"},
    )
    assert result["valid"] is False
    assert result["checks"]["policy_trust"] is False
    assert result["checks"]["input:terraform-plan"] is False


def test_replayed_or_wrong_workflow_evidence_fails_closed():
    result = verify_evidence_v2(
        _envelope(),
        _key().public_key(),
        expected_workflow="untrusted workflow",
        max_age_seconds=60,
        now=NOW + dt.timedelta(hours=1),
    )
    assert result["valid"] is False
    assert result["checks"]["workflow_identity"] is False
    assert result["checks"]["freshness"] is False


def test_cli_generates_v2_and_v1_then_verifies_machine_readable_result(tmp_path):
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    private_path.write_bytes(
        _key().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        _key()
        .public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    envelope_path = tmp_path / "evidence-v2.dsse.json"
    legacy_path = tmp_path / "evidence-v1.json"
    generate_code = cli.main(
        [
            "evidence",
            "generate",
            "--assessment",
            str(FIXTURES / "assessment.json"),
            "--change",
            str(FIXTURES / "change.yaml"),
            "--policy",
            str(FIXTURES / "policy.json"),
            "--input",
            f"terraform-plan={FIXTURES / 'terraform-plan.txt'}",
            "--private-key",
            str(private_path),
            "--output",
            str(envelope_path),
            "--legacy-output",
            str(legacy_path),
        ]
    )
    assert generate_code == 0
    assert json.loads(legacy_path.read_text(encoding="utf-8"))["schema_version"] == "1.0"
    verification_path = tmp_path / "verification.json"
    verify_code = cli.main(
        [
            "evidence",
            "verify",
            "--evidence",
            str(envelope_path),
            "--public-key",
            str(public_path),
            "--output",
            str(verification_path),
            "--expected-input",
            f"terraform-plan={FIXTURES / 'terraform-plan.txt'}",
        ]
    )
    assert verify_code == 0
    assert json.loads(verification_path.read_text(encoding="utf-8"))["valid"] is True


def test_cli_returns_three_for_untrusted_evidence(tmp_path):
    envelope = _envelope()
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(envelope), encoding="utf-8")
    other_key = Ed25519PrivateKey.generate().public_key()
    public_path = tmp_path / "wrong-public.pem"
    public_path.write_bytes(
        other_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    result_path = tmp_path / "verification.json"
    code = cli.main(
        [
            "evidence",
            "verify",
            "--evidence",
            str(evidence_path),
            "--public-key",
            str(public_path),
            "--output",
            str(result_path),
        ]
    )
    assert code == 3
    assert json.loads(result_path.read_text(encoding="utf-8"))["valid"] is False


def test_payload_type_is_interoperable_in_toto_json():
    assert _envelope()["payloadType"] == PAYLOAD_TYPE


@pytest.mark.parametrize(
    "mutation,error",
    [
        (lambda envelope: envelope.update(payloadType="text/plain"), "payloadType"),
        (lambda envelope: envelope.update(payload="not base64!"), "base64"),
        (lambda envelope: envelope.update(signatures=[]), "exactly one"),
    ],
)
def test_malformed_dsse_envelopes_are_rejected_without_crashing(mutation, error):
    envelope = _envelope()
    mutation(envelope)
    result = verify_evidence_v2(envelope, _key().public_key())
    assert result["valid"] is False
    assert any(error in message for message in result["errors"])


def test_wrong_repository_and_commit_are_rejected():
    result = verify_evidence_v2(
        _envelope(),
        _key().public_key(),
        expected_repository="other/repository",
        expected_commit="b" * 40,
    )
    assert result["valid"] is False
    assert result["checks"]["repository_identity"] is False
    assert result["checks"]["commit_identity"] is False


def test_generation_rejects_unsupported_classification_and_naive_time():
    with pytest.raises(EvidenceError, match="classification"):
        build_statement_v2(_document("assessment.json"), data_classification="secret")
    with pytest.raises(EvidenceError, match="timezone"):
        build_statement_v2(
            _document("assessment.json"),
            generated_at=dt.datetime(2026, 8, 28, 20, 0),
        )


def test_verification_rejects_negative_freshness_limit():
    result = verify_evidence_v2(
        _envelope(),
        _key().public_key(),
        max_age_seconds=-1,
    )
    assert result["valid"] is False
    assert "max_age_seconds cannot be negative." in result["errors"]


def test_cli_fails_closed_when_signing_key_is_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("PREFLIGHTOPS_EVIDENCE_PRIVATE_KEY", raising=False)
    code = cli.main(
        [
            "evidence",
            "generate",
            "--assessment",
            str(FIXTURES / "assessment.json"),
            "--change",
            str(FIXTURES / "change.yaml"),
            "--output",
            str(tmp_path / "evidence.json"),
        ]
    )
    assert code == 2
    assert not (tmp_path / "evidence.json").exists()

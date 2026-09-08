"""Reusable lifecycle assertions and adversarial reference-provider tests."""

import threading
from dataclasses import replace

import pytest

from preflightops.provider_contract import ProviderContractError, ProviderEvidence
from preflightops.provider_runtime import (
    FakeProvider,
    ProviderCapabilities,
    ProviderRequest,
    ProviderRunner,
)


def evidence(control="monitoring"):
    return ProviderEvidence(
        "fake",
        "1",
        control,
        "PASS",
        "Approved evidence.",
        "ref-1",
        "2026-09-08T12:00:00Z",
        "2026-09-08T13:00:00Z",
        90,
    )


def request(**overrides):
    return ProviderRequest(
        **{
            "context_digest": "a" * 64,
            "configuration_digest": "b" * 64,
            "controls": ("monitoring",),
            "evaluated_at": "2026-09-08T12:30:00Z",
            **overrides,
        }
    )


def provider(*items):
    return FakeProvider(
        ProviderCapabilities("fake", "1", ("monitoring", "rollback")), tuple(items) or (evidence(),)
    )


def assert_provider_contract(factory):
    """Future provider factories can reuse this offline lifecycle contract."""
    first = factory()
    runner = ProviderRunner()
    result = runner.run(first, request())
    assert len(result) == 1
    assert result[0].status == "PASS"
    assert result[0].canonical_bytes() == runner.run(factory(), request())[0].canonical_bytes()
    cancelled = threading.Event()
    cancelled.set()
    errors = runner.run(factory(), request(), cancellation=cancelled)
    assert all(e.status == "ERROR" and e.error_code == "CANCELLED" for e in errors)


def test_fake_provider_contract():
    assert_provider_contract(provider)


def test_cache_is_context_scoped_and_expiry_aware():
    fake = provider()
    runner = ProviderRunner()
    runner.run(fake, request())
    runner.run(fake, request())
    assert fake.calls == 1 and not fake.opened
    runner.run(fake, request(context_digest="c" * 64))
    assert fake.calls == 2
    result = runner.run(fake, request(evaluated_at="2026-09-08T13:00:00Z"))
    assert fake.calls == 3
    assert result[0].status == "UNKNOWN" and result[0].error_code == "STALE"
    runner.run(fake, request(evaluated_at="2026-09-08T13:00:00Z"))
    assert fake.calls == 4


def test_cancellation_prevents_open_and_credential_access():
    fake = provider()
    cancelled = threading.Event()
    cancelled.set()

    def forbidden():
        pytest.fail("Credentials must not be queried")

    result = ProviderRunner().run(fake, request(), cancellation=cancelled, credentials=forbidden)
    assert result[0].error_code == "CANCELLED"
    assert fake.calls == 0 and not fake.opened


def test_late_results_fail_closed_and_release_resources():
    now = [0.0]

    class Late(FakeProvider):
        def collect(self, request, context):
            now[0] = 11
            return self.evidence

    fake = Late(provider().capabilities, (evidence(),))
    result = ProviderRunner(monotonic=lambda: now[0]).run(fake, request(timeout_seconds=10))
    assert result[0].error_code == "TIMEOUT"
    assert not fake.opened


def test_partial_failure_retains_completed_controls_and_redacts_error():
    class Partial(FakeProvider):
        def collect(self, request, context):
            yield evidence()
            raise RuntimeError("token=do-not-disclose")

    fake = Partial(provider().capabilities, ())
    result = ProviderRunner().run(fake, request(controls=("rollback", "monitoring")))
    assert [e.status for e in result] == ["PASS", "ERROR"]
    assert "do-not-disclose" not in repr(result)
    assert not fake.opened


def test_failure_after_all_results_cannot_disappear_or_enter_cache():
    class TerminalFailure(FakeProvider):
        def collect(self, request, context):
            self.calls += 1
            yield evidence()
            raise RuntimeError("token=do-not-disclose")

    fake = TerminalFailure(provider().capabilities, ())
    runner = ProviderRunner()
    for _ in range(2):
        result = runner.run(fake, request())
        assert result[0].status == "ERROR"
        assert result[0].error_code == "INTERNAL"
        assert "do-not-disclose" not in repr(result)
        assert not fake.opened
    assert fake.calls == 2


@pytest.mark.parametrize("status,code", [("FAIL", None), ("ERROR", "AUTH")])
def test_expired_negative_evidence_is_never_promoted(status, code):
    item = replace(evidence(), status=status, error_code=code, confidence=0)
    result = ProviderRunner().run(provider(item), request(evaluated_at="2026-09-08T13:00:00Z"))
    assert result[0].status == status
    assert result[0].confidence == 0
    assert result[0].error_code == code


@pytest.mark.parametrize(
    "items",
    [
        (evidence(), evidence()),
        (replace(evidence(), provider="impostor"),),
        (evidence("unsupported"),),
    ],
)
def test_identity_mismatch_and_duplicates_invalidate_response(items):
    class InvalidResponse(FakeProvider):
        def collect(self, request, context):
            return self.evidence

    fake = InvalidResponse(provider().capabilities, items)
    assert ProviderRunner().run(fake, request())[0].error_code == "INVALID_RESPONSE"


def test_missing_controls_are_not_pass():
    result = ProviderRunner().run(provider(), request(controls=("rollback", "monitoring")))
    assert result[1].status == "UNKNOWN" and result[1].error_code == "MISSING"


def test_cache_capacity_and_disabled_cache():
    fake = provider()
    runner = ProviderRunner(cache_capacity=1)
    runner.run(fake, request())
    runner.run(fake, request(context_digest="c" * 64))
    runner.run(fake, request())
    assert fake.calls == 3
    runner = ProviderRunner(cache_capacity=0)
    runner.run(fake, request())
    runner.run(fake, request())
    assert fake.calls == 5


@pytest.mark.parametrize("timeout", [True, 0, -1, 121, float("inf"), float("nan")])
def test_invalid_timeouts(timeout):
    with pytest.raises(ProviderContractError):
        request(timeout_seconds=timeout)

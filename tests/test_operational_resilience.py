"""Offline faults, privacy, concurrency, resource bounds and compatibility."""

import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jsonschema
import pytest

from preflightops import cli
from preflightops.bounded_input import load_yaml, read_text
from preflightops.changed_files import (
    classify_changed_files,
    load_auto_scanner_inputs,
    load_changed_files,
)
from preflightops.operational_probe import main as probe_main
from preflightops.operational_probe import run_probe
from preflightops.operations import OperationsError, OperationsRecorder
from preflightops.provider_runtime import (
    FakeProvider,
    ProviderContext,
    ProviderExecutionError,
    ProviderRunner,
)
from preflightops.zabbix_client import ZabbixClient, ZabbixResponse
from tests.test_provider_runtime import evidence, provider, request


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Operational tests must not use the network")

    monkeypatch.setattr(socket, "create_connection", forbidden)


def test_structured_events_have_fixed_cardinality_and_bounded_retention():
    recorder = OperationsRecorder("a" * 32, capacity=2)
    for _ in range(4):
        recorder.record(
            kind="provider",
            outcome="degraded",
            duration_seconds=0.02,
            controls={"ERROR": 1},
            errors={"AUTH": 1},
            cache="miss",
        )
    doc = recorder.document()
    assert len(doc["events"]) == 2
    assert doc["metrics"]["events_total"] == 4
    assert doc["metrics"]["events_dropped"] == 2
    assert doc["metrics"]["provider_errors_AUTH"] == 4
    assert doc["metrics"]["latency_provider_le_100_ms"] == 4
    assert doc["metrics"]["retries_total"] == 0
    doc["events"][0]["errors"]["AUTH"] = 999
    assert recorder.document()["events"][0]["errors"]["AUTH"] == 1
    assert "a" * 32 not in " ".join(doc["metrics"])
    assert len(recorder.serialize()) < 10_000


def test_operations_schema_rejects_extra_labels_and_raw_payloads():
    recorder = OperationsRecorder()
    recorder.record(
        kind="cli",
        outcome="blocked",
        duration_seconds=1,
        assessment_id="urn:preflightops:assessment:sha256:" + "a" * 64,
        risk="CRITICAL",
    )
    schema = json.loads(Path("schemas/operations-v1.schema.json").read_text(encoding="utf-8"))
    doc = recorder.document()
    jsonschema.validate(doc, schema)
    doc["events"][0]["payload"] = "synthetic-sensitive-marker"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, schema)
    doc = recorder.document()
    doc["metrics"]["customer_label"] = 1
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, schema)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"correlation_id": "private-service"},
        {"capacity": 0},
        {"capacity": 257},
        {"capacity": True},
        {"correlation_id": "https://private.example/?token=secret"},
    ],
)
def test_recorder_rejects_unapproved_identifiers_and_limits(kwargs):
    with pytest.raises(OperationsError):
        OperationsRecorder(**kwargs)


@pytest.mark.parametrize(
    "override",
    [
        {"kind": "private-service"},
        {"outcome": "PASS"},
        {"risk": "approve"},
        {"cache": "private-url"},
        {"duration_seconds": float("nan")},
        {"duration_seconds": -1},
        {"duration_seconds": True},
        {"controls": {"arbitrary-label": 1}},
        {"errors": {"token=secret": 1}},
        {"controls": {"PASS": True}},
        {"controls": {"PASS": -1}},
        {"assessment_id": "secret-payload"},
    ],
)
def test_recorder_cannot_be_used_as_payload_logger(override):
    recorder = OperationsRecorder()
    with pytest.raises(OperationsError):
        recorder.record(
            **{"kind": "cli", "outcome": "completed", "duration_seconds": 0, **override}
        )
    assert recorder.document()["metrics"]["events_total"] == 0


def test_provider_telemetry_is_additive_and_cache_replay_is_identical():
    recorder = OperationsRecorder()
    runner = ProviderRunner(recorder=recorder)
    fake = provider()
    baseline = ProviderRunner().run(provider(), request())
    assert runner.run(fake, request()) == baseline
    assert runner.run(fake, request()) == baseline
    assert fake.calls == 1
    metrics = recorder.document()["metrics"]
    assert metrics["cache_hit"] == metrics["cache_miss"] == 1
    assert metrics["controls_PASS"] == 2
    assert metrics["operations_provider_degraded"] == 0


def test_transport_retries_are_measured_without_changing_retry_policy():
    recorder = OperationsRecorder()
    clock = [0.0]

    class Event:
        def is_set(self):
            return False

        def wait(self, delay):
            clock[0] += delay

    class Transport:
        calls = 0

        def post(self, **kwargs):
            self.calls += 1
            return (
                ZabbixResponse(503, b"")
                if self.calls < 3
                else ZabbixResponse(200, b'{"jsonrpc":"2.0","id":1,"result":"7.0.30"}')
            )

    transport = Transport()
    context = ProviderContext(10, Event(), lambda: None, lambda: clock[0], recorder)
    assert ZabbixClient("unused", transport).discover(context) == "7.0.30"
    assert transport.calls == 3
    assert recorder.document()["metrics"]["retries_total"] == 2


@pytest.mark.parametrize("code", ["TIMEOUT", "RATE_LIMIT", "AUTH", "UNAVAILABLE", "INTERNAL"])
def test_repeated_faults_are_visible_and_never_cached_as_pass(code):
    class Fault(FakeProvider):
        def collect(self, request, context):
            self.calls += 1
            if code == "INTERNAL":
                raise RuntimeError("token=synthetic-secret https://private.example/path")
            raise ProviderExecutionError(code)

    fake = Fault(provider().capabilities, ())
    recorder = OperationsRecorder()
    runner = ProviderRunner(recorder=recorder)
    for _ in range(2):
        output = runner.run(fake, request())
        assert output[0].status == "ERROR" and output[0].error_code == code
    assert fake.calls == 2 and not fake.opened
    assert recorder.document()["metrics"][f"provider_errors_{code}"] == 2
    assert recorder.document()["metrics"]["operations_provider_degraded"] == 2
    assert "synthetic-secret" not in recorder.serialize()
    assert "private.example" not in recorder.serialize()


def test_corrupt_partial_expired_and_missing_evidence_remain_degraded():
    class Corrupt(FakeProvider):
        def collect(self, request, context):
            return (object(),)

    recorder = OperationsRecorder()
    runner = ProviderRunner(recorder=recorder)
    bad = runner.run(Corrupt(provider().capabilities, ()), request())
    assert bad[0].error_code == "INVALID_RESPONSE"
    partial = runner.run(provider(), request(controls=("monitoring", "rollback")))
    assert [e.status for e in partial] == ["PASS", "UNKNOWN"]
    stale = runner.run(provider(), request(evaluated_at="2026-09-08T14:00:00Z"))
    assert stale[0].status == "UNKNOWN"
    assert recorder.document()["metrics"]["operations_provider_degraded"] == 3


def test_waiting_request_expires_without_touching_active_provider():
    opened = threading.Event()
    release = threading.Event()

    class Busy(FakeProvider):
        def collect(self, request, context):
            opened.set()
            assert release.wait(5)
            return self.evidence

    busy = Busy(provider().capabilities, (evidence(),))
    waiting = provider()
    recorder = OperationsRecorder()
    runner = ProviderRunner(recorder=recorder)
    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(runner.run, busy, request())
        try:
            assert opened.wait(2)
            second = pool.submit(runner.run, waiting, request(timeout_seconds=0.02))
            result = second.result(timeout=2)
            assert result[0].status == "ERROR" and result[0].error_code == "TIMEOUT"
            assert waiting.calls == 0 and busy.opened
        finally:
            release.set()
        assert active.result(timeout=2)[0].status == "PASS"
    assert not busy.opened
    assert recorder.document()["metrics"]["provider_errors_TIMEOUT"] == 1


def test_concurrent_repeated_assessments_have_one_collection_and_bounded_events():
    recorder = OperationsRecorder(capacity=8)
    runner = ProviderRunner(recorder=recorder)
    fake = provider()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: runner.run(fake, request()), range(64)))
    assert all(result == results[0] for result in results)
    assert fake.calls == 1
    doc = recorder.document()
    assert doc["metrics"]["cache_hit"] == 63
    assert doc["metrics"]["events_dropped"] == 56
    assert len(doc["events"]) == 8


@pytest.mark.parametrize(
    "content",
    [
        "a: &a [*a]",
        "a: " + "[" * 66 + "]" * 66,
        "a: [ token=synthetic-secret",
        "a: &a []\nb: [" + "*a," * 129 + "]",
    ],
)
def test_yaml_adversarial_inputs_are_rejected_without_content(tmp_path, content):
    path = tmp_path / "input.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError) as error:
        load_yaml(path)
    assert "synthetic-secret" not in str(error.value)


def test_valid_alias_compatibility_and_byte_bound(tmp_path):
    path = tmp_path / "input.yaml"
    path.write_text("a: &a [1, 2]\nb: *a\n", encoding="utf-8")
    assert load_yaml(path) == {"a": [1, 2], "b": [1, 2]}
    with pytest.raises(ValueError, match="byte limit"):
        read_text(path, max_bytes=4)
    path.write_bytes(b"\xff")
    with pytest.raises(ValueError, match="UTF-8"):
        read_text(path)
    with pytest.raises(ValueError, match="regular file"):
        read_text(tmp_path)


def test_changed_file_and_combined_input_budgets(tmp_path):
    path = tmp_path / "manifest.txt"
    path.write_text("\n".join(f"{n}.txt" for n in range(3001)), encoding="utf-8")
    with pytest.raises(ValueError, match="3000"):
        load_changed_files(path)
    with pytest.raises(ValueError, match="3000"):
        classify_changed_files(str(n) for n in range(3001))
    with pytest.raises(ValueError, match="path budget"):
        classify_changed_files(["a" * 4097])
    manifest = tmp_path / "k8s.yaml"
    manifest.write_text("x" * (4 * 1024 * 1024), encoding="utf-8")
    with pytest.raises(ValueError, match="4 MiB"):
        load_auto_scanner_inputs(
            {"auto_inputs": {"kubernetes_manifest_candidates": ["k8s.yaml"]}}, tmp_path
        )


def args_for(tmp_path):
    return [
        "--services",
        "examples/services-low-risk.yaml",
        "--change",
        "examples/change-low-risk.yaml",
        "--output",
        str(tmp_path / "report.md"),
    ]


def test_cli_telemetry_preserves_legacy_bytes_and_never_approves(tmp_path):
    args = args_for(tmp_path)
    assert cli.main(args) == 0
    baseline = (tmp_path / "report.md").read_bytes()
    telemetry = tmp_path / "operations.json"
    assert (
        cli.main([*args, "--telemetry-output", str(telemetry), "--correlation-id", "a" * 32]) == 0
    )
    assert (tmp_path / "report.md").read_bytes() == baseline
    doc = json.loads(telemetry.read_text())
    assert doc["metrics"]["verdict_LOW"] == 1
    assert doc["events"][0]["assessment_id"] is None
    assert "reporting-api" not in telemetry.read_text()
    assert "data-platform" not in telemetry.read_text()
    preserved = telemetry.read_bytes()
    assert cli.main([*args, "--telemetry-output", str(telemetry)]) == 2
    assert telemetry.read_bytes() == preserved


def test_cli_error_and_destination_collision_are_fail_closed(tmp_path):
    args = args_for(tmp_path)
    output = tmp_path / "operations.json"
    assert (
        cli.main(
            ["--services", "missing", "--change", "missing", "--telemetry-output", str(output)]
        )
        == 2
    )
    assert json.loads(output.read_text())["metrics"]["operations_cli_error"] == 1
    assert cli.main([*args, "--telemetry-output", str(tmp_path / "report.md")]) == 2
    assert not (tmp_path / "report.md").exists()
    assert cli.main([*args, "--correlation-id", "a" * 32]) == 2


def test_critical_cli_remains_blocked_and_render_links_valid_assessment(tmp_path):
    telemetry = tmp_path / "critical-ops.json"
    assert (
        cli.main(
            [
                "--services",
                "examples/services-critical-risk.yaml",
                "--change",
                "examples/change-critical-risk.yaml",
                "--terraform",
                "examples/terraform-critical.txt",
                "--output",
                str(tmp_path / "critical.md"),
                "--telemetry-output",
                str(telemetry),
            ]
        )
        == 1
    )
    assert json.loads(telemetry.read_text())["events"][0]["outcome"] == "blocked"
    contract = Path("tests/fixtures/assessment/assessment-v1.golden.json")
    output = tmp_path / "report-ops.json"
    assert (
        cli.main(
            [
                "report",
                "render",
                "--assessment",
                str(contract),
                "--json-output",
                str(tmp_path / "rendered.json"),
                "--telemetry-output",
                str(output),
            ]
        )
        == 0
    )
    assert (
        json.loads(output.read_text())["events"][0]["assessment_id"]
        == json.loads(contract.read_text(encoding="utf-8"))["assessment_id"]
    )


def test_cli_persistence_failure_and_parser_error_are_not_success(tmp_path, monkeypatch):
    original = Path.open
    target = tmp_path / "ops.json"

    class BrokenWriter:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def write(self, content):
            raise OSError("synthetic-secret-disk-error")

        def close(self):
            pass

    def patched(path, *args, **kwargs):
        return BrokenWriter() if path == target else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", patched)
    assert cli.main([*args_for(tmp_path), "--telemetry-output", str(target)]) == 2
    monkeypatch.setattr(Path, "open", original)
    with pytest.raises(SystemExit) as result:
        cli.main(["--services", "only-one-required-input", "--telemetry-output", str(target)])
    assert result.value.code == 2
    assert json.loads(target.read_text())["events"][0]["outcome"] == "error"


def test_inspection_budget_and_json_file_count_are_bounded(tmp_path):
    manifest = tmp_path / "files.json"
    manifest.write_text(json.dumps(["x"] * 3001))
    with pytest.raises(ValueError, match="3000"):
        load_changed_files(manifest)
    large = tmp_path / "terraform-plan.json"
    with large.open("wb") as stream:
        stream.truncate(33 * 1024 * 1024)
    with pytest.raises(ValueError, match="32 MiB"):
        classify_changed_files([large.name], tmp_path)


def test_probe_is_measurable_reproducible_and_preserves_outputs(tmp_path, capsys):
    result = run_probe(20)
    assert result["passed"] and result["replay_mismatches"] == 0
    assert result["latency_ms"]["p95"] >= 0 and result["throughput_per_second"] > 0
    assert result["peak_python_bytes"] > 0
    output = tmp_path / "probe.json"
    assert probe_main(["--iterations", "10", "--output", str(output)]) == 0
    assert probe_main(["--iterations", "10", "--output", str(output)]) == 2
    assert probe_main(["--iterations", "1"]) == 2
    assert "token" not in capsys.readouterr().out

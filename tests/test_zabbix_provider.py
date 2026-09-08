"""Deterministic, synthetic JSON-RPC inventory; no network or real credentials."""

import copy
import datetime as dt
import json
from dataclasses import replace

import pytest
from test_provider_runtime import assert_provider_contract

from preflightops.provider_contract import ProviderContractError
from preflightops.provider_runtime import ProviderRequest, ProviderRunner
from preflightops.zabbix_client import ZabbixResponse
from preflightops.zabbix_provider import KINDS, ZabbixConfig, ZabbixProvider
from preflightops.zabbix_transport import ZabbixEndpoint

AT = "2026-09-08T12:00:00Z"
NOW = int(dt.datetime.fromisoformat(AT).timestamp())


def credentials():
    return "synthetic-test-token-0001"


def config(**changes):
    return replace(
        ZabbixConfig(
            ZabbixEndpoint("https://example.test/api_jsonrpc.php", "8.8.8.8"),
            "source-1",
            "42",
            ("51",),
            ("61",),
            retries=0,
            min_interval_ms=1,
        ),
        **changes,
    )


def request(cfg, kinds=KINDS):
    return ProviderRequest("a" * 64, cfg.digest, tuple("source-1." + k for k in kinds), AT)


class Inventory:
    def __init__(self, **overrides):
        self.results = {
            "apiinfo.version": "7.0.30",
            "host.get": [
                {
                    "hostid": "42",
                    "status": "0",
                    "maintenance_status": "0",
                    "groups": [{"groupid": "91"}],
                    "hostgroups": [{"groupid": "91"}],
                }
            ],
            "trigger.get": [{"triggerid": "51", "status": "0", "state": "0", "value": "0"}],
            "item.get": [
                {
                    "itemid": "61",
                    "hostid": "42",
                    "status": "0",
                    "state": "0",
                    "lastclock": str(NOW - 10),
                }
            ],
            "maintenance.get": [],
            "problem.get": [],
            "event.get": [],
            **overrides,
        }
        self.calls = []
        self.closed = False

    def post(self, **kwargs):
        payload = json.loads(kwargs["body"])
        self.calls.append(payload)
        result = self.results[payload["method"]]
        if callable(result):
            result = result(payload["params"])
        if isinstance(result, ZabbixResponse):
            return result
        return ZabbixResponse(
            200, json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode()
        )

    def close(self):
        self.closed = True


def run(inventory=None, cfg=None, kinds=KINDS):
    cfg = cfg or config()
    inventory = inventory or Inventory()
    result = ProviderRunner().run(
        ZabbixProvider(cfg, transport=inventory),
        request(cfg, kinds),
        credentials=credentials,
    )
    assert inventory.closed
    return {e.control_id.split(".")[-1]: e for e in result}


@pytest.mark.parametrize("version", ["6.0.42", "7.0.30", "7.4.1"])
def test_common_contract_and_independent_replay(version):
    cfg = config()
    assert_provider_contract(
        lambda: ZabbixProvider(cfg, transport=Inventory(**{"apiinfo.version": version})),
        request(cfg),
        credentials=credentials,
    )


def test_freshness_expires_when_oldest_sample_does():
    inventory = Inventory()
    inventory.results["item.get"][0]["lastclock"] = str(NOW - 299)
    value = run(inventory, kinds=("freshness",))["freshness"]
    assert value.status == "PASS"
    assert value.valid_until == "2026-09-08T12:00:01Z"
    assert value.effective_status(value.valid_until) == "UNKNOWN"


@pytest.mark.parametrize(
    "age,code", [(300, "STALE"), (301, "STALE"), (NOW, "STALE"), (-1, "FUTURE")]
)
def test_sample_age_is_not_query_age(age, code):
    inventory = Inventory()
    inventory.results["item.get"][0]["lastclock"] = str(NOW - age)
    value = run(inventory, kinds=("freshness",))["freshness"]
    assert value.status == "UNKNOWN" and value.error_code == code and value.confidence == 0


@pytest.mark.parametrize(
    "method,kind", [("host.get", "host"), ("trigger.get", "triggers"), ("item.get", "freshness")]
)
def test_missing_expected_objects_never_pass(method, kind):
    value = run(Inventory(**{method: []}), kinds=(kind,))[kind]
    assert value.status == "UNKNOWN" and value.error_code == "MISSING"


def test_existing_host_does_not_claim_trigger_coverage():
    result = run(Inventory(**{"trigger.get": []}))
    assert result["host"].status == "PASS"
    assert result["triggers"].status == "UNKNOWN"
    assert result["events"].status == "UNKNOWN"


@pytest.mark.parametrize(
    "method,kind,field,value,status",
    [
        ("host.get", "host", "status", "1", "FAIL"),
        ("trigger.get", "triggers", "status", "1", "FAIL"),
        ("trigger.get", "triggers", "value", "1", "FAIL"),
        ("trigger.get", "triggers", "state", "1", "UNKNOWN"),
        ("item.get", "freshness", "state", "1", "FAIL"),
        ("item.get", "freshness", "status", "1", "FAIL"),
        ("host.get", "maintenance", "maintenance_status", "1", "FAIL"),
    ],
)
def test_observed_states_are_not_approvals(method, kind, field, value, status):
    inventory = Inventory()
    inventory.results[method][0][field] = value
    assert run(inventory, kinds=(kind,))[kind].status == status


def test_recurring_definition_is_not_assumed_effective():
    inventory = Inventory(
        **{
            "maintenance.get": [
                {
                    "maintenanceid": "71",
                    "active_since": str(NOW - 10),
                    "active_till": str(NOW + 10),
                    "hostgroups": [],
                }
            ]
        }
    )
    result = run(inventory, kinds=("maintenance",))["maintenance"]
    assert result.status == "UNKNOWN"


@pytest.mark.parametrize(
    "version,selection,key",
    [
        ("6.0.42", "selectGroups", "groups"),
        ("7.0.30", "selectHostGroups", "hostgroups"),
        ("7.4.1", "selectHostGroups", "hostgroups"),
    ],
)
def test_group_assigned_maintenance_is_not_omitted(version, selection, key):
    def maintenance(params):
        if "hostids" in params:
            return []
        assert params["groupids"] == ["91"]
        assert params[selection] == ["groupid"]
        return [
            {
                "maintenanceid": "71",
                "active_since": str(NOW - 10),
                "active_till": str(NOW + 10),
                key: [{"groupid": "91"}],
            }
        ]

    inventory = Inventory(**{"apiinfo.version": version, "maintenance.get": maintenance})
    value = run(inventory, kinds=("maintenance",))["maintenance"]
    assert value.status == "UNKNOWN"
    host_call = next(c for c in inventory.calls if c["method"] == "host.get")
    assert host_call["params"][selection] == ["groupid"]


def test_other_host_maintenance_in_same_group_is_not_applied():
    def maintenance(params):
        if "hostids" in params:
            return []
        return [
            {
                "maintenanceid": "71",
                "active_since": str(NOW - 10),
                "active_till": str(NOW + 10),
                "hostgroups": [],
            }
        ]

    value = run(Inventory(**{"maintenance.get": maintenance}), kinds=("maintenance",))[
        "maintenance"
    ]
    assert value.status == "PASS"


@pytest.mark.parametrize("groups", [None, [], [{"groupid": "91"}] * 2])
def test_missing_or_invalid_group_scope_never_passes(groups):
    inventory = Inventory()
    inventory.results["host.get"][0]["hostgroups"] = groups
    value = run(inventory, kinds=("maintenance",))["maintenance"]
    assert value.status in {"UNKNOWN", "ERROR"}


@pytest.mark.parametrize(
    "rows",
    [
        None,
        {},
        [None],
        [{"hostid": "42"}],
        [{"hostid": "43", "status": "0"}],
        [{"hostid": "42", "status": True}],
        [{"hostid": "42", "status": "2"}],
        [{"hostid": "042", "status": "0"}],
        [{"hostid": "42", "status": "0"}] * 2,
    ],
)
def test_malformed_host_response_fails_closed(rows):
    value = run(Inventory(**{"host.get": rows}), kinds=("host",))["host"]
    assert value.status == "ERROR" and value.error_code == "INVALID_RESPONSE"


def test_auth_error_isolated_and_redacted():
    inventory = Inventory(
        **{"item.get": ZabbixResponse(403, b"secret-token https://internal.invalid")}
    )
    result = run(inventory)
    assert result["host"].status == "PASS"
    assert result["freshness"].error_code == "AUTH"
    encoded = b"".join(e.canonical_bytes() for e in result.values())
    for forbidden in (
        b"secret-token",
        b"internal.invalid",
        b"example.test",
        credentials().encode(),
    ):
        assert forbidden not in encoded


@pytest.mark.parametrize("kind", ["problems", "events"])
def test_keyset_pagination_progress_and_complete_negative_evidence(kind):
    rows = [{"eventid": str(i), "objectid": "51", "clock": str(NOW - 1)} for i in (81, 82)]

    def page(params):
        return [row for row in rows if int(row["eventid"]) >= int(params["eventid_from"])][:1]

    inventory = Inventory(**{("problem.get" if kind == "problems" else "event.get"): page})
    result = run(inventory, config(page_size=1), kinds=(kind,))[kind]
    assert result.status == "FAIL"
    pages = [
        c["params"]["eventid_from"]
        for c in inventory.calls
        if c["method"] in {"event.get", "problem.get"}
    ]
    assert pages == ["1", "82", "83"]


@pytest.mark.parametrize(
    "row",
    [
        {"eventid": "81", "objectid": "51", "clock": str(NOW)},
        {"eventid": "81", "objectid": "99", "clock": str(NOW)},
        {"eventid": "81", "objectid": "51", "clock": str(NOW + 1)},
    ],
)
def test_repeated_out_of_scope_or_future_events_fail_closed(row):
    value = run(Inventory(**{"event.get": [row]}), config(page_size=1), kinds=("events",))["events"]
    assert value.status == "ERROR"


def test_page_budget_exhaustion_never_claims_complete():
    value = run(
        Inventory(**{"event.get": [{"eventid": "81", "objectid": "51", "clock": str(NOW)}]}),
        config(page_size=1, max_pages=1),
        kinds=("events",),
    )["events"]
    assert value.status == "ERROR"


@pytest.mark.parametrize("kind", ["triggers", "freshness", "problems", "events"])
def test_disabled_host_prevents_favorable_monitoring(kind):
    inventory = Inventory()
    inventory.results["host.get"][0]["status"] = "1"
    value = run(inventory, kinds=(kind,))[kind]
    assert value.status == "ERROR" and value.error_code == "UNAVAILABLE"


@pytest.mark.parametrize("kind", ["problems", "events"])
@pytest.mark.parametrize("field", ["status", "state"])
def test_empty_event_query_does_not_hide_disabled_or_unknown_trigger(kind, field):
    inventory = Inventory()
    inventory.results["trigger.get"][0][field] = "1"
    value = run(inventory, kinds=(kind,))[kind]
    assert value.status == "UNKNOWN" and value.error_code == "UNAVAILABLE"
    assert not any(c["method"] in {"event.get", "problem.get"} for c in inventory.calls)


def test_config_digest_binding_and_no_mutation():
    cfg = config()
    assert cfg.digest == copy.deepcopy(cfg).digest
    assert cfg.digest != config(max_pages=2).digest
    inventory = Inventory()
    result = ProviderRunner().run(
        ZabbixProvider(cfg, transport=inventory),
        replace(request(cfg), configuration_digest="b" * 64),
        credentials=credentials,
    )
    assert all(e.status == "ERROR" for e in result)
    assert not inventory.calls


@pytest.mark.parametrize(
    "changes",
    [
        {"ttl_seconds": True},
        {"max_pages": 0},
        {"trigger_ids": ("2", "1")},
        {"item_ids": ("1", "1")},
        {"host_id": "0"},
    ],
)
def test_invalid_configuration(changes):
    with pytest.raises(ProviderContractError):
        config(**changes)

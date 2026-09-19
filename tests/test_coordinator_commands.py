"""Behavioral tests for the ZHA transport and the coordinator's PIN operations.

The ZHA seams are tested on ZhaLockTransport directly: the retry loop in
send, the auto-wake and its registry lookup, the cluster chain walk and the
capabilities read. The stubs replicate the object shapes zha.py assumes,
so these tests lock our retry and traversal logic, not ZHA compatibility:
a ZHA rename of device_proxies would pass here and only show up on a real
Home Assistant instance. The coordinator's PIN operations run against a
fake transport that records what would go out.

CI installs only pytest, so the tests are sync and drive the coroutines
with asyncio.run().
"""
from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest import mock

import pytest
from zigpy.exceptions import DeliveryError, ZigbeeException

from .conftest import load_component_module

coordinator_mod = load_component_module("coordinator")
zha_mod = load_component_module("zha")
const_mod = load_component_module("const")

# Letters in the ieee so the case-insensitivity tests compare something.
IEEE = "f4:ce:36:0a:00:11:22:aa"
# ZHA keys device_proxies by EUI64 objects whose str() may differ in case.
IEEE_ZHA_KEY = IEEE.upper()
OTHER_IEEE = "aa:bb:cc:dd:ee:ff:00:11"
DOORLOCK_CLUSTER_ID = 0x0101
PIN = "83729164"
ZHA_ENTRY_ID = "zha-entry"


class FakeConfigEntry:
    def __init__(self, options=None, ieee=IEEE):
        self.data = {"ieee": ieee}
        self.options = dict(options or {})
        self.background = []

    def async_create_background_task(self, hass, target, name):
        """Keep the coroutine so a test can run it when it chooses."""
        self.background.append(target)

    def run_background(self):
        while self.background:
            _run(self.background.pop(0))


class FakeConfigEntries:
    """Replicates HA's change detection in async_update_entry."""

    def __init__(self):
        self.written = []

    def async_update_entry(self, entry, *, options):
        if entry.options == options:
            return False
        entry.options = options
        self.written.append(json.loads(json.dumps(options)))
        return True

    def async_entries(self, domain):
        """One ZHA config entry, which owns the ZHA devices."""
        return [SimpleNamespace(entry_id=ZHA_ENTRY_ID, domain="zha")] if domain == "zha" else []


class FakeRegistryEntry:
    def __init__(self, entity_id, platform, device_id, disabled_by=None):
        self.entity_id = entity_id
        self.domain = entity_id.split(".")[0]
        self.platform = platform
        self.device_id = device_id
        self.disabled_by = disabled_by


class FakeEntityRegistry:
    def __init__(self, entities=()):
        self.entities = {e.entity_id: e for e in entities}


class FakeDeviceRegistry:
    """Holds devices; the conftest stub lists them per config entry."""

    def __init__(self, devices=()):
        self.devices = list(devices)


def _zha_device(ieee=IEEE, device_id="dev-front", config_entry_id=ZHA_ENTRY_ID):
    # ZHA registers str(EUI64), which zigpy renders in lowercase.
    return SimpleNamespace(
        id=device_id,
        connections={("zigbee", ieee.lower())},
        config_entries={config_entry_id},
    )


def _lock_entity(entity_id="lock.front_door", device_id="dev-front", **kwargs):
    return FakeRegistryEntry(entity_id, "zha", device_id, **kwargs)


class ScriptedServices:
    """Service bus where each zha command call consumes one scripted effect.

    None means success, an exception instance is raised. lock.lock calls
    (the auto-wake) are recorded separately and succeed unless wake_error
    is set.
    """

    def __init__(self, zha_effects=(), wake_error=None):
        self.zha_effects = list(zha_effects)
        self.wake_error = wake_error
        self.zha_calls = []
        self.lock_calls = []

    async def async_call(self, domain, service, data, blocking=False):
        if domain == "zha":
            self.zha_calls.append(data)
            effect = self.zha_effects.pop(0) if self.zha_effects else None
            if effect is not None:
                raise effect
        elif domain == "lock":
            self.lock_calls.append(data)
            if self.wake_error is not None:
                raise self.wake_error


class FakeHass:
    def __init__(self, zha_effects=(), wake_error=None, entities=None, devices=None):
        self.config_entries = FakeConfigEntries()
        self.services = ScriptedServices(zha_effects, wake_error)
        self.device_registry = FakeDeviceRegistry(
            devices if devices is not None else [_zha_device()]
        )
        self.entity_registry = FakeEntityRegistry(
            entities if entities is not None else [_lock_entity()]
        )
        self.data = {}


async def _no_sleep(_seconds):
    return None


def _run(coro):
    # wake() sleeps one real second after actuating, pointless in tests.
    with mock.patch("asyncio.sleep", _no_sleep):
        return asyncio.run(coro)


def _make(options=None, transport=None, **hass_kwargs):
    hass = FakeHass(**hass_kwargs)
    entry = FakeConfigEntry(options)
    return hass, entry, coordinator_mod.NimlyCoordinator(hass, entry, transport)


def _transport(ieee=IEEE, **hass_kwargs):
    hass = FakeHass(**hass_kwargs)
    return hass, zha_mod.ZhaLockTransport(hass, ieee)


class FakeTransport:
    """Records each command the coordinator sends and reports it delivered."""

    def __init__(self, result=True, capabilities=None):
        self.result = result
        self.capabilities = capabilities
        self.sent = []
        self.reads = 0

    async def send(self, command, params):
        self.sent.append((command, params))
        return self.result

    async def read_capabilities(self):
        self.reads += 1
        return self.capabilities


def _zha_topology(cluster, ieee_key=IEEE_ZHA_KEY):
    """Proxy -> device -> zigpy device, clusters only on the deepest level.

    Mirrors the real chain (ZHADeviceProxy -> Device -> CustomDeviceV2) so
    the tests fail if the walk stops at the wrapper layers.
    """
    ep0 = SimpleNamespace(in_clusters={})
    in_clusters = {DOORLOCK_CLUSTER_ID: cluster} if cluster is not None else {}
    ep11 = SimpleNamespace(in_clusters=in_clusters)
    zigpy_device = SimpleNamespace(endpoints={0: ep0, 11: ep11})
    zha_device = SimpleNamespace(device=zigpy_device)
    proxy = SimpleNamespace(device=zha_device)
    gateway_proxy = SimpleNamespace(device_proxies={ieee_key: proxy})
    return SimpleNamespace(gateway_proxy=gateway_proxy)


class FakeCluster:
    def __init__(self, result=None, error=None, endpoint_id=None):
        self._result = result
        self._error = error
        self.requested = []
        if endpoint_id is not None:
            self.endpoint = SimpleNamespace(endpoint_id=endpoint_id)

    async def read_attributes(self, attr_ids):
        self.requested.append(list(attr_ids))
        if self._error is not None:
            raise self._error
        return self._result


def _coordinator_reading(cluster, options=None):
    """A coordinator whose real transport reads from the given cluster.

    The cluster lookup has its own tests in TestGetCluster, bypassing it
    keeps the ZHA topology stub out of what these tests are about.
    """
    hass, transport = _transport()
    transport.cluster = lambda: cluster
    entry = FakeConfigEntry(options)
    return hass, entry, coordinator_mod.NimlyCoordinator(hass, entry, transport)


class TestSendClusterCommand:
    """Retry semantics, success semantics and the Nimly IndexError quirk."""

    def test_wire_contract(self):
        # What the lock actually receives through ZHA's service. No ZHA in
        # hass.data, so no cluster to read the endpoint from: 11 is the
        # fallback every Onesti lock seen so far uses.
        hass, transport = _transport()
        params = {"user_id": 5, "pin_code": "123456"}
        result = _run(transport.send(0x0005, params))
        assert result is True
        assert len(hass.services.zha_calls) == 1
        call = hass.services.zha_calls[0]
        assert call["ieee"] == IEEE
        assert call["endpoint_id"] == 11
        assert call["cluster_id"] == DOORLOCK_CLUSTER_ID
        assert call["command"] == 0x0005
        assert call["params"]["user_id"] == 5
        assert call["params"]["pin_code"] == "123456"

    def test_endpoint_comes_from_the_cluster(self):
        # Hardcoding 11 broke any lock whose Door Lock cluster sits on
        # another endpoint, while the cluster lookup searched them all.
        hass, transport = _transport()
        hass.data["zha"] = _zha_topology(FakeCluster(endpoint_id=1))
        _run(transport.send(0x0005, {"user_id": 5}))
        assert hass.services.zha_calls[0]["endpoint_id"] == 1

    def test_index_error_counts_as_success(self):
        # AGENTS.md rule 4: zigpy raises IndexError parsing the Nimly
        # response, but the command did reach the lock. Treating it as
        # failure would report every successful PIN write as failed and
        # desync local state from the lock.
        hass, transport = _transport(
            zha_effects=[IndexError("tuple index out of range")]
        )
        result = _run(transport.send(0x0005, {"user_id": 5}))
        assert result is True
        assert len(hass.services.zha_calls) == 1
        assert hass.services.lock_calls == []

    @pytest.mark.parametrize(
        "first_error",
        [TimeoutError(), DeliveryError("Failed to deliver packet")],
        ids=["timeout", "delivery_error"],
    )
    def test_sleep_errors_wake_the_lock_and_retry(self, first_error):
        # A sleeping lock shows up as either: no answer in time, or a
        # frame the radio could not deliver.
        hass, transport = _transport(zha_effects=[first_error, None])
        result = _run(transport.send(0x0005, {"user_id": 5}))
        assert result is True
        assert len(hass.services.zha_calls) == 2
        assert [c["entity_id"] for c in hass.services.lock_calls] == [
            "lock.front_door"
        ]

    @pytest.mark.parametrize(
        "errors",
        [
            [TimeoutError(), TimeoutError()],
            [DeliveryError("x"), DeliveryError("x")],
            [TimeoutError(), DeliveryError("x")],
        ],
        ids=["timeout_twice", "delivery_twice", "timeout_then_delivery"],
    )
    def test_second_sleep_error_gives_up_after_one_wake(self, errors):
        # The wake physically throws the bolt, so it must fire exactly
        # once per operation, and the loop must terminate.
        hass, transport = _transport(zha_effects=errors)
        result = _run(transport.send(0x0005, {"user_id": 5}))
        assert result is False
        assert len(hass.services.zha_calls) == 2
        assert len(hass.services.lock_calls) == 1

    def test_other_zigbee_error_fails_without_wake(self, caplog):
        # Not a sleep symptom, so waking would move the bolt for nothing.
        hass, transport = _transport(zha_effects=[ZigbeeException("bad frame")])
        with caplog.at_level(logging.DEBUG):
            result = _run(transport.send(0x0005, {"user_id": 5}))
        assert result is False
        assert len(hass.services.zha_calls) == 1
        assert hass.services.lock_calls == []
        records = [r for r in caplog.records if "ZigbeeException" in r.getMessage()]
        assert [r.levelno for r in records] == [logging.WARNING]

    def test_unexpected_error_fails_without_wake_or_raise(self):
        hass, transport = _transport(
            zha_effects=[ValueError("boom"), ValueError("boom")]
        )
        result = _run(transport.send(0x0005, {"user_id": 5}))
        assert result is False
        assert len(hass.services.zha_calls) == 1
        assert hass.services.lock_calls == []


class TestSendNeverLogsThePin:
    """Errors from ZHA may quote the params, and the params hold the PIN."""

    @pytest.mark.parametrize(
        "errors",
        [
            # What vol.Invalid from ZHA's service schema looks like.
            [ValueError(f"params {{'pin_code': '{PIN}'}}")],
            [ZigbeeException(f"frame user_id=5 pin_code={PIN}")],
            [DeliveryError(f"pin {PIN}"), DeliveryError(f"pin {PIN}")],
        ],
        ids=["voluptuous_style", "zigbee_error", "delivery_after_retry"],
    )
    def test_log_holds_no_pin(self, caplog, errors):
        _hass, transport = _transport(zha_effects=errors)
        with caplog.at_level(logging.DEBUG):
            result = _run(transport.send(0x0005, {"user_id": 5, "pin_code": PIN}))
        assert result is False
        assert caplog.records, "the failure must still be logged"
        assert PIN not in caplog.text
        # No traceback either: a frame's locals or a chained message can
        # carry the params past the redaction.
        assert all(r.exc_info is None for r in caplog.records)


class TestWakeLock:
    """Auto-wake actuates the right lock and never vetoes the operation."""

    def test_wake_actuates_only_the_matching_lock(self):
        # The wake physically locks a door. In a home with two ZHA locks
        # it must never actuate the other one.
        hass, transport = _transport(
            devices=[
                _zha_device(OTHER_IEEE, device_id="dev-back"),
                _zha_device(IEEE, device_id="dev-front"),
            ],
            entities=[
                _lock_entity("lock.back_door", device_id="dev-back"),
                # Same device, not a lock: makes the domain filter
                # load-bearing.
                FakeRegistryEntry("sensor.battery", "zha", "dev-front"),
                # Same device, a lock from another platform: makes the
                # platform filter load-bearing.
                FakeRegistryEntry("lock.template_front", "template", "dev-front"),
                _lock_entity("lock.front_door", device_id="dev-front"),
            ],
        )
        _run(transport.wake())
        assert [c["entity_id"] for c in hass.services.lock_calls] == [
            "lock.front_door"
        ]

    def test_ieee_case_in_the_entry_does_not_matter(self):
        # ZHA registers the ieee in lowercase. An entry holding it in
        # uppercase must still find the device.
        hass, transport = _transport(ieee=IEEE.upper())
        _run(transport.wake())
        assert [c["entity_id"] for c in hass.services.lock_calls] == [
            "lock.front_door"
        ]

    def test_disabled_lock_entity_is_skipped(self):
        hass, transport = _transport(
            entities=[_lock_entity(disabled_by="user")]
        )
        _run(transport.wake())
        assert hass.services.lock_calls == []

    def test_missing_lock_entity_is_logged_and_retry_still_runs(self, caplog):
        # This used to be a silent no-op, which made the whole wake-retry
        # path disappear without a trace.
        hass, transport = _transport(zha_effects=[TimeoutError(), None], entities=[])
        with caplog.at_level(logging.WARNING):
            result = _run(transport.send(0x0005, {"user_id": 5}))
        assert result is True
        assert hass.services.lock_calls == []
        assert "No ZHA lock entity" in caplog.text

    def test_wake_failure_is_swallowed_and_retry_still_runs(self):
        # A failed wake attempt must degrade to "retry anyway", not
        # propagate and abort the whole PIN operation.
        hass, transport = _transport(
            zha_effects=[TimeoutError(), None],
            wake_error=RuntimeError("registry gone"),
        )
        result = _run(transport.send(0x0005, {"user_id": 5}))
        assert result is True
        assert len(hass.services.zha_calls) == 2


class TestWakeEcho:
    """The lock reports our own wake as a Zigbee lock; the transport knows when."""

    def _at(self, seconds):
        return mock.patch.object(zha_mod.time, "monotonic", return_value=seconds)

    def test_nothing_pending_before_any_wake(self):
        _hass, transport = _transport()
        assert transport.wake_echo_pending() is False

    def test_pending_inside_the_window_only(self):
        _hass, transport = _transport()
        window = const_mod.WAKE_ECHO_WINDOW_S
        with self._at(1000.0):
            _run(transport.wake())
        with self._at(1000.0 + window - 1):
            assert transport.wake_echo_pending() is True
            # Asking does not consume it.
            assert transport.wake_echo_pending() is True
        with self._at(1000.0 + window):
            assert transport.wake_echo_pending() is False

    def test_no_actuation_means_no_echo(self):
        _hass, transport = _transport(entities=[])
        _run(transport.wake())
        assert transport.wake_echo_pending() is False

    def test_failed_wake_leaves_no_echo(self):
        # The stamp is set before lock.lock returns. If the call fails, no
        # lock is known to have gone out, and a real lock from the
        # dashboard in the next window must not be taken for an echo.
        _hass, transport = _transport(wake_error=RuntimeError("lock.lock failed"))
        with self._at(1000.0):
            _run(transport.wake())
        with self._at(1001.0):
            assert transport.wake_echo_pending() is False

    def test_failed_wake_keeps_an_earlier_wakes_window(self):
        hass, transport = _transport()
        with self._at(1000.0):
            _run(transport.wake())
        hass.services.wake_error = RuntimeError("lock.lock failed")
        with self._at(1010.0):
            _run(transport.wake())
        with self._at(1011.0):
            assert transport.wake_echo_pending() is True
        with self._at(1000.0 + const_mod.WAKE_ECHO_WINDOW_S):
            assert transport.wake_echo_pending() is False

    def test_window_is_thirty_seconds(self):
        assert const_mod.WAKE_ECHO_WINDOW_S == 30


class TestGetCluster:
    """The DoorLock cluster lives on the deepest zigpy object."""

    def test_walks_down_to_the_zigpy_device(self):
        cluster = object()
        hass, transport = _transport()
        # Uppercase ZHA key vs lowercase config entry ieee: casing differs
        # in the wild and the match must not care.
        hass.data["zha"] = _zha_topology(cluster, ieee_key=IEEE_ZHA_KEY)
        assert transport.cluster() is cluster

    def test_returns_none_when_cluster_absent(self):
        hass, transport = _transport()
        hass.data["zha"] = _zha_topology(None)
        assert transport.cluster() is None

    def test_returns_none_without_a_gateway(self):
        # ZHA's helper raises ValueError when it has no gateway, for
        # instance while ZHA itself is reloading.
        hass, transport = _transport()
        hass.data["zha"] = SimpleNamespace(gateway_proxy=None)
        assert transport.cluster() is None


class TestReadCapabilities:
    """The transport tells 'not reached' (None) from an answer (a dict)."""

    def test_reads_the_standard_zcl_attribute_ids(self):
        # NumberOfPINUsersSupported, MaxPINCodeLength, MinPINCodeLength.
        cluster = FakeCluster(result=({}, {}))
        _hass, transport = _transport()
        transport.cluster = lambda: cluster
        _run(transport.read_capabilities())
        assert cluster.requested == [[0x0012, 0x0017, 0x0018]]

    @pytest.mark.parametrize(
        "error",
        [TimeoutError(), DeliveryError("x"), RuntimeError("odd firmware")],
        ids=["timeout", "delivery_error", "other"],
    )
    def test_errors_mean_not_reached(self, error):
        _hass, transport = _transport()
        transport.cluster = lambda: FakeCluster(error=error)
        assert _run(transport.read_capabilities()) is None

    def test_no_cluster_means_not_reached(self):
        _hass, transport = _transport()
        assert _run(transport.read_capabilities()) is None

    def test_an_answer_without_the_attributes_is_final(self):
        # Some variants answer UNSUPPORTED_ATTRIBUTE. Asking again will
        # not change that, so it is an answer, not a miss.
        _hass, transport = _transport()
        transport.cluster = lambda: FakeCluster(result=({}, {0x0012: 0x86}))
        assert _run(transport.read_capabilities()) == {}


class TestRefreshCapabilities:
    """Capabilities are read until the lock answers once, then kept."""

    READING = ({0x0012: 50, 0x0017: 8, 0x0018: 4}, {})
    EXPECTED = {"num_pin_users": 50, "max_pin_length": 8, "min_pin_length": 4}

    def test_reported_capacity_lowers_the_slot_ceiling_and_persists(self):
        hass, entry, coord = _coordinator_reading(FakeCluster(result=self.READING))
        _run(coord.async_refresh_capabilities())
        assert coord.lock_capabilities == self.EXPECTED
        assert coord.max_user_slot() == 49
        assert coord.capabilities_final is True
        assert hass.config_entries.written[-1]["capabilities"] == self.EXPECTED

    def test_name_keyed_reading_lowers_the_ceiling_too(self):
        # zigpy keys the success dict by whatever the caller passed in, but
        # a quirk or a future zigpy may answer with its own attribute names.
        # Reading only ids dropped these silently and left the ceiling at
        # 999, so the lock's real capacity never applied.
        named = (
            {"num_of_pin_users_supported": 50, "max_pin_len": 8, "min_pin_len": 4},
            {},
        )
        _hass, _entry, coord = _coordinator_reading(FakeCluster(result=named))
        _run(coord.async_refresh_capabilities())
        assert coord.lock_capabilities == self.EXPECTED
        assert coord.max_user_slot() == 49

    def test_sleeping_lock_is_asked_again_later(self):
        # The startup read usually meets a sleeping lock. That must leave
        # the manual defaults and nothing persisted, so the next chance
        # (a delivered command, an attribute report) reads again.
        cluster = FakeCluster(error=TimeoutError())
        hass, _entry, coord = _coordinator_reading(cluster)
        _run(coord.async_refresh_capabilities())
        assert coord.lock_capabilities == {}
        assert coord.capabilities_final is False
        assert coord.max_user_slot() == 999
        assert hass.config_entries.written == []

        cluster._error = None
        cluster._result = self.READING
        _run(coord.async_refresh_capabilities())
        assert coord.lock_capabilities == self.EXPECTED
        assert len(cluster.requested) == 2

    def test_missing_zha_is_silent(self):
        # hass.data has no zha at all, so the real cluster lookup returns
        # None and the refresh must swallow that quietly too.
        _hass, _entry, coord = _make()
        _run(coord.async_refresh_capabilities())
        assert coord.lock_capabilities == {}
        assert coord.capabilities_final is False

    def test_empty_answer_is_final_and_persisted(self):
        hass, _entry, coord = _coordinator_reading(FakeCluster(result=({}, {0x0012: 0x86})))
        _run(coord.async_refresh_capabilities())
        assert coord.capabilities_final is True
        assert hass.config_entries.written[-1]["capabilities"] == {}

    def test_idempotent_once_answered(self):
        cluster = FakeCluster(result=self.READING)
        hass, _entry, coord = _coordinator_reading(cluster)
        _run(coord.async_refresh_capabilities())
        _run(coord.async_refresh_capabilities())
        assert len(cluster.requested) == 1
        assert len(hass.config_entries.written) == 1

    def test_stored_answer_is_loaded_at_startup(self):
        cluster = FakeCluster(result=self.READING)
        _hass, _entry, coord = _coordinator_reading(
            cluster, options={"slots": {}, "capabilities": {"num_pin_users": 20}}
        )
        assert coord.lock_capabilities == {"num_pin_users": 20}
        assert coord.max_user_slot() == 19
        assert coord.capabilities_final is True
        _run(coord.async_refresh_capabilities())
        assert cluster.requested == []

    def test_concurrent_refreshes_read_once(self):
        transport = FakeTransport(capabilities={"num_pin_users": 50})
        _hass, _entry, coord = _make(transport=transport)

        async def both():
            await asyncio.gather(
                coord.async_refresh_capabilities(), coord.async_refresh_capabilities()
            )

        asyncio.run(both())
        assert transport.reads == 1

    def test_saving_slots_keeps_the_capabilities(self):
        _hass, entry, coord = _coordinator_reading(FakeCluster(result=self.READING))
        _run(coord.async_refresh_capabilities())
        _run(coord.set_slot_name(4, "Kari"))
        assert entry.options["capabilities"] == self.EXPECTED


class TestRefreshAfterSend:
    """A delivered command proves the radio awake, so it triggers a read."""

    def test_delivered_command_schedules_a_read(self):
        transport = FakeTransport(capabilities={"num_pin_users": 50})
        _hass, entry, coord = _make(options={"slots": {}}, transport=transport)
        _run(coord.set_pin(5, "Kari", "123456"))
        assert len(entry.background) == 1
        entry.run_background()
        assert coord.lock_capabilities == {"num_pin_users": 50}

    def test_failed_command_schedules_nothing(self):
        transport = FakeTransport(result=False)
        _hass, entry, coord = _make(options={"slots": {}}, transport=transport)
        _run(coord.clear_pin(5))
        assert entry.background == []

    def test_nothing_scheduled_once_answered(self):
        transport = FakeTransport()
        _hass, entry, coord = _make(
            options={"slots": {}, "capabilities": {}}, transport=transport
        )
        _run(coord.clear_slot(5))
        assert entry.background == []


class TestPinOperations:
    """Local state and the wire must agree after each PIN operation."""

    def test_set_pin_success_persists_and_notifies(self):
        transport = FakeTransport()
        hass, entry, coord = _make(options={"slots": {}}, transport=transport)
        events = []
        coord.add_listener(lambda: events.append(True))
        result = _run(coord.set_pin(5, "Kari", "123456"))
        assert result is True
        assert coord.get_slot(5) == {
            "name": "Kari",
            "has_pin": True,
        }
        assert hass.config_entries.written[-1]["slots"]["5"]["has_pin"] is True
        assert events == [True]
        # The rest of the wire contract is TestSendClusterCommand's.
        assert len(transport.sent) == 1
        command, params = transport.sent[0]
        assert command == 0x0005
        assert params["user_id"] == 5
        assert params["pin_code"] == "123456"
        for coro in entry.background:
            coro.close()

    def test_clear_pin_keeps_the_name(self):
        # clear_pin removes the code but the person still owns the slot,
        # only clear_slot wipes the name.
        occupied = {
            "slots": {"5": {"name": "Kari", "has_pin": True}}
        }
        transport = FakeTransport()
        hass, entry, coord = _make(options=occupied, transport=transport)
        result = _run(coord.clear_pin(5))
        assert result is True
        assert coord.get_slot(5)["has_pin"] is False
        assert coord.get_slot(5)["name"] == "Kari"
        assert hass.config_entries.written[-1]["slots"]["5"]["name"] == "Kari"
        assert transport.sent[0][0] == 0x0007
        for coro in entry.background:
            coro.close()

"""Behavioral tests for NimlyCoordinator ZHA command paths.

Extends the harness in test_coordinator_behavior.py to the ZHA seams:
the retry loop in _send_cluster_command, the auto-wake, the cluster
chain walk and the capabilities read. The stubs replicate the object
shapes the coordinator assumes, so these tests lock our retry and
traversal logic, not ZHA compatibility: a ZHA rename of gateway_proxy
or device_proxies would pass here and only show up on a real Home
Assistant instance.

CI installs only pytest, so the tests are sync and drive the coroutines
with asyncio.run().
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import types
from types import SimpleNamespace
from unittest import mock

if "homeassistant" not in sys.modules:
    sys.modules["homeassistant"] = types.ModuleType("homeassistant")
if "homeassistant.core" not in sys.modules:
    _core = types.ModuleType("homeassistant.core")
    _core.HomeAssistant = object
    sys.modules["homeassistant"].core = _core
    sys.modules["homeassistant.core"] = _core
if "homeassistant.config_entries" not in sys.modules:
    _ce = types.ModuleType("homeassistant.config_entries")
    _ce.ConfigEntry = object
    sys.modules["homeassistant"].config_entries = _ce
    sys.modules["homeassistant.config_entries"] = _ce
if "homeassistant.helpers.entity_registry" not in sys.modules:
    # _wake_lock imports this inside its try block. Without the stub the
    # import raises, the except swallows it, and every wake assertion
    # below would silently test nothing.
    _helpers = types.ModuleType("homeassistant.helpers")
    _er = types.ModuleType("homeassistant.helpers.entity_registry")
    _er.async_get = lambda hass: hass.entity_registry
    _helpers.entity_registry = _er
    sys.modules["homeassistant"].helpers = _helpers
    sys.modules["homeassistant.helpers"] = _helpers
    sys.modules["homeassistant.helpers.entity_registry"] = _er

_COMPONENT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "onesti_lock"
)
# Same package name as test_coordinator_behavior.py so both files share
# one loaded coordinator module regardless of collection order.
_PACKAGE = "onesti_lock_coordinator_under_test"


def _load_coordinator():
    if _PACKAGE not in sys.modules:
        package = types.ModuleType(_PACKAGE)
        package.__path__ = [_COMPONENT_DIR]
        sys.modules[_PACKAGE] = package
    name = f"{_PACKAGE}.coordinator"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_COMPONENT_DIR, "coordinator.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


coordinator_mod = _load_coordinator()

# Letters in the ieee so the case-insensitivity tests compare something.
IEEE = "f4:ce:36:0a:00:11:22:aa"
# ZHA keys device_proxies by EUI64 objects whose str() may differ in case.
IEEE_ZHA_KEY = IEEE.upper()
DOORLOCK_CLUSTER_ID = 0x0101


class FakeConfigEntry:
    def __init__(self, options=None):
        self.data = {"ieee": IEEE}
        self.options = dict(options or {})


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


class FakeEntity:
    def __init__(self, platform, unique_id, entity_id):
        self.platform = platform
        self.unique_id = unique_id
        self.entity_id = entity_id


class FakeEntityRegistry:
    def __init__(self, entities=()):
        self.entities = {e.entity_id: e for e in entities}


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


def _lock_entity(ieee=IEEE, entity_id="lock.front_door"):
    # ZHA unique ids end in the cluster id in decimal, 257 is DoorLock 0x0101.
    return FakeEntity("zha", f"{ieee}-11-257", entity_id)


class FakeHass:
    def __init__(self, zha_effects=(), wake_error=None, entities=None):
        self.config_entries = FakeConfigEntries()
        self.services = ScriptedServices(zha_effects, wake_error)
        self.entity_registry = FakeEntityRegistry(
            entities if entities is not None else [_lock_entity()]
        )
        self.data = {}


async def _no_sleep(_seconds):
    return None


def _run(coro):
    # _wake_lock sleeps one real second after actuating, pointless in tests.
    with mock.patch("asyncio.sleep", _no_sleep):
        return asyncio.run(coro)


def _make(options=None, **hass_kwargs):
    hass = FakeHass(**hass_kwargs)
    entry = FakeConfigEntry(options)
    return hass, entry, coordinator_mod.NimlyCoordinator(hass, entry)


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
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    async def read_attributes(self, attr_ids):
        if self._error is not None:
            raise self._error
        return self._result


class TestSendClusterCommand:
    """Retry semantics, success semantics and the Nimly IndexError quirk."""

    def test_index_error_counts_as_success(self):
        # AGENTS.md rule 4: zigpy raises IndexError parsing the Nimly
        # response, but the command did reach the lock. Treating it as
        # failure would report every successful PIN write as failed and
        # desync local state from the lock.
        hass, _entry, coord = _make(
            zha_effects=[IndexError("tuple index out of range")]
        )
        result = _run(coord._send_cluster_command(0x0005, {"user_id": 5}))
        assert result is True
        assert len(hass.services.zha_calls) == 1
        assert hass.services.lock_calls == []

    def test_timeout_wakes_lock_and_retry_succeeds(self):
        hass, _entry, coord = _make(zha_effects=[TimeoutError(), None])
        result = _run(coord._send_cluster_command(0x0005, {"user_id": 5}))
        assert result is True
        assert len(hass.services.zha_calls) == 2
        assert [c["entity_id"] for c in hass.services.lock_calls] == [
            "lock.front_door"
        ]

    def test_double_timeout_gives_up_after_one_wake(self):
        # The wake physically throws the bolt, so it must fire exactly
        # once per operation, and the loop must terminate.
        hass, _entry, coord = _make(zha_effects=[TimeoutError(), TimeoutError()])
        result = _run(coord._send_cluster_command(0x0005, {"user_id": 5}))
        assert result is False
        assert len(hass.services.zha_calls) == 2
        assert len(hass.services.lock_calls) == 1

    def test_unexpected_error_returns_false_without_raising(self):
        # Only the boolean contract is locked. Which exception types
        # deserve wake+retry is an open question (DeliveryError, tracked
        # separately), so no assertion on wake or attempt count here. The
        # error is scripted on both attempts: with a single effect the
        # scripted bus succeeds on retry, and the False assertion would
        # cement "ValueError is never retried" after all.
        hass, _entry, coord = _make(
            zha_effects=[ValueError("boom"), ValueError("boom")]
        )
        result = _run(coord._send_cluster_command(0x0005, {"user_id": 5}))
        assert result is False


class TestWakeLock:
    """Auto-wake actuates the right lock and never vetoes the operation."""

    def test_wake_actuates_only_the_matching_lock(self):
        # The wake physically locks a door. In a home with two ZHA locks
        # it must never actuate the other one.
        ours = _lock_entity(entity_id="lock.front_door")
        other = _lock_entity(
            ieee="aa:bb:cc:dd:ee:ff:00:11", entity_id="lock.back_door"
        )
        # Same device, same ieee, but the battery sensor's unique_id does
        # not end in the DoorLock cluster id: makes the 257 filter
        # load-bearing, not just the platform filter.
        same_device_sensor = FakeEntity("zha", f"{IEEE}-1-1", "sensor.battery")
        # Foreign platform whose unique_id happens to end in 257: makes the
        # platform filter load-bearing, not just the 257 filter.
        not_a_lock = FakeEntity("hue", f"{IEEE}-11-257", "light.hallway")
        hass, _entry, coord = _make(
            entities=[other, same_device_sensor, not_a_lock, ours]
        )
        _run(coord._wake_lock())
        assert [c["entity_id"] for c in hass.services.lock_calls] == [
            "lock.front_door"
        ]

    def test_wake_failure_is_swallowed_and_retry_still_runs(self):
        # A failed wake attempt must degrade to "retry anyway", not
        # propagate and abort the whole PIN operation.
        hass, _entry, coord = _make(
            zha_effects=[TimeoutError(), None],
            wake_error=RuntimeError("registry gone"),
        )
        result = _run(coord._send_cluster_command(0x0005, {"user_id": 5}))
        assert result is True
        assert len(hass.services.zha_calls) == 2


class TestGetCluster:
    """The DoorLock cluster lives on the deepest zigpy object."""

    def test_walks_down_to_the_zigpy_device(self):
        cluster = object()
        hass, _entry, coord = _make()
        # Uppercase ZHA key vs lowercase config entry ieee: casing differs
        # in the wild and the match must not care.
        hass.data["zha"] = _zha_topology(cluster, ieee_key=IEEE_ZHA_KEY)
        assert coord._get_cluster() is cluster

    def test_returns_none_when_cluster_absent(self):
        hass, _entry, coord = _make()
        hass.data["zha"] = _zha_topology(None)
        assert coord._get_cluster() is None


class TestReadLockCapabilities:
    """The capability read feeds the slot ceiling and must never break setup."""

    def test_reported_capacity_lowers_the_slot_ceiling(self):
        _hass, _entry, coord = _make()
        cluster = FakeCluster(result=({0x0012: 50, 0x0017: 8, 0x0018: 4}, {}))
        # _get_cluster has its own tests above, bypassing it keeps the ZHA
        # topology stub out of what this test is about.
        coord._get_cluster = lambda: cluster
        _run(coord.read_lock_capabilities())
        assert coord.lock_capabilities == {
            "num_pin_users": 50,
            "max_pin_length": 8,
            "min_pin_length": 4,
        }
        assert coord.max_user_slot() == 49

    def test_name_keyed_reading_lowers_the_ceiling_too(self):
        # zigpy keys the success dict by whatever the caller passed in, but
        # a quirk or a future zigpy may answer with its own attribute names.
        # Reading only ids dropped these silently and left the ceiling at
        # 999, so the lock's real capacity never applied.
        _hass, _entry, coord = _make()
        coord._get_cluster = lambda: FakeCluster(
            result=(
                {
                    "num_of_pin_users_supported": 50,
                    "max_pin_len": 8,
                    "min_pin_len": 4,
                },
                {},
            )
        )
        _run(coord.read_lock_capabilities())
        assert coord.lock_capabilities == {
            "num_pin_users": 50,
            "max_pin_length": 8,
            "min_pin_length": 4,
        }
        assert coord.max_user_slot() == 49

    def test_sleeping_lock_degrades_to_defaults(self):
        # The read runs as a background task at setup. A lock sleeping
        # through it must leave the manual defaults, not raise into the
        # task and never populate the ceiling.
        _hass, _entry, coord = _make()
        coord._get_cluster = lambda: FakeCluster(error=TimeoutError())
        _run(coord.read_lock_capabilities())
        assert coord.lock_capabilities == {}
        assert coord.max_user_slot() == 999

    def test_missing_zha_is_silent(self):
        # hass.data has no zha at all, so the real _get_cluster returns
        # None and the read must swallow that quietly too.
        _hass, _entry, coord = _make()
        _run(coord.read_lock_capabilities())
        assert coord.lock_capabilities == {}


class TestPinOperations:
    """Local state and the wire must agree after each PIN operation."""

    def test_set_pin_success_persists_and_notifies(self):
        hass, _entry, coord = _make(options={"slots": {}})
        events = []
        coord.add_listener(lambda: events.append(True))
        result = _run(coord.set_pin(5, "Kari", "123456"))
        assert result is True
        assert coord.get_slot(5) == {
            "name": "Kari",
            "has_pin": True,
            "has_rfid": False,
        }
        assert hass.config_entries.written[-1]["slots"]["5"]["has_pin"] is True
        assert events == [True]
        # The wire contract is what the lock actually receives.
        assert len(hass.services.zha_calls) == 1
        call = hass.services.zha_calls[0]
        assert call["ieee"] == IEEE
        assert call["endpoint_id"] == 11
        assert call["cluster_id"] == DOORLOCK_CLUSTER_ID
        assert call["command"] == 0x0005
        assert call["params"]["user_id"] == 5
        assert call["params"]["pin_code"] == "123456"

    def test_clear_pin_keeps_the_name(self):
        # clear_pin removes the code but the person still owns the slot,
        # only clear_slot wipes the name.
        occupied = {
            "slots": {"5": {"name": "Kari", "has_pin": True, "has_rfid": False}}
        }
        hass, _entry, coord = _make(options=occupied)
        result = _run(coord.clear_pin(5))
        assert result is True
        assert coord.get_slot(5)["has_pin"] is False
        assert coord.get_slot(5)["name"] == "Kari"
        assert hass.config_entries.written[-1]["slots"]["5"]["name"] == "Kari"
        assert hass.services.zha_calls[0]["command"] == 0x0007

"""Behavioral tests for the activity sensor suppression in __init__.py.

These run the real _register_event_listener and its callback against a fake
cluster, so they cover the code path the replicated decode tests miss: which
events reach the activity sensor and which only fire the HA event.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types

import pytest

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

_COMPONENT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "onesti_lock"
)
_PACKAGE = "onesti_lock_init_under_test"


def _load_init():
    if _PACKAGE not in sys.modules:
        package = types.ModuleType(_PACKAGE)
        package.__path__ = [_COMPONENT_DIR]
        sys.modules[_PACKAGE] = package
    name = f"{_PACKAGE}.__init__"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_COMPONENT_DIR, "__init__.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


init_mod = _load_init()


class FakeCluster:
    def __init__(self):
        self.callbacks = {}
        self._event_listeners = {}

    def on_event(self, name, callback):
        self.callbacks[name] = callback
        return lambda: None


class FakeBus:
    def __init__(self):
        self.fired = []

    def async_fire(self, name, data):
        self.fired.append((name, data))


class FakeHass:
    def __init__(self, entry_id):
        self.data = {init_mod.DOMAIN: {entry_id: {}}}
        self.bus = FakeBus()


class FakeCoordinator:
    ieee = "00:11:22:33:44:55:66:77"

    def __init__(self, cluster):
        self._cluster = cluster
        self.activity_calls = []

    def _get_cluster(self):
        return self._cluster

    def get_slot_name(self, slot):
        return f"User {slot}"

    def update_activity(self, user_slot, action, source):
        self.activity_calls.append((user_slot, action, source))


class FakeEntry:
    entry_id = "test_entry"


class FakeEvent:
    def __init__(self, attribute_id, raw_value):
        self.attribute_id = attribute_id
        self.raw_value = raw_value


def _make_listener():
    cluster = FakeCluster()
    coordinator = FakeCoordinator(cluster)
    hass = FakeHass(FakeEntry.entry_id)
    init_mod._register_event_listener(hass, FakeEntry(), coordinator)
    return hass, coordinator, cluster.callbacks["attribute_report"]


def _event(source, action, slot):
    return FakeEvent(0x0100, (source << 24) | (action << 16) | slot)


class TestActivitySuppression:
    """Which decoded events may touch the activity sensor."""

    @pytest.mark.parametrize(
        ("source", "action", "slot"),
        [
            (0x02, 0x02, 3),   # keypad unlock by a user
            (0x02, 0x01, 3),   # keypad lock by a user
            (0x03, 0x02, 4),   # fingerprint unlock
            (0x00, 0x01, 0),   # zigbee lock: explicit remote attribution
            (0x05, 0x02, 0),   # unattributed unlock: a person at the door
            (0x05, 0x01, 7),   # unattributed lock WITH a user slot
        ],
    )
    def test_user_attributable_events_update_sensor(self, source, action, slot):
        _hass, coordinator, callback = _make_listener()
        callback(_event(source, action, slot))
        assert len(coordinator.activity_calls) == 1

    @pytest.mark.parametrize(
        ("source", "action", "slot"),
        [
            (0x0A, 0x01, 0),   # auto-relock on most models
            (0x05, 0x01, 0),   # auto-relock as reported by NimlyCodePRO fw 4.8
        ],
    )
    def test_system_locks_do_not_touch_sensor(self, source, action, slot):
        _hass, coordinator, callback = _make_listener()
        callback(_event(source, action, slot))
        assert coordinator.activity_calls == []


class TestEventAlwaysFires:
    """The HA event fires for every decoded report, including suppressed ones."""

    @pytest.mark.parametrize(
        ("source", "action", "slot"),
        [
            (0x02, 0x02, 3),
            (0x0A, 0x01, 0),
            (0x05, 0x01, 0),
        ],
    )
    def test_ha_event_fires(self, source, action, slot):
        hass, _coordinator, callback = _make_listener()
        callback(_event(source, action, slot))
        assert len(hass.bus.fired) == 1
        name, data = hass.bus.fired[0]
        assert name == "onesti_lock_activity"
        assert data["ieee"] == FakeCoordinator.ieee

    def test_other_attributes_are_ignored(self):
        hass, coordinator, callback = _make_listener()
        callback(FakeEvent(0x0042, 123))
        assert hass.bus.fired == []
        assert coordinator.activity_calls == []

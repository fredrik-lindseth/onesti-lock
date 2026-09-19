"""Behavioral tests for the activity sensor suppression in events.py.

These run the real register_event_listener and its callback against a fake
cluster, so they cover the code path the replicated decode tests miss: which
events reach the activity sensor and which only fire the HA event.
"""
from __future__ import annotations

import pytest

from .conftest import load_component_module

events_mod = load_component_module("events")


class FakeCluster:
    def __init__(self):
        self.callbacks = {}

    def on_event(self, name, callback):
        self.callbacks[name] = callback
        return lambda: None


class FakeBus:
    def __init__(self):
        self.fired = []

    def async_fire(self, name, data):
        self.fired.append((name, data))


class FakeHass:
    def __init__(self):
        self.bus = FakeBus()


class FakeTransport:
    def __init__(self, cluster):
        self._cluster = cluster

    def cluster(self):
        return self._cluster


class FakeCoordinator:
    ieee = "00:11:22:33:44:55:66:77"

    def __init__(self, cluster):
        self.transport = FakeTransport(cluster)
        self.activity_calls = []
        self.capability_refreshes = 0
        self.echo_pending = False
        self.listened_cluster = None

    def wake_echo_pending(self):
        return self.echo_pending

    def get_slot_name(self, slot):
        return f"User {slot}"

    def update_activity(self, user_slot, action, source):
        self.activity_calls.append((user_slot, action, source))

    def schedule_capability_refresh(self):
        self.capability_refreshes += 1


class FakeEvent:
    def __init__(self, attribute_id, raw_value):
        self.attribute_id = attribute_id
        self.raw_value = raw_value


def _make_listener(echo_pending=False):
    cluster = FakeCluster()
    coordinator = FakeCoordinator(cluster)
    coordinator.echo_pending = echo_pending
    hass = FakeHass()
    events_mod.register_event_listener(hass, coordinator)
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
            (0x02, 0x02, 0),   # master code unlock (capture 0x02020000)
            # Keypad lock on slot 0: a hardware check (locking from outside)
            # decides whether this should be narrowed to system locks instead.
            (0x02, 0x01, 0),
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


class TestWakeEcho:
    """Our own auto-wake locks the door through ZHA, and the lock reports it
    as a Zigbee lock. Inside the echo window that report is a system lock."""

    def test_zigbee_lock_during_echo_window_does_not_touch_sensor(self):
        hass, coordinator, callback = _make_listener(echo_pending=True)
        callback(_event(0x00, 0x01, 0))
        assert coordinator.activity_calls == []
        # The HA event still fires, automations see every lock.
        assert len(hass.bus.fired) == 1
        assert hass.bus.fired[0][1]["source"] == "zigbee"

    def test_zigbee_lock_outside_echo_window_updates_sensor(self):
        _hass, coordinator, callback = _make_listener(echo_pending=False)
        callback(_event(0x00, 0x01, 0))
        assert coordinator.activity_calls == [(None, "lock", "zigbee")]

    @pytest.mark.parametrize(
        ("source", "action", "slot"),
        [
            (0x00, 0x02, 0),   # zigbee unlock: the wake never unlocks
            (0x00, 0x01, 4),   # zigbee lock with a user slot
            (0x02, 0x01, 3),   # keypad lock by a user
            (0x02, 0x02, 3),   # keypad unlock by a user
        ],
    )
    def test_echo_window_only_hides_anonymous_zigbee_locks(self, source, action, slot):
        _hass, coordinator, callback = _make_listener(echo_pending=True)
        callback(_event(source, action, slot))
        assert len(coordinator.activity_calls) == 1


class TestIsSystemLock:
    """The pure rule, with the echo flag passed in."""

    @pytest.mark.parametrize(
        ("decoded", "echo", "expected"),
        [
            ({"source": "auto", "action": "lock", "user_slot": None}, False, True),
            ({"source": "auto", "action": "unlock", "user_slot": None}, False, True),
            ({"source": "unattributed", "action": "lock", "user_slot": None}, False, True),
            ({"source": "unattributed", "action": "unlock", "user_slot": None}, True, False),
            ({"source": "zigbee", "action": "lock", "user_slot": None}, False, False),
            ({"source": "zigbee", "action": "lock", "user_slot": None}, True, True),
            ({"source": "zigbee", "action": "unlock", "user_slot": None}, True, False),
            ({"source": "keypad", "action": "lock", "user_slot": None}, True, False),
        ],
    )
    def test_rule(self, decoded, echo, expected):
        assert events_mod.is_system_lock(decoded, echo) is expected

    def test_echo_defaults_to_false(self):
        assert events_mod.is_system_lock({"source": "zigbee", "action": "lock", "user_slot": None}) is False


class TestRegistration:
    """What register_event_listener reports when ZHA's internals are missing."""

    def test_records_the_cluster_it_listens_on(self):
        cluster = FakeCluster()
        coordinator = FakeCoordinator(cluster)
        unsub = events_mod.register_event_listener(FakeHass(), coordinator)
        assert callable(unsub)
        assert coordinator.listened_cluster is cluster

    def test_missing_cluster_raises_with_detail(self):
        coordinator = FakeCoordinator(None)
        with pytest.raises(events_mod.ZhaInternalsMissing) as excinfo:
            events_mod.register_event_listener(FakeHass(), coordinator)
        assert coordinator.ieee in excinfo.value.detail
        assert coordinator.listened_cluster is None

    def test_cluster_without_on_event_raises_with_detail(self):
        class OldCluster:
            pass

        coordinator = FakeCoordinator(OldCluster())
        with pytest.raises(events_mod.ZhaInternalsMissing) as excinfo:
            events_mod.register_event_listener(FakeHass(), coordinator)
        assert excinfo.value.detail == "OldCluster.on_event"
        assert coordinator.listened_cluster is None

    def test_never_reads_private_listener_state(self):
        """The debug line once read cluster._event_listeners, which a zigpy
        rename would turn into a setup crash even with debug logging off."""
        cluster = FakeCluster()
        coordinator = FakeCoordinator(cluster)
        events_mod.register_event_listener(FakeHass(), coordinator)
        assert not hasattr(cluster, "_event_listeners")


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


class TestCapabilityRefreshOnReport:
    """A report proves the radio is awake, so the listener asks for a read."""

    @pytest.mark.parametrize(
        "event",
        [_event(0x02, 0x02, 3), FakeEvent(0x0042, 123)],
        ids=["operation_event", "other_attribute"],
    )
    def test_every_report_schedules_a_refresh(self, event):
        _hass, coordinator, callback = _make_listener()
        callback(event)
        assert coordinator.capability_refreshes == 1

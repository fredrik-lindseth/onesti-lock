"""Behavioral tests for the activity sensor suppression in events.py.

These run the real register_event_listener and its callback against a fake
cluster, so they cover the code path the replicated decode tests miss: which
events reach the activity sensor and which only fire the HA event.

Every one of them runs twice, once per registration path: the
`cluster.on_event` hook zigpy 0.91 and newer offer, and the
`add_listener` + `attribute_updated` fallback for the older zigpy that
Home Assistant 2025.6 through 2026.1 ship. The two fakes mirror how real
zigpy delivers a report on each path; tests_ha/test_zigpy_listener.py
proves the shapes against the real library.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from .conftest import load_component_module

events_mod = load_component_module("events")


class FakeOnEventCluster:
    """zigpy 0.91 and newer: Cluster emits "attribute_report" events."""

    def __init__(self):
        self.callbacks = {}

    def on_event(self, name, callback):
        self.callbacks.setdefault(name, []).append(callback)

        def unsubscribe():
            self.callbacks[name].remove(callback)

        return unsubscribe

    def deliver(self, attribute_id, raw_value):
        # An emit with nobody subscribed is a no-op in zigpy too.
        for callback in list(self.callbacks.get("attribute_report", [])):
            callback(SimpleNamespace(attribute_id=attribute_id, raw_value=raw_value))

    @property
    def listening(self) -> bool:
        return any(self.callbacks.values())


class FakeListenableCluster:
    """zigpy before 0.91: listener objects with attribute_updated."""

    def __init__(self):
        self.listeners = []

    def add_listener(self, listener):
        self.listeners.append(listener)
        return id(listener)

    def remove_listener(self, listener):
        self.listeners.remove(listener)

    def deliver(self, attribute_id, raw_value):
        # zigpy passes the timestamp positionally, from _update_attribute.
        for listener in list(self.listeners):
            listener.attribute_updated(attribute_id, raw_value, 1_700_000_000.0)

    @property
    def listening(self) -> bool:
        return bool(self.listeners)


@pytest.fixture(params=[FakeOnEventCluster, FakeListenableCluster], ids=["on_event", "add_listener"])
def cluster_class(request):
    """Both registration paths, for every test that takes this fixture."""
    return request.param


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


def _make_listener(cluster_class, echo_pending=False):
    cluster = cluster_class()
    coordinator = FakeCoordinator(cluster)
    coordinator.echo_pending = echo_pending
    hass = FakeHass()
    events_mod.register_event_listener(hass, coordinator)
    return hass, coordinator, cluster


def _report(cluster, source, action, slot):
    cluster.deliver(0x0100, (source << 24) | (action << 16) | slot)


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
    def test_user_attributable_events_update_sensor(self, cluster_class, source, action, slot):
        _hass, coordinator, cluster = _make_listener(cluster_class)
        _report(cluster, source, action, slot)
        assert len(coordinator.activity_calls) == 1

    @pytest.mark.parametrize(
        ("source", "action", "slot"),
        [
            (0x0A, 0x01, 0),   # auto-relock on most models
            (0x05, 0x01, 0),   # auto-relock as reported by NimlyCodePRO fw 4.8
        ],
    )
    def test_system_locks_do_not_touch_sensor(self, cluster_class, source, action, slot):
        _hass, coordinator, cluster = _make_listener(cluster_class)
        _report(cluster, source, action, slot)
        assert coordinator.activity_calls == []


class TestWakeEcho:
    """Our own auto-wake locks the door through ZHA, and the lock reports it
    as a Zigbee lock. Inside the echo window that report is a system lock."""

    def test_zigbee_lock_during_echo_window_does_not_touch_sensor(self, cluster_class):
        hass, coordinator, cluster = _make_listener(cluster_class, echo_pending=True)
        _report(cluster, 0x00, 0x01, 0)
        assert coordinator.activity_calls == []
        # The HA event still fires, automations see every lock.
        assert len(hass.bus.fired) == 1
        assert hass.bus.fired[0][1]["source"] == "zigbee"

    def test_zigbee_lock_outside_echo_window_updates_sensor(self, cluster_class):
        _hass, coordinator, cluster = _make_listener(cluster_class, echo_pending=False)
        _report(cluster, 0x00, 0x01, 0)
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
    def test_echo_window_only_hides_anonymous_zigbee_locks(self, cluster_class, source, action, slot):
        _hass, coordinator, cluster = _make_listener(cluster_class, echo_pending=True)
        _report(cluster, source, action, slot)
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
    """Which hook is used, and what is reported when neither is there."""

    def test_records_the_cluster_it_listens_on(self, cluster_class):
        cluster = cluster_class()
        coordinator = FakeCoordinator(cluster)
        unsub = events_mod.register_event_listener(FakeHass(), coordinator)
        assert callable(unsub)
        assert coordinator.listened_cluster is cluster
        assert cluster.listening

    def test_unsubscribe_removes_the_listener(self, cluster_class):
        cluster = cluster_class()
        coordinator = FakeCoordinator(cluster)
        hass = FakeHass()
        unsub = events_mod.register_event_listener(hass, coordinator)

        unsub()

        assert not cluster.listening
        _report(cluster, 0x02, 0x02, 3)
        assert coordinator.activity_calls == []
        assert hass.bus.fired == []

    def test_on_event_wins_when_the_cluster_has_both(self):
        """zigpy 0.91 and newer keep add_listener, so the order matters."""

        class BothHooks(FakeOnEventCluster):
            def __init__(self):
                super().__init__()
                self.listeners = []

            def add_listener(self, listener):
                self.listeners.append(listener)

            def remove_listener(self, listener):
                self.listeners.remove(listener)

        cluster = BothHooks()
        events_mod.register_event_listener(FakeHass(), FakeCoordinator(cluster))
        assert cluster.listening
        assert cluster.listeners == []

    def test_missing_cluster_raises_with_detail(self):
        coordinator = FakeCoordinator(None)
        with pytest.raises(events_mod.ZhaInternalsMissing) as excinfo:
            events_mod.register_event_listener(FakeHass(), coordinator)
        assert coordinator.ieee in excinfo.value.detail
        assert coordinator.listened_cluster is None

    def test_cluster_without_either_hook_raises_with_detail(self):
        class OldCluster:
            pass

        coordinator = FakeCoordinator(OldCluster())
        with pytest.raises(events_mod.ZhaInternalsMissing) as excinfo:
            events_mod.register_event_listener(FakeHass(), coordinator)
        assert "OldCluster.on_event" in excinfo.value.detail
        assert "add_listener" in excinfo.value.detail
        assert coordinator.listened_cluster is None

    def test_add_listener_without_remove_listener_raises(self):
        """Half the fallback is no fallback: unsubscribing would be a lie."""

        class HalfCluster:
            def add_listener(self, listener):
                pass

        coordinator = FakeCoordinator(HalfCluster())
        with pytest.raises(events_mod.ZhaInternalsMissing):
            events_mod.register_event_listener(FakeHass(), coordinator)
        assert coordinator.listened_cluster is None

    def test_never_reads_private_listener_state(self, cluster_class):
        """The debug line once read cluster._event_listeners, which a zigpy
        rename would turn into a setup crash even with debug logging off."""
        cluster = cluster_class()
        coordinator = FakeCoordinator(cluster)
        events_mod.register_event_listener(FakeHass(), coordinator)
        assert not hasattr(cluster, "_event_listeners")
        assert not hasattr(cluster, "_listeners")


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
    def test_ha_event_fires(self, cluster_class, source, action, slot):
        hass, _coordinator, cluster = _make_listener(cluster_class)
        _report(cluster, source, action, slot)
        assert len(hass.bus.fired) == 1
        name, data = hass.bus.fired[0]
        assert name == "onesti_lock_activity"
        assert data["ieee"] == FakeCoordinator.ieee

    def test_other_attributes_are_ignored(self, cluster_class):
        hass, coordinator, cluster = _make_listener(cluster_class)
        cluster.deliver(0x0042, 123)
        assert hass.bus.fired == []
        assert coordinator.activity_calls == []


class TestCapabilityRefreshOnReport:
    """A report proves the radio is awake, so the listener asks for a read.

    On the add_listener path this also covers our own capability reads,
    since zigpy calls attribute_updated for a read response too. That is
    the same signal and the same guard (capabilities_final), so it costs
    at most one extra read.
    """

    @pytest.mark.parametrize(
        ("attribute_id", "raw_value"),
        [(0x0100, 0x02020003), (0x0042, 123), (0x0012, 50)],
        ids=["operation_event", "other_attribute", "capability_read"],
    )
    def test_every_report_schedules_a_refresh(self, cluster_class, attribute_id, raw_value):
        _hass, coordinator, cluster = _make_listener(cluster_class)
        cluster.deliver(attribute_id, raw_value)
        assert coordinator.capability_refreshes == 1

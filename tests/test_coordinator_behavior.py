"""Behavioral tests for NimlyCoordinator persistence and clear_slot.

coordinator.py imports homeassistant only for the HomeAssistant and
ConfigEntry type hints, so minimal stub modules are enough to execute the
real class. FakeConfigEntries replicates the one piece of HA behavior that
matters here: async_update_entry only persists when the new options compare
unequal to entry.options. That equality check is what hid the _save_slots
aliasing bug, so these tests run the real save path against it.

CI installs only pytest, so the tests are sync and drive the coroutines
with asyncio.run().
"""
from __future__ import annotations

import asyncio
import json

import pytest

from .conftest import load_component_module

coordinator_mod = load_component_module("coordinator")


class FakeConfigEntry:
    def __init__(self, options=None):
        self.data = {"ieee": "00:11:22:33:44:55:66:77"}
        self.options = dict(options or {})
        self.background_tasks = []

    def async_create_background_task(self, hass, target, name):
        """Record the name and close the coroutine unrun.

        A delivered PIN command schedules a capability read here. These
        tests are about slot state, and the read has its own tests in
        test_coordinator_commands.py.
        """
        self.background_tasks.append(name)
        target.close()


class FakeConfigEntries:
    """Replicates HA's change detection in async_update_entry."""

    def __init__(self):
        self.written = []

    def async_update_entry(self, entry, *, options):
        if entry.options == options:
            # HA returns False and schedules no .storage write.
            return False
        entry.options = options
        # The json round-trip snapshots what .storage would hold on disk.
        self.written.append(json.loads(json.dumps(options)))
        return True


class FakeServices:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, data))
        if self.fail:
            raise TimeoutError


class NoDevices:
    """A device registry without the lock, so the auto-wake finds nothing."""

    def async_get_device(self, identifiers=None, connections=None):
        return None


class FakeHass:
    def __init__(self, fail_services=False):
        self.config_entries = FakeConfigEntries()
        self.services = FakeServices(fail=fail_services)
        # No ZHA gateway and no ZHA device: the real transport sends with
        # the fallback endpoint and its wake is a logged no-op.
        self.data = {}
        self.device_registry = NoDevices()


def _make_coordinator(options=None, fail_services=False, transport=None):
    hass = FakeHass(fail_services=fail_services)
    entry = FakeConfigEntry(options)
    return hass, entry, coordinator_mod.NimlyCoordinator(hass, entry, transport)


class TestSaveSlotsPersistence:
    """The save path must survive HA's options equality check every time."""

    def test_second_save_is_persisted(self):
        hass, _entry, coord = _make_coordinator({"slots": {}})
        asyncio.run(coord.set_slot_name(3, "Kari"))
        asyncio.run(coord.set_slot_name(4, "Ola"))
        assert len(hass.config_entries.written) == 2
        slots = hass.config_entries.written[-1]["slots"]
        assert slots["3"]["name"] == "Kari"
        assert slots["4"]["name"] == "Ola"

    def test_rename_of_existing_slot_is_persisted(self):
        hass, _entry, coord = _make_coordinator({"slots": {}})
        asyncio.run(coord.set_slot_name(3, "Kari"))
        asyncio.run(coord.set_slot_name(3, "Kari Nordmann"))
        assert hass.config_entries.written[-1]["slots"]["3"]["name"] == "Kari Nordmann"

    def test_all_changes_survive_restart(self):
        hass, _entry, coord = _make_coordinator({"slots": {}})
        asyncio.run(coord.set_slot_name(3, "Kari"))
        asyncio.run(coord.set_slot_name(4, "Ola"))
        persisted = hass.config_entries.written[-1]
        _hass2, _entry2, coord2 = _make_coordinator(persisted)
        assert coord2.get_slot(3)["name"] == "Kari"
        assert coord2.get_slot(4)["name"] == "Ola"

    def test_saved_options_never_alias_live_slots(self):
        _hass, entry, coord = _make_coordinator({"slots": {}})
        asyncio.run(coord.set_slot_name(3, "Kari"))
        assert entry.options["slots"] is not coord._slots
        assert entry.options["slots"]["3"] is not coord._slots["3"]


class TestClearSlotFailure:
    """A clear that never reached the lock must not pretend it did."""

    _OCCUPIED = {"slots": {"5": {"name": "Kari", "has_pin": True}}}

    def test_failed_clear_keeps_slot_state(self):
        hass, _entry, coord = _make_coordinator(self._OCCUPIED, fail_services=True)
        result = asyncio.run(coord.clear_slot(5))
        assert result is False
        assert coord.get_slot(5)["name"] == "Kari"
        assert coord.get_slot(5)["has_pin"] is True
        assert hass.config_entries.written == []

    def test_successful_clear_resets_and_persists(self):
        hass, _entry, coord = _make_coordinator(self._OCCUPIED)
        result = asyncio.run(coord.clear_slot(5))
        assert result is True
        assert coord.get_slot(5)["name"] == ""
        assert coord.get_slot(5)["has_pin"] is False
        assert hass.config_entries.written[-1]["slots"]["5"]["name"] == ""

    def test_failed_set_pin_does_not_mark_has_pin(self):
        hass, _entry, coord = _make_coordinator({"slots": {}}, fail_services=True)
        result = asyncio.run(coord.set_pin(5, "Kari", "1234"))
        assert result is False
        assert coord.get_slot(5)["has_pin"] is False
        assert hass.config_entries.written == []


class TestGetSlotIsolation:
    """get_slot hands out copies so callers cannot corrupt _slots."""

    def test_occupied_slot_is_a_copy(self):
        _hass, _entry, coord = _make_coordinator({"slots": {}})
        asyncio.run(coord.set_slot_name(3, "Kari"))
        assert coord.get_slot(3) is not coord._slots["3"]

    def test_mutating_the_returned_dict_does_not_leak(self):
        hass, entry, coord = _make_coordinator({"slots": {}})
        asyncio.run(coord.set_slot_name(3, "Kari"))
        writes_before = len(hass.config_entries.written)
        returned = coord.get_slot(3)
        returned["name"] = "Mallory"
        returned["has_pin"] = True
        assert coord.get_slot(3)["name"] == "Kari"
        assert coord.get_slot(3)["has_pin"] is False
        assert entry.options["slots"]["3"]["name"] == "Kari"
        assert len(hass.config_entries.written) == writes_before

    def test_vacant_slot_mutation_does_not_create_state(self):
        _hass, _entry, coord = _make_coordinator({"slots": {}})
        coord.get_slot(9)["name"] = "ghost"
        assert coord.get_slot(9)["name"] == ""
        assert "9" not in coord._slots


class TestCapabilitySlotCeiling:
    """max_user_slot follows the lock's reported capacity, else the manual."""

    def test_default_ceiling_without_capabilities(self):
        _hass, _entry, coord = _make_coordinator({"slots": {}})
        assert coord.max_user_slot() == 999

    def test_ceiling_follows_reported_capacity(self):
        _hass, _entry, coord = _make_coordinator({"slots": {}})
        coord.lock_capabilities["num_pin_users"] = 50
        assert coord.max_user_slot() == 49


class TestSlotNameFallback:
    """Unnamed slot 0 is the master user; other unnamed slots stay numbered."""

    def _coord(self, slots=None):
        _hass, _entry, coord = _make_coordinator({"slots": slots or {}})
        coord.strings = {"slot_fallback_name": "Plass {slot}", "slot_fallback_master": "Hovud"}
        return coord

    def test_unnamed_slot_0_uses_master_string(self):
        assert self._coord().get_slot_name(0) == "Hovud"

    def test_named_slot_0_uses_the_name(self):
        assert self._coord({"0": {"name": "Fredrik"}}).get_slot_name(0) == "Fredrik"

    def test_slots_1_and_2_keep_the_numbered_fallback(self):
        coord = self._coord()
        assert coord.get_slot_name(1) == "Plass 1"
        assert coord.get_slot_name(2) == "Plass 2"

    def test_english_default_without_loaded_strings(self):
        _hass, _entry, coord = _make_coordinator({"slots": {}})
        assert coord.get_slot_name(0) == "Master"


class GatedTransport:
    """Holds every send until the test opens the gate, and counts overlap."""

    def __init__(self):
        self.gate = asyncio.Event()
        self.started = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def send(self, command, params):
        self.started.append((command, params["user_id"]))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await self.gate.wait()
        self.in_flight -= 1
        return True


class TestPinOperationsAreSerialised:
    """The options flow and a service call must not interleave on one lock."""

    def test_second_operation_waits_for_the_first(self):
        transport = GatedTransport()
        _hass, _entry, coord = _make_coordinator({"slots": {}}, transport=transport)

        async def scenario():
            first = asyncio.create_task(coord.set_pin(5, "Kari", "1234"))
            second = asyncio.create_task(coord.clear_slot(5))
            third = asyncio.create_task(coord.clear_pin(6))
            for _ in range(5):
                await asyncio.sleep(0)
            # Only the first send is on the air; the others queue behind it.
            assert transport.started == [(0x0005, 5)]
            transport.gate.set()
            return await asyncio.gather(first, second, third)

        assert asyncio.run(scenario()) == [True, True, True]
        assert transport.max_in_flight == 1
        assert transport.started == [(0x0005, 5), (0x0007, 5), (0x0007, 6)]
        # The later clear_slot wins, as it was called last.
        assert coord.get_slot(5)["has_pin"] is False
        assert coord.get_slot(5)["name"] == ""

    def test_a_refused_slot_does_not_hold_the_lock(self):
        transport = GatedTransport()
        transport.gate.set()
        _hass, _entry, coord = _make_coordinator({"slots": {}}, transport=transport)
        with pytest.raises(ValueError):
            asyncio.run(coord.set_pin(0, "Master", "1234"))
        assert asyncio.run(coord.set_pin(5, "Kari", "1234")) is True


class TestLoadSlots:
    """Stored slots are read back in DEFAULT_SLOT's shape and nothing else."""

    def test_unknown_keys_are_dropped(self):
        stored = {"slots": {"5": {"name": "Kari", "has_pin": True, "has_rfid": True, "junk": 1}}}
        _hass, _entry, coord = _make_coordinator(stored)
        assert coord.get_slot(5) == {"name": "Kari", "has_pin": True}

    def test_missing_keys_come_from_the_default(self):
        _hass, _entry, coord = _make_coordinator({"slots": {"5": {"name": "Kari"}}})
        assert coord.get_slot(5) == {"name": "Kari", "has_pin": False}


class TestSetupState:
    """What the coordinator remembers from setup for the update listener."""

    def test_first_user_slot_at_setup_follows_the_option(self):
        _hass, _entry, coord = _make_coordinator({"slots": {}, "reserved_slots": 1})
        assert coord.setup_first_user_slot == 1

    def test_first_user_slot_at_setup_defaults_to_three(self):
        _hass, _entry, coord = _make_coordinator({"slots": {}})
        assert coord.setup_first_user_slot == 3

    def test_setup_value_does_not_follow_later_option_changes(self):
        _hass, entry, coord = _make_coordinator({"slots": {}})
        entry.options = {**entry.options, "reserved_slots": 2}
        assert coord.setup_first_user_slot == 3
        assert coord.first_user_slot() == 2

    def test_wake_echo_is_the_transports(self):
        class EchoTransport:
            pending = False

            def wake_echo_pending(self):
                return self.pending

        transport = EchoTransport()
        _hass, _entry, coord = _make_coordinator({"slots": {}}, transport=transport)
        assert coord.wake_echo_pending() is False
        transport.pending = True
        assert coord.wake_echo_pending() is True

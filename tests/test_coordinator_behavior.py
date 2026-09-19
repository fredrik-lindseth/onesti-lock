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

from .conftest import load_component_module

coordinator_mod = load_component_module("coordinator")


class FakeConfigEntry:
    def __init__(self, options=None):
        self.data = {"ieee": "00:11:22:33:44:55:66:77"}
        self.options = dict(options or {})


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


class FakeHass:
    def __init__(self, fail_services=False):
        self.config_entries = FakeConfigEntries()
        self.services = FakeServices(fail=fail_services)


def _make_coordinator(options=None, fail_services=False):
    hass = FakeHass(fail_services=fail_services)
    entry = FakeConfigEntry(options)
    return hass, entry, coordinator_mod.NimlyCoordinator(hass, entry)


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

    _OCCUPIED = {"slots": {"5": {"name": "Kari", "has_pin": True, "has_rfid": False}}}

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

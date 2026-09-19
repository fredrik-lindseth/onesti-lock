"""Executes the real service handlers against the capability ceiling.

services.py imports voluptuous and homeassistant, neither of which CI
installs, so both are stubbed with the little that the module actually
touches: a schema wrapper that is only stored, an error class that keeps
its translation key, and cv.string. That makes it possible to prove the
ceiling by calling handle_set_pin rather than by reading its source.

CI installs only pytest, so the tests are sync and drive the coroutines
with asyncio.run().
"""
from __future__ import annotations

import asyncio

import pytest
from homeassistant.exceptions import HomeAssistantError

from .conftest import load_component_module

services_mod = load_component_module("services")
pin_rules = load_component_module("pin_rules")
DELIVERED = load_component_module("zha").SEND_DELIVERED


class FakeCoordinator:
    """A lock whose reported capabilities the test controls."""

    def __init__(self, capabilities=None, options=None):
        self.ieee = "00:11:22:33:44:55:66:77"
        self.lock_capabilities = dict(capabilities or {})
        self.options = dict(options or {})
        self.set_pin_calls = []
        self.clear_pin_calls = []

    def first_user_slot(self):
        return pin_rules.first_user_slot(self.options)

    def max_user_slot(self):
        # The real coordinator method is one line over the same rule, so the
        # handler is exercised against the actual pin_rules logic.
        return pin_rules.max_user_slot(self.lock_capabilities)

    async def set_pin(self, slot, name, code):
        self.set_pin_calls.append((slot, name, code))
        return DELIVERED

    async def clear_pin(self, slot):
        self.clear_pin_calls.append(slot)
        return DELIVERED


class FakeServiceRegistry:
    def __init__(self):
        self.handlers = {}

    def async_register(self, domain, service, handler, schema=None):
        self.handlers[service] = handler

    def async_remove(self, domain, service):
        self.handlers.pop(service, None)


class FakeEntry:
    """A loaded config entry: HA keeps the coordinator on runtime_data."""

    def __init__(self, coordinator):
        self.entry_id = "entry_id"
        self.runtime_data = coordinator


class FakeConfigEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_loaded_entries(self, domain):
        return list(self._entries) if domain == "onesti_lock" else []


class FakeHass:
    def __init__(self, coordinator):
        self.config_entries = FakeConfigEntries([FakeEntry(coordinator)])
        self.services = FakeServiceRegistry()


class FakeCall:
    def __init__(self, **data):
        self.data = data


def _handlers(coordinator):
    hass = FakeHass(coordinator)
    asyncio.run(services_mod.async_setup_services(hass))
    return hass.services.handlers


class TestSetPinCapacityCeiling:
    """set_pin rejects slots above the reported capacity, and only then."""

    def test_slot_60_passes_while_capabilities_are_unread(self):
        coordinator = FakeCoordinator()
        handlers = _handlers(coordinator)
        asyncio.run(
            handlers["set_pin"](FakeCall(slot=60, name="Kari", code="1234"))
        )
        assert coordinator.set_pin_calls == [(60, "Kari", "1234")]

    def test_slot_60_is_rejected_when_the_lock_reports_fifty(self):
        coordinator = FakeCoordinator({"num_pin_users": 50})
        handlers = _handlers(coordinator)
        with pytest.raises(HomeAssistantError) as excinfo:
            asyncio.run(
                handlers["set_pin"](FakeCall(slot=60, name="Kari", code="1234"))
            )
        assert excinfo.value.translation_key == "invalid_slot"
        assert excinfo.value.translation_placeholders == {"min": "3", "max": "49"}
        assert coordinator.set_pin_calls == []

    def test_the_last_slot_within_capacity_still_passes(self):
        coordinator = FakeCoordinator({"num_pin_users": 50})
        handlers = _handlers(coordinator)
        asyncio.run(
            handlers["set_pin"](FakeCall(slot=49, name="Kari", code="1234"))
        )
        assert coordinator.set_pin_calls == [(49, "Kari", "1234")]

    def test_master_slots_are_still_rejected(self):
        coordinator = FakeCoordinator({"num_pin_users": 50})
        handlers = _handlers(coordinator)
        with pytest.raises(HomeAssistantError) as excinfo:
            asyncio.run(
                handlers["set_pin"](FakeCall(slot=2, name="Kari", code="1234"))
            )
        assert excinfo.value.translation_key == "invalid_slot"


class TestClearPinStaysPermissive:
    """Codes set before this version must remain removable."""

    def test_clear_pin_accepts_a_slot_above_the_reported_capacity(self):
        coordinator = FakeCoordinator({"num_pin_users": 50})
        handlers = _handlers(coordinator)
        asyncio.run(handlers["clear_pin"](FakeCall(slot=60)))
        assert coordinator.clear_pin_calls == [60]


class TestSetPinLength:
    """set_pin checks the code against the lock's reported PIN length."""

    def test_the_fallback_range_applies_while_capabilities_are_unread(self):
        coordinator = FakeCoordinator()
        handlers = _handlers(coordinator)
        with pytest.raises(HomeAssistantError) as excinfo:
            asyncio.run(
                handlers["set_pin"](FakeCall(slot=5, name="Kari", code="123456789"))
            )
        assert excinfo.value.translation_key == "invalid_pin"
        assert excinfo.value.translation_placeholders == {"min": "4", "max": "8"}
        assert coordinator.set_pin_calls == []

    def test_the_reported_range_is_enforced_and_named(self):
        coordinator = FakeCoordinator({"min_pin_length": 6, "max_pin_length": 10})
        handlers = _handlers(coordinator)
        with pytest.raises(HomeAssistantError) as excinfo:
            asyncio.run(
                handlers["set_pin"](FakeCall(slot=5, name="Kari", code="1234"))
            )
        assert excinfo.value.translation_key == "invalid_pin"
        assert excinfo.value.translation_placeholders == {"min": "6", "max": "10"}
        assert coordinator.set_pin_calls == []

    def test_a_code_inside_the_reported_range_is_sent(self):
        coordinator = FakeCoordinator({"min_pin_length": 6, "max_pin_length": 10})
        handlers = _handlers(coordinator)
        asyncio.run(
            handlers["set_pin"](FakeCall(slot=5, name="Kari", code="1234567890"))
        )
        assert coordinator.set_pin_calls == [(5, "Kari", "1234567890")]

    def test_the_error_never_carries_the_code(self):
        """Exceptions end up in the log and in automation traces."""
        coordinator = FakeCoordinator()
        handlers = _handlers(coordinator)
        with pytest.raises(HomeAssistantError) as excinfo:
            asyncio.run(
                handlers["set_pin"](FakeCall(slot=5, name="Kari", code="837291645"))
            )
        error = excinfo.value
        assert "837291645" not in str(error)
        assert "837291645" not in repr(error.translation_placeholders)


class TestWriteOutcomeReachesTheCaller:
    """What the lock did with the command decides the error, not just that it failed."""

    zha = load_component_module("zha")

    @pytest.mark.parametrize(
        ("outcome", "key", "placeholders"),
        [
            (zha.SEND_UNREACHED, "lock_unreachable", {}),
            (zha.rejected(0x0005, object(), 1), "lock_rejected", {"status": "1"}),
            (zha.rejected(0x0005, object(), 2), "lock_rejected_memory_full", {"status": "2"}),
            (zha.rejected(0x0005, object(), 3), "lock_rejected_duplicate", {"status": "3"}),
        ],
        ids=["unreached", "failure", "memory_full", "duplicate"],
    )
    def test_set_pin_error_follows_the_outcome(self, outcome, key, placeholders):
        coordinator = FakeCoordinator()

        async def set_pin(slot, name, code):
            return outcome

        coordinator.set_pin = set_pin
        with pytest.raises(HomeAssistantError) as excinfo:
            asyncio.run(_handlers(coordinator)["set_pin"](FakeCall(slot=5, name="Kari", code="1234")))
        assert excinfo.value.translation_key == key
        assert excinfo.value.translation_placeholders == placeholders

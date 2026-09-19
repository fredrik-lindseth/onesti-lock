"""Which lock a service call reaches: device_id, ieee, or the only lock.

Runs the real handlers from services.py under the shared stubs, with a fake
hass that holds any number of loaded locks and a device registry. The
coordinators record what they are asked to do, so every test can assert
that a refused call touched no lock at all. tests_ha/test_services.py runs
the same lookup against a real Home Assistant.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from .conftest import load_component_module

services_mod = load_component_module("services")
pin_rules = load_component_module("pin_rules")

DOMAIN = "onesti_lock"
FRONT = "00:0d:6f:00:11:22:33:44"
BACK = "00:0d:6f:00:55:66:77:88"


class FakeCoordinator:
    def __init__(self, ieee):
        self.ieee = ieee
        self.lock_capabilities = {}
        self.options = {}
        self.calls = []

    def first_user_slot(self):
        return pin_rules.first_user_slot(self.options)

    def max_user_slot(self):
        return pin_rules.max_user_slot(self.lock_capabilities)

    async def set_pin(self, slot, name, code):
        self.calls.append(("set_pin", slot))
        return True

    async def clear_pin(self, slot):
        self.calls.append(("clear_pin", slot))
        return True

    async def set_slot_name(self, slot, name):
        self.calls.append(("set_name", slot))

    async def clear_slot(self, slot):
        self.calls.append(("clear_slot", slot))
        return True


class FakeDeviceRegistry:
    def __init__(self, devices):
        self._devices = devices

    def async_get(self, device_id):
        return self._devices.get(device_id)


class FakeServiceRegistry:
    def __init__(self):
        self.handlers = {}

    def async_register(self, domain, service, handler, schema=None):
        self.handlers[service] = handler


class FakeConfigEntries:
    def __init__(self, coordinators):
        self._entries = [SimpleNamespace(runtime_data=c) for c in coordinators]

    def async_loaded_entries(self, domain):
        return list(self._entries) if domain == DOMAIN else []


class FakeCall:
    def __init__(self, **data):
        self.data = data


def _device(*identifiers):
    return SimpleNamespace(identifiers=set(identifiers))


# Each lock gets a device from this integration. The ZHA device of the same
# lock carries the same IEEE, but under ZHA's own domain.
DEVICES = {
    "front_device": _device((DOMAIN, FRONT)),
    "back_device": _device((DOMAIN, BACK)),
    "zha_front_device": _device(("zha", FRONT)),
    "orphan_device": _device((DOMAIN, "00:0d:6f:00:99:99:99:99")),
}

# One valid call per service, so the lookup tests can run on all four.
SERVICE_CALLS = {
    "set_pin": {"slot": 5, "name": "Kari", "code": "1234"},
    "clear_pin": {"slot": 5},
    "set_name": {"slot": 5, "name": "Kari"},
    "clear_slot": {"slot": 5},
}


def _setup(*ieees):
    coordinators = [FakeCoordinator(ieee) for ieee in ieees]
    hass = SimpleNamespace(
        config_entries=FakeConfigEntries(coordinators),
        services=FakeServiceRegistry(),
        device_registry=FakeDeviceRegistry(DEVICES),
    )
    asyncio.run(services_mod.async_setup_services(hass))
    return hass.services.handlers, coordinators


def _call(handlers, service, **target):
    asyncio.run(handlers[service](FakeCall(**SERVICE_CALLS[service], **target)))


def _refused(handlers, service, **target):
    with pytest.raises(HomeAssistantError) as excinfo:
        _call(handlers, service, **target)
    return excinfo.value


@pytest.mark.parametrize("service", SERVICE_CALLS)
class TestLockLookup:
    def test_two_locks_without_a_target_touch_neither(self, service):
        handlers, (front, back) = _setup(FRONT, BACK)
        error = _refused(handlers, service)
        assert error.translation_key == "multiple_locks"
        assert error.translation_placeholders == {"ieees": f"{FRONT}, {BACK}"}
        assert front.calls == back.calls == []

    def test_one_lock_without_a_target_works_as_before(self, service):
        handlers, (front,) = _setup(FRONT)
        _call(handlers, service)
        assert front.calls == [(service, 5)]

    def test_device_id_picks_the_lock(self, service):
        handlers, (front, back) = _setup(FRONT, BACK)
        _call(handlers, service, device_id="back_device")
        assert front.calls == []
        assert back.calls == [(service, 5)]

    def test_device_id_wins_over_ieee(self, service):
        handlers, (front, back) = _setup(FRONT, BACK)
        _call(handlers, service, device_id="back_device", ieee=FRONT)
        assert front.calls == []
        assert back.calls == [(service, 5)]

    def test_ieee_in_another_case_picks_the_lock(self, service):
        handlers, (front, back) = _setup(FRONT, BACK)
        _call(handlers, service, ieee=BACK.upper())
        assert front.calls == []
        assert back.calls == [(service, 5)]

    def test_unknown_ieee(self, service):
        handlers, (front,) = _setup(FRONT)
        error = _refused(handlers, service, ieee="00:00:00:00:00:00:00:01")
        assert error.translation_key == "lock_not_found_ieee"
        assert error.translation_placeholders == {"ieee": "00:00:00:00:00:00:00:01"}
        assert front.calls == []

    def test_a_device_from_another_integration_is_not_a_lock(self, service):
        """The ZHA device of the same lock does not count either."""
        handlers, (front,) = _setup(FRONT)
        error = _refused(handlers, service, device_id="zha_front_device")
        assert error.translation_key == "lock_not_found"
        assert front.calls == []

    def test_an_unknown_device_id_is_not_a_lock(self, service):
        handlers, (front,) = _setup(FRONT)
        error = _refused(handlers, service, device_id="no_such_device")
        assert error.translation_key == "lock_not_found"
        assert front.calls == []

    def test_an_onesti_device_whose_lock_is_not_loaded(self, service):
        handlers, (front,) = _setup(FRONT)
        error = _refused(handlers, service, device_id="orphan_device")
        assert error.translation_key == "lock_not_found_ieee"
        assert front.calls == []

    def test_no_lock_loaded(self, service):
        handlers, _ = _setup()
        error = _refused(handlers, service)
        assert error.translation_key == "lock_not_found"

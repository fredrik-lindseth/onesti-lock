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
import importlib.util
import os
import sys
import types

import pytest


class _StubHomeAssistantError(Exception):
    """Keeps the translation metadata the handlers attach."""

    def __init__(
        self,
        message="",
        *,
        translation_domain=None,
        translation_key=None,
        translation_placeholders=None,
    ):
        super().__init__(message)
        self.message = message
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders or {}


def _install_stubs():
    """Add the homeassistant and voluptuous names services.py imports."""
    if "homeassistant" not in sys.modules:
        sys.modules["homeassistant"] = types.ModuleType("homeassistant")
    ha = sys.modules["homeassistant"]

    if "homeassistant.core" not in sys.modules:
        core = types.ModuleType("homeassistant.core")
        sys.modules["homeassistant.core"] = core
        ha.core = core
    core = sys.modules["homeassistant.core"]
    # Other test modules install this stub too, with only the names they
    # need, so missing attributes are filled in rather than overwritten.
    if not hasattr(core, "HomeAssistant"):
        core.HomeAssistant = object
    if not hasattr(core, "ServiceCall"):
        core.ServiceCall = object

    if "homeassistant.exceptions" not in sys.modules:
        exceptions = types.ModuleType("homeassistant.exceptions")
        sys.modules["homeassistant.exceptions"] = exceptions
        ha.exceptions = exceptions
    exceptions = sys.modules["homeassistant.exceptions"]
    if not hasattr(exceptions, "HomeAssistantError"):
        exceptions.HomeAssistantError = _StubHomeAssistantError

    if "homeassistant.helpers" not in sys.modules:
        helpers = types.ModuleType("homeassistant.helpers")
        helpers.__path__ = []
        sys.modules["homeassistant.helpers"] = helpers
        ha.helpers = helpers
    helpers = sys.modules["homeassistant.helpers"]
    if "homeassistant.helpers.config_validation" not in sys.modules:
        cv = types.ModuleType("homeassistant.helpers.config_validation")
        cv.string = str
        sys.modules["homeassistant.helpers.config_validation"] = cv
        helpers.config_validation = cv

    if "voluptuous" not in sys.modules:
        vol = types.ModuleType("voluptuous")
        vol.Schema = lambda schema: schema
        vol.Required = lambda key: key
        vol.Optional = lambda key: key
        vol.Coerce = lambda type_: type_
        sys.modules["voluptuous"] = vol

    return sys.modules["homeassistant.exceptions"].HomeAssistantError


HomeAssistantError = _install_stubs()

_COMPONENT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "onesti_lock"
)
_PACKAGE = "onesti_lock_services_under_test"


def _load(module_name: str):
    """Load one component module under a stub package, like test_coordinator_behavior.py does."""
    if _PACKAGE not in sys.modules:
        package = types.ModuleType(_PACKAGE)
        package.__path__ = [_COMPONENT_DIR]
        sys.modules[_PACKAGE] = package
    name = f"{_PACKAGE}.{module_name}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_COMPONENT_DIR, f"{module_name}.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


services_mod = _load("services")
pin_rules = _load("pin_rules")


class FakeCoordinator:
    """A lock whose reported capabilities the test controls."""

    def __init__(self, capabilities=None):
        self.ieee = "00:11:22:33:44:55:66:77"
        self.lock_capabilities = dict(capabilities or {})
        self.set_pin_calls = []
        self.clear_pin_calls = []

    def max_user_slot(self):
        # The real coordinator method is one line over the same rule, so the
        # handler is exercised against the actual pin_rules logic.
        return pin_rules.max_user_slot(self.lock_capabilities)

    async def set_pin(self, slot, name, code):
        self.set_pin_calls.append((slot, name, code))
        return True

    async def clear_pin(self, slot):
        self.clear_pin_calls.append(slot)
        return True


class FakeServiceRegistry:
    def __init__(self):
        self.handlers = {}

    def async_register(self, domain, service, handler, schema=None):
        self.handlers[service] = handler

    def async_remove(self, domain, service):
        self.handlers.pop(service, None)


class FakeHass:
    def __init__(self, coordinator):
        self.data = {"onesti_lock": {"entry_id": {"coordinator": coordinator}}}
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

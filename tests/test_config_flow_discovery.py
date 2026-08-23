"""Behavioral tests for config flow device discovery.

Issue #5: a Connect Module can report a sibling model name (a CodePRO
presenting as NimlyTwist), so the model string must not gate discovery.
These tests run the real async_step_user against fake ZHA proxies and
verify that any Onesti device with a Door Lock cluster is offered,
regardless of model string, and that non-lock or foreign devices are not.

CI installs only pytest, so homeassistant and voluptuous are stubbed and
the coroutines run under asyncio.run().
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types

if "homeassistant" not in sys.modules:
    sys.modules["homeassistant"] = types.ModuleType("homeassistant")
if "homeassistant.core" not in sys.modules:
    _core = types.ModuleType("homeassistant.core")
    _core.HomeAssistant = object
    _core.callback = lambda f: f
    sys.modules["homeassistant"].core = _core
    sys.modules["homeassistant.core"] = _core
else:
    _core = sys.modules["homeassistant.core"]
    if not hasattr(_core, "callback"):
        _core.callback = lambda f: f
if "homeassistant.config_entries" not in sys.modules:
    _ce = types.ModuleType("homeassistant.config_entries")
    sys.modules["homeassistant"].config_entries = _ce
    sys.modules["homeassistant.config_entries"] = _ce
else:
    _ce = sys.modules["homeassistant.config_entries"]


class _StubConfigFlow:
    """Accepts the domain= class kwarg and records form/abort calls."""

    def __init_subclass__(cls, **kwargs):
        pass

    def async_abort(self, *, reason):
        return {"type": "abort", "reason": reason}

    def async_show_form(self, *, step_id, data_schema):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema}

    def async_create_entry(self, *, title, data, options):
        return {"type": "create_entry", "title": title, "data": data, "options": options}


_ce.ConfigEntry = getattr(_ce, "ConfigEntry", object)
_ce.ConfigFlow = _StubConfigFlow
_ce.ConfigFlowResult = dict
_ce.OptionsFlow = object

if "voluptuous" not in sys.modules:
    _vol = types.ModuleType("voluptuous")

    class _Schema:
        def __init__(self, schema):
            self.schema = schema

    class _Marker:
        def __init__(self, key, **kwargs):
            self.key = key

        def __hash__(self):
            return hash(self.key)

        def __eq__(self, other):
            return isinstance(other, _Marker) and other.key == self.key

    class _In:
        def __init__(self, container):
            self.container = container

    _vol.Schema = _Schema
    _vol.Required = _Marker
    _vol.Optional = _Marker
    _vol.In = _In
    _vol.All = lambda *a: a
    _vol.Range = lambda **kw: kw
    _vol.Coerce = lambda t: t
    sys.modules["voluptuous"] = _vol

_COMPONENT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "onesti_lock"
)
_PACKAGE = "onesti_lock_config_flow_under_test"


def _load_config_flow():
    if _PACKAGE not in sys.modules:
        package = types.ModuleType(_PACKAGE)
        package.__path__ = [_COMPONENT_DIR]
        sys.modules[_PACKAGE] = package
    name = f"{_PACKAGE}.config_flow"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_COMPONENT_DIR, "config_flow.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


config_flow = _load_config_flow()

DOORLOCK_CLUSTER_ID = 0x0101


class FakeEndpoint:
    def __init__(self, cluster_ids):
        self.in_clusters = {cid: object() for cid in cluster_ids}


class FakeZigpyDevice:
    """The deepest object in the chain — the one holding endpoints."""

    def __init__(self, manufacturer, model, cluster_ids=(DOORLOCK_CLUSTER_ID,)):
        self.manufacturer = manufacturer
        self.model = model
        self.endpoints = {0: FakeEndpoint([]), 11: FakeEndpoint(cluster_ids)}


class FakeProxy:
    """ZHADeviceProxy: metadata on .device, clusters one level deeper."""

    def __init__(self, zigpy_device):
        self.device = types.SimpleNamespace(
            manufacturer=zigpy_device.manufacturer,
            model=zigpy_device.model,
            device=zigpy_device,
        )


def _make_flow(proxies, existing_ieees=()):
    flow = config_flow.NimlyProConfigFlow()
    gateway = types.SimpleNamespace(
        gateway_proxy=types.SimpleNamespace(device_proxies=proxies)
    )
    flow.hass = types.SimpleNamespace(data={"zha": gateway})
    flow._async_current_entries = lambda: [
        types.SimpleNamespace(data={"ieee": ieee}) for ieee in existing_ieees
    ]
    return flow


def _offered_devices(result):
    assert result["type"] == "form", result
    markers = list(result["data_schema"].schema)
    return result["data_schema"].schema[markers[0]].container


class TestHasDoorLockCluster:
    def test_found_two_levels_down(self):
        proxy = FakeProxy(FakeZigpyDevice("Onesti Products AS", "NimlyPRO"))
        assert config_flow._has_door_lock_cluster(proxy)

    def test_absent(self):
        proxy = FakeProxy(
            FakeZigpyDevice("Onesti Products AS", "NimlyPRO", cluster_ids=(0x0006,))
        )
        assert not config_flow._has_door_lock_cluster(proxy)

    def test_no_endpoints_anywhere(self):
        assert not config_flow._has_door_lock_cluster(object())


class TestDiscovery:
    def test_unknown_model_with_lock_cluster_is_offered(self):
        """Issue #5: a CodePRO whose module reports as NimlyTwist."""
        proxies = {
            "aa:bb": FakeProxy(FakeZigpyDevice("Onesti Products AS", "NimlyTwist"))
        }
        result = asyncio.run(_make_flow(proxies).async_step_user())
        assert "aa:bb" in _offered_devices(result)

    def test_known_model_still_offered(self):
        proxies = {
            "aa:bb": FakeProxy(FakeZigpyDevice("Onesti Products AS", "NimlyCodePRO"))
        }
        result = asyncio.run(_make_flow(proxies).async_step_user())
        assert "aa:bb" in _offered_devices(result)

    def test_foreign_manufacturer_not_offered(self):
        proxies = {"aa:bb": FakeProxy(FakeZigpyDevice("Aqara", "DoorLock v1"))}
        result = asyncio.run(_make_flow(proxies).async_step_user())
        assert result["type"] == "abort"
        assert result["reason"] == "no_devices_found"

    def test_onesti_device_without_lock_cluster_not_offered(self):
        proxies = {
            "aa:bb": FakeProxy(
                FakeZigpyDevice(
                    "Onesti Products AS", "SomeBridge", cluster_ids=(0x0006,)
                )
            )
        }
        result = asyncio.run(_make_flow(proxies).async_step_user())
        assert result["type"] == "abort"
        assert result["reason"] == "no_devices_found"

    def test_already_configured_lock_not_offered_again(self):
        proxies = {
            "aa:bb": FakeProxy(FakeZigpyDevice("Onesti Products AS", "NimlyPRO"))
        }
        result = asyncio.run(
            _make_flow(proxies, existing_ieees=("aa:bb",)).async_step_user()
        )
        assert result["type"] == "abort"
        assert result["reason"] == "no_devices_found"

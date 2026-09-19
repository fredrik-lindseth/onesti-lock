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
import types

from .conftest import load_component_module

config_flow = load_component_module("config_flow")

DOORLOCK_CLUSTER_ID = 0x0101


class FakeEndpoint:
    def __init__(self, cluster_ids):
        self.in_clusters = {cid: object() for cid in cluster_ids}


class FakeZigpyDevice:
    """The deepest object in the chain, the one holding endpoints."""

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

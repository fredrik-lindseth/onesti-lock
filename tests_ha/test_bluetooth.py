"""bluetooth.py against Home Assistant's real Bluetooth integration.

tests/test_bluetooth.py checks the choices bluetooth.py makes against stubs.
Here the advertisements go into the Bluetooth manager of the pinned Home
Assistant, with the bleak, habluetooth and bleak-retry-connector releases
that Home Assistant ships, so the lookup, the callback matcher and the
BLEDevice handed to establish_connection are Home Assistant's own on both
ends of the supported range. Only establish_connection itself is replaced:
there is no radio. A full protocol session through Home Assistant needs the
fake lock importable without the tests/ stubs, which it is not yet.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect

import bleak_retry_connector
import pytest
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from habluetooth.usage import HaBleakClientWithServiceCache
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onesti_lock import bluetooth as lock_bluetooth
from custom_components.onesti_lock.ble import ADVERTISING_UUID, BleError, BleTimeoutError
from custom_components.onesti_lock.ble.client.bleak_transport import BleakTransport
from custom_components.onesti_lock.const import CONF_IEEE, DOMAIN
from tests_ha.conftest import LOCK_IEEE, inject_bluetooth_service_info

ADDRESS = "AA:BB:CC:DD:EE:01"
OTHER_ADDRESS = "AA:BB:CC:DD:EE:02"
DEVICE_ID = bytes.fromhex("0a1b2c3d4e5f")
SEED = bytes.fromhex("c0de")
FACTORY_DATA = bytes(2) + bytes.fromhex("010203040506")
ENROLLED_DATA = SEED + hashlib.sha1(SEED + DEVICE_ID).digest()[:6]


class FakeClient:
    """A connected bleak client with nothing behind it."""

    def __init__(self, disconnected_callback=None) -> None:
        self.disconnected_callback = disconnected_callback
        self.is_connected = True
        self.mtu_size = 247
        self.disconnect_calls = 0

    async def read_gatt_char(self, uuid):
        raise BleakError("Characteristic not found")

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.is_connected = False


@pytest.fixture
def connections(monkeypatch) -> list[dict]:
    """Replaces bleak-retry-connector's two calls in bluetooth.py and records them."""
    calls: list[dict] = []

    async def close_stale(address, only_other_adapters=False):
        calls.append({"close_stale": address})

    async def establish(client_class, device, name, **kwargs):
        # The real signature must accept what bluetooth.py passes.
        inspect.signature(bleak_retry_connector.establish_connection).bind(client_class, device, name, **kwargs)
        client = FakeClient(kwargs.get("disconnected_callback"))
        calls.append({"client_class": client_class, "device": device, "name": name, "client": client, **kwargs})
        return client

    monkeypatch.setattr(lock_bluetooth, "close_stale_connections_by_address", close_stale)
    monkeypatch.setattr(lock_bluetooth, "establish_connection", establish)
    return calls


async def test_the_manifest_dependency_sets_up_bluetooth(hass: HomeAssistant, mock_zha) -> None:
    entry = MockConfigEntry(domain=DOMAIN, version=2, unique_id=LOCK_IEEE, data={CONF_IEEE: LOCK_IEEE}, options={"slots": {}})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert {"bluetooth_adapters", "bluetooth"} <= hass.config.components


async def test_without_bluetooth_the_error_says_so(hass: HomeAssistant) -> None:
    with pytest.raises(BleError, match="Bluetooth integration is not set up"):
        lock_bluetooth.async_discovered_locks(hass)
    with pytest.raises(BleError, match="Bluetooth integration is not set up"):
        await lock_bluetooth.async_find_lock(hass, timeout=0.01)


async def test_finds_the_locks_home_assistant_has_heard(hass: HomeAssistant, enable_bluetooth) -> None:
    inject_bluetooth_service_info(hass, address=ADDRESS, service_data={ADVERTISING_UUID: ENROLLED_DATA})
    inject_bluetooth_service_info(hass, address=OTHER_ADDRESS, service_data={ADVERTISING_UUID: FACTORY_DATA})
    # Heard, but by nothing that can connect to it.
    inject_bluetooth_service_info(
        hass, address="AA:BB:CC:DD:EE:03", service_data={ADVERTISING_UUID: FACTORY_DATA}, connectable=False
    )
    inject_bluetooth_service_info(hass, address="AA:BB:CC:DD:EE:04", service_data={"0000fe24-0000-1000-8000-00805f9b34fb": b"x"})
    await hass.async_block_till_done()

    [enrolled] = lock_bluetooth.async_discovered_locks(hass, device_id=DEVICE_ID)
    assert (enrolled.address, enrolled.name, enrolled.rssi) == (ADDRESS, "NIMLY", -60)
    assert enrolled.advertisement.enrolled
    [factory] = lock_bluetooth.async_discovered_locks(hass)
    assert factory.address == OTHER_ADDRESS
    assert (await lock_bluetooth.async_find_lock(hass, device_id=DEVICE_ID)).address == ADDRESS


async def test_waits_for_the_lock_through_a_registered_callback(hass: HomeAssistant, enable_bluetooth) -> None:
    task = asyncio.create_task(lock_bluetooth.async_find_lock(hass, device_id=DEVICE_ID, timeout=5))
    await asyncio.sleep(0)
    inject_bluetooth_service_info(hass, address=OTHER_ADDRESS, service_data={ADVERTISING_UUID: FACTORY_DATA})
    await hass.async_block_till_done()
    assert not task.done()
    inject_bluetooth_service_info(hass, address=ADDRESS, service_data={ADVERTISING_UUID: ENROLLED_DATA})
    found = await task
    assert found.address == ADDRESS


async def test_no_advertisement_is_a_timeout(hass: HomeAssistant, enable_bluetooth) -> None:
    with pytest.raises(BleTimeoutError):
        await lock_bluetooth.async_find_lock(hass, device_id=DEVICE_ID, timeout=0.05)


async def test_connects_with_home_assistants_ble_device(hass: HomeAssistant, enable_bluetooth, connections) -> None:
    inject_bluetooth_service_info(hass, address=ADDRESS, service_data={ADVERTISING_UUID: ENROLLED_DATA})
    await hass.async_block_till_done()
    lock = await lock_bluetooth.async_find_lock(hass, device_id=DEVICE_ID)

    transport = await lock_bluetooth.async_connect(hass, lock)

    stale, call = connections
    assert stale == {"close_stale": ADDRESS}
    # habluetooth's wrapper, which routes through the best adapter or proxy,
    # not the class bleak-retry-connector defines.
    assert call["client_class"] is HaBleakClientWithServiceCache
    assert isinstance(call["device"], BLEDevice) and call["device"].address == ADDRESS
    assert call["name"] == "NIMLY"
    assert call["ble_device_callback"]().address == ADDRESS
    assert isinstance(transport, BleakTransport)
    assert transport.mtu_size == 247
    await transport.close()
    assert call["client"].disconnect_calls == 1


async def test_a_lock_no_adapter_can_reach(hass: HomeAssistant, enable_bluetooth, connections) -> None:
    lock = lock_bluetooth.FoundLock(ADDRESS, "NIMLY", -60, None)
    with pytest.raises(BleError, match="No Bluetooth adapter or proxy"):
        await lock_bluetooth.async_connect(hass, lock)
    assert connections == []


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (bleak_retry_connector.BleakOutOfConnectionSlotsError("no slots"), "No free connection slot"),
        (bleak_retry_connector.BleakNotFoundError("not found"), "is out of reach"),
        (bleak_retry_connector.BleakConnectionError("failed"), "Could not connect .*BleakConnectionError"),
        (bleak_retry_connector.BleakAbortedError("aborted"), "Could not connect .*BleakAbortedError"),
    ],
)
async def test_bleak_retry_connector_errors_become_ble_errors(
    hass: HomeAssistant, enable_bluetooth, monkeypatch, error, message
) -> None:
    """The real exception classes of each pinned release."""

    async def establish(*args, **kwargs):
        raise error

    monkeypatch.setattr(lock_bluetooth, "establish_connection", establish)
    inject_bluetooth_service_info(hass, address=ADDRESS, service_data={ADVERTISING_UUID: ENROLLED_DATA})
    await hass.async_block_till_done()
    lock = await lock_bluetooth.async_find_lock(hass, device_id=DEVICE_ID)
    with pytest.raises(BleError, match=message):
        await lock_bluetooth.async_connect(hass, lock)


async def test_a_session_that_fails_to_start_lets_go(hass: HomeAssistant, enable_bluetooth, connections) -> None:
    inject_bluetooth_service_info(hass, address=ADDRESS, service_data={ADVERTISING_UUID: ENROLLED_DATA})
    await hass.async_block_till_done()

    with pytest.raises(BleError, match="Reading the software revision failed"):
        async with lock_bluetooth.async_open_session(hass, device_id=DEVICE_ID):
            raise AssertionError("never entered")

    [_stale, call] = connections
    assert call["client"].disconnect_calls == 1

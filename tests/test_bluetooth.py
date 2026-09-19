"""bluetooth.py against the Home Assistant Bluetooth stubs in conftest.py.

The stubs hand every call to FakeBluetooth below, which holds the
advertisements Home Assistant has seen and plays the ones that arrive
later. establish_connection is replaced per test. What real Home Assistant
does with the same calls is tests_ha/test_bluetooth.py; this file covers the
choices bluetooth.py makes itself: which advertisement is the lock, when to
wait, how a failure reads, and that the connection is always let go.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("bleak", reason="bluetooth.py needs bleak, which the unit group installs")

from bleak.exc import BleakError  # noqa: E402

from .ble.fake_lock import FakeLock  # noqa: E402
from .conftest import load_component_module  # noqa: E402

bluetooth = load_component_module("bluetooth")
errors = load_component_module("ble.errors")
client_const = load_component_module("ble.client.const")
ha_bluetooth = sys.modules["homeassistant.components.bluetooth"]
retry_connector = sys.modules["bleak_retry_connector"]

ADDRESS = "AA:BB:CC:DD:EE:01"
OTHER_ADDRESS = "AA:BB:CC:DD:EE:02"
DEVICE_ID = bytes.fromhex("0a1b2c3d4e5f")
SEED = bytes.fromhex("c0de")


def run(coro):
    return asyncio.run(coro)


def factory_data(identifier: bytes = bytes.fromhex("010203040506")) -> bytes:
    return bytes(2) + identifier


def enrolled_data(device_id: bytes = DEVICE_ID, seed: bytes = SEED) -> bytes:
    return seed + hashlib.sha1(seed + device_id).digest()[:6]


def service_info(address: str = ADDRESS, data: bytes | None = None, *, name: str | None = "NIMLY", rssi: int = -60):
    service_data = {} if data is None else {client_const.ADVERTISING_UUID: data}
    return ha_bluetooth.BluetoothServiceInfoBleak(name=name, address=address, rssi=rssi, service_data=service_data)


class FakeBluetooth:
    """Home Assistant's Bluetooth manager, as the conftest stub asks it."""

    def __init__(self) -> None:
        self.service_infos: list = []
        self.devices: dict[str, object] = {}
        self.registrations: list[tuple] = []
        self.unregistered = 0
        self.device_lookups: list[str] = []

    def discovered(self, connectable: bool) -> list:
        assert connectable, "bluetooth.py only wants advertisements it can connect to"
        return list(self.service_infos)

    def ble_device(self, address: str, connectable: bool) -> object | None:
        assert connectable
        self.device_lookups.append(address)
        return self.devices.get(address)

    def register(self, callback, matcher, mode):
        registration = (callback, matcher, mode)
        self.registrations.append(registration)

        def unregister() -> None:
            self.registrations.remove(registration)
            self.unregistered += 1

        return unregister

    def advertise(self, info) -> None:
        """An advertisement arrives: every matching registration hears it."""
        for callback, matcher, _mode in list(self.registrations):
            if matcher["service_data_uuid"] in info.service_data:
                callback(info, ha_bluetooth.BluetoothChange.ADVERTISEMENT)


def make_hass(*, bluetooth_loaded: bool = True) -> SimpleNamespace:
    components = {"bluetooth"} if bluetooth_loaded else set()
    return SimpleNamespace(config=SimpleNamespace(components=components), bluetooth=FakeBluetooth())


@pytest.fixture
def hass() -> SimpleNamespace:
    return make_hass()


# --- Finding the lock ------------------------------------------------------------


class TestDiscoveredLocks:
    def test_a_factory_reset_lock_is_found_without_a_device_id(self, hass):
        hass.bluetooth.service_infos = [service_info(data=factory_data())]
        [found] = bluetooth.async_discovered_locks(hass)
        assert found.address == ADDRESS
        assert found.name == "NIMLY"
        assert found.rssi == -60
        assert not found.advertisement.enrolled

    def test_an_enrolled_lock_is_not_taken_for_a_factory_one(self, hass):
        hass.bluetooth.service_infos = [service_info(data=enrolled_data())]
        assert bluetooth.async_discovered_locks(hass) == []

    def test_the_enrolled_lock_is_found_by_its_device_id(self, hass):
        hass.bluetooth.service_infos = [
            service_info(OTHER_ADDRESS, enrolled_data(bytes.fromhex("ffffffffffff"))),
            service_info(ADDRESS, enrolled_data()),
            service_info("AA:BB:CC:DD:EE:03", factory_data()),
        ]
        [found] = bluetooth.async_discovered_locks(hass, device_id=DEVICE_ID)
        assert found.address == ADDRESS
        assert found.advertisement.matches(DEVICE_ID)

    def test_other_devices_and_broken_service_data_are_skipped(self, hass):
        hass.bluetooth.service_infos = [
            service_info("AA:BB:CC:DD:EE:03", None),
            # Something else under 0xFD00, too short to be a lock.
            service_info(OTHER_ADDRESS, b"\x00\x00\x01"),
            service_info(ADDRESS, factory_data()),
        ]
        assert [found.address for found in bluetooth.async_discovered_locks(hass)] == [ADDRESS]

    def test_the_address_narrows_it_whatever_its_case(self, hass):
        hass.bluetooth.service_infos = [service_info(ADDRESS, factory_data()), service_info(OTHER_ADDRESS, factory_data())]
        [found] = bluetooth.async_discovered_locks(hass, address=OTHER_ADDRESS.lower())
        assert found.address == OTHER_ADDRESS

    def test_a_lock_without_a_name_is_named_by_its_address(self, hass):
        hass.bluetooth.service_infos = [service_info(data=factory_data(), name=None)]
        [found] = bluetooth.async_discovered_locks(hass)
        assert found.name == ADDRESS


class TestFindLock:
    def test_a_lock_home_assistant_has_seen_is_returned_at_once(self, hass):
        hass.bluetooth.service_infos = [service_info(data=enrolled_data())]
        found = run(bluetooth.async_find_lock(hass, device_id=DEVICE_ID))
        assert found.address == ADDRESS
        assert hass.bluetooth.registrations == [] and hass.bluetooth.unregistered == 0

    def test_two_factory_reset_locks_without_an_address_are_refused(self, hass):
        hass.bluetooth.service_infos = [service_info(ADDRESS, factory_data()), service_info(OTHER_ADDRESS, factory_data())]
        with pytest.raises(errors.BleError, match="Found 2 locks where a factory-reset lock was wanted"):
            run(bluetooth.async_find_lock(hass))
        # With the address, the same two are no longer ambiguous.
        assert run(bluetooth.async_find_lock(hass, address=OTHER_ADDRESS)).address == OTHER_ADDRESS

    def test_waits_for_the_lock_to_advertise(self, hass):
        async def scenario():
            task = asyncio.create_task(bluetooth.async_find_lock(hass, device_id=DEVICE_ID, timeout=5))
            await asyncio.sleep(0)
            [(_callback, matcher, mode)] = hass.bluetooth.registrations
            assert matcher == {"service_data_uuid": client_const.ADVERTISING_UUID, "connectable": True}
            assert mode is ha_bluetooth.BluetoothScanningMode.PASSIVE
            # A factory lock and someone else's enrolled lock go by first.
            hass.bluetooth.advertise(service_info(OTHER_ADDRESS, factory_data()))
            hass.bluetooth.advertise(service_info(OTHER_ADDRESS, enrolled_data(bytes.fromhex("ffffffffffff"))))
            hass.bluetooth.advertise(service_info(ADDRESS, b"\x01"))
            assert not task.done()
            hass.bluetooth.advertise(service_info(ADDRESS, enrolled_data()))
            # A second advertisement before the task resumes changes nothing.
            hass.bluetooth.advertise(service_info(ADDRESS, enrolled_data(), rssi=-40))
            return await task

        found = run(scenario())
        assert found.address == ADDRESS and found.rssi == -60
        assert hass.bluetooth.registrations == [] and hass.bluetooth.unregistered == 1

    def test_waiting_for_an_address_ignores_other_addresses(self, hass):
        async def scenario():
            task = asyncio.create_task(bluetooth.async_find_lock(hass, address=ADDRESS.lower(), timeout=5))
            await asyncio.sleep(0)
            hass.bluetooth.advertise(service_info(OTHER_ADDRESS, factory_data()))
            assert not task.done()
            hass.bluetooth.advertise(service_info(ADDRESS, factory_data()))
            return await task

        assert run(scenario()).address == ADDRESS

    def test_no_advertisement_in_time_is_a_timeout(self, hass):
        with pytest.raises(errors.BleTimeoutError) as caught:
            run(bluetooth.async_find_lock(hass, device_id=DEVICE_ID, address=ADDRESS, timeout=0.01))
        assert str(caught.value) == f"Did not see the enrolled lock at {ADDRESS} advertising within 0.01 s"
        assert isinstance(caught.value, TimeoutError)
        assert DEVICE_ID.hex() not in str(caught.value)
        assert hass.bluetooth.registrations == [] and hass.bluetooth.unregistered == 1


class TestBluetoothNotSetUp:
    """A clear BleError, not whatever Home Assistant's internals raise."""

    def test_every_entry_point_says_so(self):
        hass = make_hass(bluetooth_loaded=False)
        lock = bluetooth.FoundLock(ADDRESS, "NIMLY", -60, None)
        for call in (
            lambda: bluetooth.async_discovered_locks(hass),
            lambda: run(bluetooth.async_find_lock(hass)),
            lambda: run(bluetooth.async_connect(hass, lock)),
        ):
            with pytest.raises(errors.BleError, match="Bluetooth integration is not set up"):
                call()
        assert hass.bluetooth.device_lookups == []


# --- Connecting ----------------------------------------------------------------------


class FakeClient:
    """A connected bleak client with nothing behind it."""

    def __init__(self, disconnected_callback=None, mtu_size: int = 185) -> None:
        self.disconnected_callback = disconnected_callback
        self.is_connected = True
        self.mtu_size = mtu_size
        self.disconnect_calls = 0
        communication = SimpleNamespace(uuid=client_const.COMMUNICATION_CHARACTERISTIC_UUID, properties=["write"])
        self.services = SimpleNamespace(get_characteristic=lambda uuid: communication)

    async def start_notify(self, characteristic, callback) -> None:
        pass

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.is_connected = False


class Connector:
    """Stands in for bleak_retry_connector's two calls, and records them."""

    def __init__(self, make_client=FakeClient, error: BaseException | None = None) -> None:
        self.make_client = make_client
        self.error = error
        self.calls: list[tuple] = []
        self.client = None

    async def close_stale(self, address, only_other_adapters=False):
        self.calls.append(("close_stale", address))

    async def establish(self, client_class, device, name, *, disconnected_callback=None, ble_device_callback=None):
        self.calls.append(("establish", client_class, device, name, disconnected_callback, ble_device_callback))
        if self.error is not None:
            raise self.error
        self.client = self.make_client(disconnected_callback)
        return self.client


@pytest.fixture
def connector(monkeypatch) -> Connector:
    connector = Connector()
    monkeypatch.setattr(bluetooth, "close_stale_connections_by_address", connector.close_stale)
    monkeypatch.setattr(bluetooth, "establish_connection", connector.establish)
    return connector


def found_lock(address: str = ADDRESS):
    return bluetooth.FoundLock(address, "NIMLY", -60, None)


class TestConnect:
    def test_connects_like_home_assistants_own_integrations(self, hass, connector):
        device = object()
        hass.bluetooth.devices[ADDRESS] = device
        transport = run(bluetooth.async_connect(hass, found_lock()))

        stale, establish = connector.calls
        assert stale == ("close_stale", ADDRESS)
        _, client_class, used_device, name, disconnected_callback, ble_device_callback = establish
        assert client_class is retry_connector.BleakClientWithServiceCache
        assert used_device is device
        assert name == "NIMLY"
        assert transport.mtu_size == 185

        # Before every retry bleak-retry-connector asks for the best path now;
        # a lock Home Assistant lost track of keeps the first one.
        newer = object()
        hass.bluetooth.devices[ADDRESS] = newer
        assert ble_device_callback() is newer
        del hass.bluetooth.devices[ADDRESS]
        assert ble_device_callback() is device

    def test_the_client_class_is_the_one_installed_now(self, hass, connector, monkeypatch):
        """habluetooth swaps in its own wrapper after bluetooth.py was imported."""

        class HaWrapper:
            pass

        monkeypatch.setattr(retry_connector, "BleakClientWithServiceCache", HaWrapper)
        hass.bluetooth.devices[ADDRESS] = object()
        run(bluetooth.async_connect(hass, found_lock()))
        assert connector.calls[1][1] is HaWrapper

    def test_a_drop_reaches_the_session_through_the_transport(self, hass, connector):
        hass.bluetooth.devices[ADDRESS] = object()
        transport = run(bluetooth.async_connect(hass, found_lock()))
        dropped = []

        # start_notify is where the session hands over its callback.
        run(transport.start_notify(lambda data: None, lambda: dropped.append(True)))
        connector.client.disconnected_callback(connector.client)
        assert dropped == [True]

    def test_a_drop_before_the_transport_exists_is_ignored(self, hass, monkeypatch):
        def make_client(disconnected_callback):
            # establish_connection has returned the client, bluetooth.py has
            # not wrapped it yet.
            disconnected_callback(None)
            return FakeClient(disconnected_callback)

        connector = Connector(make_client)
        monkeypatch.setattr(bluetooth, "close_stale_connections_by_address", connector.close_stale)
        monkeypatch.setattr(bluetooth, "establish_connection", connector.establish)
        hass.bluetooth.devices[ADDRESS] = object()
        run(bluetooth.async_connect(hass, found_lock()))

    def test_no_adapter_or_proxy_in_reach(self, hass, connector):
        with pytest.raises(errors.BleError, match=f"No Bluetooth adapter or proxy .* reach the lock at {ADDRESS}"):
            run(bluetooth.async_connect(hass, found_lock()))
        assert connector.calls == []

    @pytest.mark.parametrize(
        ("error", "kind", "message"),
        [
            pytest.param(TimeoutError(), errors.BleTimeoutError, f"Connecting to the lock at {ADDRESS} timed out", id="timeout"),
            pytest.param(
                retry_connector.BleakOutOfConnectionSlotsError("all 3 slots in use"),
                errors.BleError,
                "No free connection slot to reach the lock at .*a Bluetooth proxy has only a few",
                id="slots",
            ),
            pytest.param(
                retry_connector.BleakNotFoundError("gone"), errors.BleError, f"The lock at {ADDRESS} is out of reach: gone", id="not-found"
            ),
            pytest.param(
                BleakError("failed with 12345678"),
                errors.BleError,
                r"Could not connect to the lock at .*: BleakError: failed with \*\*\*\*",
                id="bleak",
            ),
        ],
    )
    def test_failures_become_ble_errors(self, hass, monkeypatch, error, kind, message):
        connector = Connector(error=error)
        monkeypatch.setattr(bluetooth, "close_stale_connections_by_address", connector.close_stale)
        monkeypatch.setattr(bluetooth, "establish_connection", connector.establish)
        hass.bluetooth.devices[ADDRESS] = object()
        with pytest.raises(kind, match=message) as caught:
            run(bluetooth.async_connect(hass, found_lock()))
        assert caught.value.__cause__ is error


# --- A whole session -------------------------------------------------------------------


class LockClient:
    """A bleak client whose far end is a FakeLock: its FakeTransport in bleak's shape."""

    def __init__(self, lock: FakeLock, disconnected_callback) -> None:
        self.link = lock.connect(require_login=False)
        self.disconnected_callback = disconnected_callback
        self.is_connected = True
        self.mtu_size = 23
        self.communication = SimpleNamespace(uuid=client_const.COMMUNICATION_CHARACTERISTIC_UUID, properties=["write", "notify"])
        self.services = SimpleNamespace(
            get_characteristic=lambda uuid: self.communication if uuid == self.communication.uuid else None
        )
        self.disconnect_calls = 0

    async def read_gatt_char(self, uuid):
        assert uuid == client_const.SOFTWARE_REVISION_CHARACTERISTIC_UUID
        return bytearray(await self.link.read_software_revision())

    async def start_notify(self, characteristic, callback):
        await self.link.start_notify(lambda data: callback(characteristic, bytearray(data)), lambda: None)

    async def stop_notify(self, characteristic):
        pass

    async def write_gatt_char(self, characteristic, data, response):
        assert response is True
        await self.link.write(bytes(data))

    async def disconnect(self):
        self.disconnect_calls += 1
        self.is_connected = False
        await self.link.close()
        self.disconnected_callback(self)


class TestOpenSession:
    @pytest.fixture
    def lock_connector(self, hass, monkeypatch) -> Connector:
        lock = FakeLock()
        connector = Connector(lambda disconnected_callback: LockClient(lock, disconnected_callback))
        monkeypatch.setattr(bluetooth, "close_stale_connections_by_address", connector.close_stale)
        monkeypatch.setattr(bluetooth, "establish_connection", connector.establish)
        hass.bluetooth.service_infos = [service_info(data=factory_data())]
        hass.bluetooth.devices[ADDRESS] = object()
        return connector

    def test_finds_connects_exchanges_keys_and_lets_go(self, hass, lock_connector):
        async def scenario():
            async with bluetooth.async_open_session(hass, command_delay=0) as session:
                assert session.connected
                assert session.firmware == (4, 8, 0)
                assert lock_connector.client.is_connected
            return session

        session = run(scenario())
        assert not session.connected
        assert lock_connector.client.disconnect_calls == 1

    def test_lets_go_when_the_block_raises(self, hass, lock_connector):
        async def scenario():
            async with bluetooth.async_open_session(hass, command_delay=0):
                raise RuntimeError("the caller's own failure")

        with pytest.raises(RuntimeError):
            run(scenario())
        assert lock_connector.client.disconnect_calls == 1

    def test_lets_go_when_the_key_exchange_fails(self, hass, lock_connector, monkeypatch):
        async def scenario():
            async with bluetooth.async_open_session(hass, command_delay=0, response_timeout=0.01):
                raise AssertionError("never entered")

        # The lock never answers the key exchange.
        original = lock_connector.make_client

        def silent_client(disconnected_callback):
            client = original(disconnected_callback)
            client.link.silent.update(set(load_component_module("ble.protocol.const").CommandId))
            return client

        lock_connector.make_client = silent_client
        with pytest.raises(errors.BleTimeoutError):
            run(scenario())
        assert lock_connector.client.disconnect_calls == 1

    def test_lets_go_when_the_session_cannot_be_built(self, hass, lock_connector):
        async def scenario():
            async with bluetooth.async_open_session(hass, no_such_option=True):
                raise AssertionError("never entered")

        with pytest.raises(TypeError):
            run(scenario())
        assert lock_connector.client.disconnect_calls == 1

"""Everything that knows Home Assistant's Bluetooth integration and bleak-retry-connector.

The counterpart of zha.py for the lock's Bluetooth side. The protocol itself
lives in ble/, which may not import Home Assistant (gotcha 13), and
ble/client/bleak_transport.py speaks it over a connected bleak client. This
module does the Home Assistant half: find the lock among what the Bluetooth
integration has seen, connect through bleak-retry-connector the way Home
Assistant's own Bluetooth integrations do, and hand the client to
BleakTransport.

An ESPHome Bluetooth proxy needs nothing of its own here. habluetooth routes
the connection through whichever adapter or proxy hears the lock best, as
long as the proxy has active connections enabled. A proxy has only a few
connection slots, so async_open_session closes the connection as soon as the
caller is done with it.

Nothing in the integration uses this yet: no config flow step, no
coordinator, and __init__.py does not import it.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import bleak_retry_connector
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakNotFoundError,
    BleakOutOfConnectionSlotsError,
    close_stale_connections_by_address,
    establish_connection,
)

# bluetooth_adapters is a manifest dependency and depends on bluetooth, so
# this package and the bleak stack it ships are importable whenever this
# integration is, and set up before it.
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

from .ble import (
    ADVERTISING_UUID,
    Advertisement,
    BleError,
    BleProtocolError,
    BleTimeoutError,
    Session,
    parse_advertisement,
)
from .ble.client.bleak_transport import BleakTransport
from .const import BLE_ADVERTISEMENT_TIMEOUT_S, BLUETOOTH_DOMAIN
from .redact import redact_digits

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FoundLock:
    """A lock Home Assistant has heard advertising, and where."""

    address: str
    name: str
    rssi: int
    advertisement: Advertisement


def _require_bluetooth(hass: HomeAssistant) -> None:
    """Raise BleError unless Home Assistant's Bluetooth integration is set up.

    Without it the API below fails in ways that name Home Assistant's
    internals: a RuntimeError from habluetooth's manager lookup in the
    releases we pin, a KeyError from hass.data in older ones. The manifest
    dependency sets it up before us, so this guards a caller that runs
    before or after that, and tests.
    """
    if BLUETOOTH_DOMAIN not in hass.config.components:
        raise BleError("Home Assistant's Bluetooth integration is not set up, so no lock can be reached over Bluetooth")


def _lock_advertisement(service_info: bluetooth.BluetoothServiceInfoBleak) -> Advertisement | None:
    """The lock's 0xFD00 service data, parsed, or None when it has none that parses."""
    data = service_info.service_data.get(ADVERTISING_UUID)
    if data is None:
        return None
    try:
        return parse_advertisement(data)
    except BleProtocolError as err:
        # Something else advertising under 0xFD00, or a truncated packet.
        _LOGGER.debug("Ignoring 0xFD00 service data from %s: %s", service_info.address, err)
        return None


def _is_wanted(advertisement: Advertisement, device_id: bytes | None) -> bool:
    """Our enrolled lock when device_id is given, otherwise any factory-reset lock."""
    if device_id is None:
        return not advertisement.enrolled
    return advertisement.matches(device_id)


def _found(service_info: bluetooth.BluetoothServiceInfoBleak, advertisement: Advertisement) -> FoundLock:
    return FoundLock(
        address=service_info.address,
        name=service_info.name or service_info.address,
        rssi=service_info.rssi,
        advertisement=advertisement,
    )


def _same_address(a: str, b: str) -> bool:
    return a.upper() == b.upper()


def _describe(device_id: bytes | None, address: str | None) -> str:
    """Which lock is being looked for, for a message; never the device id itself."""
    what = "the enrolled lock" if device_id is not None else "a factory-reset lock"
    return f"{what} at {address}" if address is not None else what


def async_discovered_locks(
    hass: HomeAssistant, *, device_id: bytes | None = None, address: str | None = None
) -> list[FoundLock]:
    """Every wanted lock among the connectable advertisements Home Assistant holds.

    device_id picks the enrolled lock with that id (Advertisement.matches);
    without it, locks nobody has enrolled (seed 00 00) are wanted. address,
    when given, narrows it to one Bluetooth address. The list is empty when
    none is known right now, which is not an error: see async_find_lock for
    waiting.
    """
    _require_bluetooth(hass)
    found = []
    for service_info in bluetooth.async_discovered_service_info(hass, connectable=True):
        if address is not None and not _same_address(service_info.address, address):
            continue
        advertisement = _lock_advertisement(service_info)
        if advertisement is not None and _is_wanted(advertisement, device_id):
            found.append(_found(service_info, advertisement))
    return found


async def async_find_lock(
    hass: HomeAssistant,
    *,
    device_id: bytes | None = None,
    address: str | None = None,
    timeout: float = BLE_ADVERTISEMENT_TIMEOUT_S,
) -> FoundLock:
    """The wanted lock, from what Home Assistant has seen or the next advertisement.

    Looks among the advertisements Home Assistant already holds first. When
    the lock is not among them, waits up to timeout seconds for one and
    raises BleTimeoutError if none comes. More than one factory-reset lock
    in range with no address to tell them apart raises BleError, since
    enrolling the wrong one would hand over a neighbour's lock; while
    waiting, the first to advertise is taken.
    """
    known = async_discovered_locks(hass, device_id=device_id, address=address)
    if len(known) > 1:
        raise BleError(
            f"Found {len(known)} locks where {_describe(device_id, address)} was wanted; "
            "give the address of the one to use"
        )
    if known:
        return known[0]

    loop = asyncio.get_running_loop()
    result: asyncio.Future[FoundLock] = loop.create_future()

    @callback
    def _advertised(service_info: bluetooth.BluetoothServiceInfoBleak, _change: bluetooth.BluetoothChange) -> None:
        if result.done() or (address is not None and not _same_address(service_info.address, address)):
            return
        advertisement = _lock_advertisement(service_info)
        if advertisement is not None and _is_wanted(advertisement, device_id):
            result.set_result(_found(service_info, advertisement))

    # The address is checked in the callback rather than in the matcher,
    # which compares it case-sensitively. The service data rides in the
    # advertisement itself, so no scan response is needed and passive
    # scanning is enough.
    matcher = bluetooth.BluetoothCallbackMatcher(service_data_uuid=ADVERTISING_UUID, connectable=True)
    unregister = bluetooth.async_register_callback(hass, _advertised, matcher, bluetooth.BluetoothScanningMode.PASSIVE)
    try:
        async with asyncio.timeout(timeout):
            return await result
    except TimeoutError as err:
        raise BleTimeoutError(
            f"Did not see {_describe(device_id, address)} advertising within {timeout:g} s"
        ) from err
    finally:
        unregister()


class _DisconnectRelay:
    """bleak's disconnected_callback, pointed at the transport once there is one.

    establish_connection builds the client, and bleak wants the callback at
    construction, before BleakTransport can exist. A drop in that gap has
    nobody to tell, and is not lost: BleakTransport refuses a client that is
    no longer connected.
    """

    def __init__(self) -> None:
        self.transport: BleakTransport | None = None

    def __call__(self, client: Any) -> None:
        if self.transport is not None:
            self.transport.client_disconnected(client)


async def async_connect(hass: HomeAssistant, lock: FoundLock) -> BleakTransport:
    """Connect to a found lock and return the transport for a Session.

    Goes the way Home Assistant's Bluetooth integrations do: take the
    BLEDevice for the best connectable path now, drop connections a crashed
    run may have left on any adapter, and connect with bleak-retry-connector,
    which retries, backs off, and asks ble_device_callback for a fresh path
    before every attempt, so a proxy that has come into range is used.

    Raises BleTimeoutError when connecting timed out and BleError for any
    other failure, with a message a person can act on. The caller owns the
    transport and must close it; async_open_session does.
    """
    _require_bluetooth(hass)
    ble_device = bluetooth.async_ble_device_from_address(hass, lock.address, connectable=True)
    if ble_device is None:
        raise BleError(
            f"No Bluetooth adapter or proxy with active connections can reach the lock at {lock.address}"
        )

    def _latest_device() -> BLEDevice:
        return bluetooth.async_ble_device_from_address(hass, lock.address, connectable=True) or ble_device

    relay = _DisconnectRelay()
    try:
        await close_stale_connections_by_address(lock.address)
        client = await establish_connection(
            # Read off the module at call time, never imported by name: while
            # the Bluetooth integration runs, habluetooth replaces this class
            # with its own wrapper, and that wrapper is what picks the adapter
            # or proxy. A reference taken before it did would connect past
            # Home Assistant's Bluetooth stack.
            bleak_retry_connector.BleakClientWithServiceCache,
            ble_device,
            lock.name,
            disconnected_callback=relay,
            ble_device_callback=_latest_device,
        )
    except TimeoutError as err:
        raise BleTimeoutError(f"Connecting to the lock at {lock.address} timed out") from err
    except BleakOutOfConnectionSlotsError as err:
        raise BleError(
            f"No free connection slot to reach the lock at {lock.address}; "
            f"a Bluetooth proxy has only a few: {redact_digits(err)}"
        ) from err
    except BleakNotFoundError as err:
        raise BleError(f"The lock at {lock.address} is out of reach: {redact_digits(err)}") from err
    except BleakError as err:
        raise BleError(
            f"Could not connect to the lock at {lock.address}: {type(err).__name__}: {redact_digits(err)}"
        ) from err
    transport = BleakTransport(client)
    relay.transport = transport
    _LOGGER.debug("Connected to %s (%s), MTU %s", lock.name, lock.address, transport.mtu_size)
    return transport


@asynccontextmanager
async def async_open_session(
    hass: HomeAssistant,
    *,
    device_id: bytes | None = None,
    address: str | None = None,
    advertisement_timeout: float = BLE_ADVERTISEMENT_TIMEOUT_S,
    **session_options: Any,
) -> AsyncIterator[Session]:
    """A connected, key-exchanged Session with the lock, closed on exit.

        async with async_open_session(hass, device_id=enrollment.device_id) as session:
            await authenticate_owner(session, enrollment.owner_credential)
            battery = await session.request(commands.batt_info_get(), responses.parse_batt_info)

    Finds the lock (async_find_lock), connects (async_connect) and enters
    the Session, which reads the firmware and runs the key exchange. The
    connection is released on leaving the block, whatever happened in it,
    because a proxy's connection slots are few and a held one blocks other
    integrations. session_options go to Session unchanged.
    """
    lock = await async_find_lock(hass, device_id=device_id, address=address, timeout=advertisement_timeout)
    transport = await async_connect(hass, lock)
    try:
        session = Session(transport, **session_options)
    except BaseException:
        await transport.close()
        raise
    # Session closes the transport on leaving, and on a failed connect too.
    async with session:
        yield session

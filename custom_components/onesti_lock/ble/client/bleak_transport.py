"""A Transport over bleak, for a lock that bleak has already connected to.

This is the one module in ble/ that imports bleak, and ble/__init__.py does
not import it, so the rest of the library loads without bleak installed.
Import it as ble.client.bleak_transport.

It runs on two bleak releases: 0.22.3, which Home Assistant 2025.6 ships, and
3.0.2, which Home Assistant 2026.9 and the command line tool use. It touches
only what both have: the BleakClient constructor's disconnected_callback and
timeout, connect, disconnect, is_connected, mtu_size, services with
get_characteristic and properties, read_gatt_char, write_gatt_char with an
explicit response flag, start_notify and stop_notify. BleakGATTProtocolError
exists only from 3.0, so it is caught through its base, BleakError.

bleak can only be told about a disconnect when the BleakClient is built, and
the client exists before the transport does. Whoever builds the client
therefore routes its disconnected_callback to client_disconnected() once the
transport exists; BleakTransport.connect() does that for a plain BleakClient,
and a caller that connects some other way (Home Assistant's
establish_connection) does the same by hand. A link that dropped before the
transport was built shows as a client that is not connected, and is refused.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Final

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from ..errors import BleDisconnectedError, BleError, BleTimeoutError
from .const import COMMUNICATION_CHARACTERISTIC_UUID, SOFTWARE_REVISION_CHARACTERISTIC_UUID
from .transport import DisconnectCallback, NotificationCallback, write_with_response

_LOGGER = logging.getLogger(__name__)

# What a GATT call on bleak can fail with besides TimeoutError. BleakError is
# bleak's own base, and covers BleakGATTProtocolError and
# BleakCharacteristicNotFoundError. EOFError and OSError (BrokenPipeError,
# ConnectionResetError) come out of the D-Bus socket on BlueZ when bluetoothd
# or the link goes away mid-call; bleak-retry-connector treats the same set as
# link failures. TimeoutError is an OSError too, and is caught before these.
_BLEAK_ERRORS: Final = (BleakError, EOFError, OSError)

# bleak's default connect timeout on 0.22 (3.0 raised it to 30 s).
DEFAULT_CONNECT_TIMEOUT_S: Final = 10.0


class BleakTransport:
    """The Transport the Session needs, on a connected bleak.BleakClient.

    The client must have discovered its services, as BleakClient.connect()
    and Home Assistant's establish_connection both do. Writes go without
    response when the communication characteristic lists
    "write-without-response", and with response only when it lists "write"
    alone; transport.write_with_response() explains why that is what the app
    does. Every failure comes out as a BleError:
    BleTimeoutError for a timeout, BleDisconnectedError once the link is
    gone, BleError for anything else bleak raised.
    """

    def __init__(self, client: BleakClient) -> None:
        if not client.is_connected:
            raise BleDisconnectedError("The bleak client is not connected")
        self._client = client
        self._characteristic: BleakGATTCharacteristic | None = None
        self._write_with_response = True
        self._on_notification: NotificationCallback | None = None
        self._on_disconnect: DisconnectCallback | None = None
        self._subscribed = False
        self._link_lost = False
        self._closed = False

    @classmethod
    async def connect(
        cls,
        device: BLEDevice | str,
        *,
        timeout: float = DEFAULT_CONNECT_TIMEOUT_S,
        client_class: Callable[..., BleakClient] = BleakClient,
    ) -> BleakTransport:
        """Connect a new client_class to device and wrap it, disconnect callback wired.

        device is a BLEDevice from a scan, or an address (a CoreBluetooth
        UUID on macOS). client_class is called like BleakClient, with the
        device, disconnected_callback and timeout.
        """
        transport: BleakTransport | None = None

        def disconnected(client: BleakClient) -> None:
            if transport is not None:
                transport.client_disconnected(client)

        client = client_class(device, disconnected_callback=disconnected, timeout=timeout)
        try:
            await client.connect()
        except TimeoutError as err:
            raise BleTimeoutError(f"Connecting to the lock timed out after {timeout:g} s") from err
        except _BLEAK_ERRORS as err:
            raise BleError(f"Connecting to the lock failed: {_describe(err)}") from err
        # No await since connect() returned, so no disconnect can have been
        # delivered in between; one that happened before shows in the check
        # in __init__.
        transport = cls(client)
        return transport

    @property
    def mtu_size(self) -> int:
        """The MTU the link negotiated, for the log. Session frames for 23 regardless."""
        return self._client.mtu_size

    @property
    def write_with_response(self) -> bool:
        """Whether writes ask for a response; known once start_notify or write has run."""
        return self._write_with_response

    def client_disconnected(self, client: BleakClient) -> None:
        """The BleakClient's disconnected_callback: tell the session the link is gone.

        bleak calls it for our own close() too, which is ignored, as is a
        second call.
        """
        if self._closed or self._link_lost:
            return
        self._link_lost = True
        if self._on_disconnect is not None:
            self._on_disconnect()

    # --- Transport -----------------------------------------------------------------

    async def read_software_revision(self) -> bytes:
        self._check_open()
        try:
            return bytes(await self._client.read_gatt_char(SOFTWARE_REVISION_CHARACTERISTIC_UUID))
        except TimeoutError as err:
            raise BleTimeoutError("Reading the software revision timed out") from err
        except _BLEAK_ERRORS as err:
            raise self._failed("Reading the software revision", err) from err

    async def start_notify(self, on_notification: NotificationCallback, on_disconnect: DisconnectCallback) -> None:
        self._check_open()
        characteristic = self._communication_characteristic()
        self._on_notification = on_notification
        self._on_disconnect = on_disconnect
        try:
            await self._client.start_notify(characteristic, self._notified)
        except TimeoutError as err:
            raise BleTimeoutError("Subscribing to the lock timed out") from err
        except _BLEAK_ERRORS as err:
            raise self._failed("Subscribing to the lock", err) from err
        self._subscribed = True

    async def write(self, data: bytes) -> None:
        self._check_open()
        characteristic = self._communication_characteristic()
        try:
            await self._client.write_gatt_char(characteristic, data, response=self._write_with_response)
        except TimeoutError as err:
            raise BleTimeoutError("Writing to the lock timed out") from err
        except _BLEAK_ERRORS as err:
            raise self._failed("Writing to the lock", err) from err

    async def close(self) -> None:
        """Stop notifications and disconnect. Never raises; a second call does nothing."""
        if self._closed:
            return
        self._closed = True
        if not self._client.is_connected:
            return
        if self._subscribed and self._characteristic is not None:
            try:
                await self._client.stop_notify(self._characteristic)
            except (TimeoutError, *_BLEAK_ERRORS) as err:
                # Disconnecting ends the subscription anyway.
                _LOGGER.debug("Stopping notifications failed: %s", _describe(err))
        try:
            await self._client.disconnect()
        except (TimeoutError, *_BLEAK_ERRORS) as err:
            _LOGGER.debug("Disconnecting from the lock failed: %s", _describe(err))

    # --- Internals -----------------------------------------------------------------

    def _notified(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        # The first argument is the characteristic on bleak 0.18 and later;
        # there is only one to listen to, so it is not looked at.
        if self._closed or self._on_notification is None:
            return
        self._on_notification(bytes(data))

    def _communication_characteristic(self) -> BleakGATTCharacteristic:
        if self._characteristic is not None:
            return self._characteristic
        try:
            characteristic = self._client.services.get_characteristic(COMMUNICATION_CHARACTERISTIC_UUID)
        except BleakError as err:
            # services raises when discovery has not run on this connection.
            raise BleError(f"The lock's GATT services are not known: {_describe(err)}") from err
        if characteristic is None:
            raise BleError("The lock has no communication characteristic; is it a Nimly/Onesti lock?")
        properties = set(characteristic.properties)
        self._write_with_response = write_with_response(properties)
        _LOGGER.debug(
            "Communication characteristic has properties %s; writing %s response",
            sorted(properties),
            "with" if self._write_with_response else "without",
        )
        self._characteristic = characteristic
        return characteristic

    def _check_open(self) -> None:
        if self._closed:
            raise BleDisconnectedError("The transport is closed")
        if self._link_lost:
            raise BleDisconnectedError("The lock disconnected")

    def _failed(self, action: str, err: BaseException) -> BleError:
        if self._link_lost or not self._client.is_connected:
            return BleDisconnectedError(f"{action} failed, the lock disconnected: {_describe(err)}")
        return BleError(f"{action} failed: {_describe(err)}")


def _describe(err: BaseException) -> str:
    """The exception's type and text. bleak's messages name UUIDs and D-Bus errors, never written data."""
    text = str(err)
    return f"{type(err).__name__}: {text}" if text else type(err).__name__

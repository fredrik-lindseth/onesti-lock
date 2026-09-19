"""A lock played in software, behind the Transport protocol.

FakeLock is the lock's lasting state: owner key, device id, name, clock,
server key and the credentials in its slots. FakeTransport is one connection
to it, with its own link keys and login, the way a real connection starts
from nothing each time. The lock side runs on the library's own framing
(PacketStream, Command, Response), but does its key exchange and challenge
check with the cryptography package and the KAT-tested Aes128Cbc directly,
so a test that passes has the session agreeing with an independent peer.

What the fake assumes about the real lock and nobody has checked:

- UserAuthBegin must name the device id the lock holds (the factory id 00 x 6
  until DeviceIdSet), and UserAuthFinalize must carry the right answer, or
  the lock answers SECURITY_ERROR. The app sends the lock's device id on
  every login, so the lock probably checks it; the status it uses is a guess.
- Everything but the key exchange, DeviceModelGet and the two login commands
  needs a completed login first, and is refused with SECURITY_ERROR without.
- UserAuthFinalize answers with a credentials byte of 1.
- FingerprintScan and ScanRfidCode send a UserAdded event (CommandRef 128)
  before their answer.

Tests change its behaviour through status_overrides, payload_overrides,
silent, lost_answers and events_before_answer, and read what it saw in
commands and writes. silent ignores a command; lost_answers carries it out
and drops only the answer, as a radio that loses the lock's reply would.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric import ec

from ..conftest import load_component_module

const = load_component_module("ble.protocol.const")
client_const = load_component_module("ble.client.const")
crypto = load_component_module("ble.crypto")
errors = load_component_module("ble.errors")
packet = load_component_module("ble.protocol.packet")
command = load_component_module("ble.protocol.command")
response = load_component_module("ble.protocol.response")
streams = load_component_module("ble.protocol.streams")

CommandId = const.CommandId
ResponseId = const.ResponseId
Status = const.ResponseStatusId

# Arbitrary private scalars for the lock's three key pairs, and one for each
# key the phone side makes. Little endian, as on the wire; all well below the
# curve order.
LOCK_LINK_PRIVATE_KEY = bytes(range(1, 33))
LOCK_UPDATE_PRIVATE_KEY = bytes(range(33, 65))
LOCK_SERVER_PRIVATE_KEY = bytes(range(65, 97))
PHONE_LINK_PRIVATE_KEY = bytes(range(97, 129))
PHONE_UPDATE_PRIVATE_KEY = bytes(range(129, 161))
PHONE_SERVER_PRIVATE_KEY = bytes(range(161, 193))

# The challenge the fake lock sends; arbitrary.
CHALLENGE = bytes(range(0xC0, 0xD0))

# BattInfoGet answer: level 5800, not low, 80 %.
BATT_INFO_PAYLOAD = bytes.fromhex("A8 16 00 50")

_OPEN_COMMANDS = frozenset(
    {CommandId.EXCHANGE_KEY_PUB_M, CommandId.DEVICE_MODEL_GET, CommandId.USER_AUTH_BEGIN, CommandId.USER_AUTH_FINALIZE}
)


def key_pairs(*private_keys: bytes) -> Callable[[], object]:
    """A key_pair_factory that hands out these keys in order, then fails."""
    remaining = list(private_keys)

    def factory() -> object:
        if not remaining:
            raise AssertionError("The key pair factory ran out of fixed keys")
        return crypto.key_pair_from_private_key(remaining.pop(0))

    return factory


def ecdh_reversed(private_key: bytes, public_key: bytes) -> bytes:
    """The app's secret, computed straight from cryptography: raw ECDH, reversed."""
    curve = ec.SECP256R1()
    private = ec.derive_private_key(int.from_bytes(private_key, "little"), curve)
    x = int.from_bytes(public_key[:32], "little")
    y = int.from_bytes(public_key[32:], "little")
    peer = ec.EllipticCurvePublicNumbers(x, y, curve).public_key()
    return private.exchange(ec.ECDH(), peer)[::-1]


def public_key(private_key: bytes) -> bytes:
    return crypto.key_pair_from_private_key(private_key).public_key


@dataclass
class FakeLock:
    """The lock's lasting state, as a factory-reset lock starts out."""

    firmware: bytes = b"4.8.0"
    model: int = const.LockModelId.NIMLY_PRO_24
    owner_key: bytes = client_const.DEFAULT_ENCRYPTION_KEY
    device_id: bytes = client_const.DEFAULT_DEVICE_ID
    name: str = ""
    clock: int | None = None
    server_public_key: bytes | None = None
    pins: dict[int, str] = field(default_factory=dict)
    fingerprints: set[int] = field(default_factory=set)
    rfids: set[int] = field(default_factory=set)
    link_private_key: bytes = LOCK_LINK_PRIVATE_KEY
    update_private_key: bytes = LOCK_UPDATE_PRIVATE_KEY
    server_private_key: bytes = LOCK_SERVER_PRIVATE_KEY
    challenge: bytes = CHALLENGE
    # Replaces the lock's link key pair with a fixed public key and link keys,
    # for replaying the executed CAVS vector, whose peer private key is not
    # published.
    link_override: tuple[bytes, object] | None = None
    # Everything any connection received, decrypted, in order.
    commands: list[object] = field(default_factory=list)

    def connect(self, **kwargs: object) -> FakeTransport:
        return FakeTransport(self, **kwargs)


class FakeTransport:
    """One connection to a FakeLock, implementing the Transport protocol."""

    def __init__(self, lock: FakeLock, *, deliver_inline: bool = False, require_login: bool = True) -> None:
        self.lock = lock
        self._stream = packet.PacketStream()
        self._on_notification: Callable[[bytes], None] | None = None
        self._on_disconnect: Callable[[], None] | None = None
        self._link_iv: bytes | None = None
        self._begun_device_id: bytes | None = None
        self.authenticated = False
        # Off for tests about the session itself, which never log in.
        self.require_login = require_login
        self.closed = False
        self.close_calls = 0
        # Deliver notifications during write() instead of on the next loop
        # turn, so an answer can arrive before the last packet is written.
        self.deliver_inline = deliver_inline
        self.writes: list[bytes] = []
        self.write_times: list[float] = []
        self.commands: list[object] = []
        self.status_overrides: dict[int, int] = {}
        # Replaces the payload of a successful answer, after the lock acted.
        self.payload_overrides: dict[int, bytes] = {}
        self.silent: set[int] = set()
        self.lost_answers: set[int] = set()
        self.events_before_answer: dict[int, list[object]] = {}
        self.write_error: BaseException | None = None

    # --- Transport ---------------------------------------------------------------

    async def read_software_revision(self) -> bytes:
        return self.lock.firmware

    async def start_notify(self, on_notification: Callable[[bytes], None], on_disconnect: Callable[[], None]) -> None:
        self._on_notification = on_notification
        self._on_disconnect = on_disconnect

    async def write(self, data: bytes) -> None:
        if self.closed:
            raise errors.BleDisconnectedError("Fake link is closed")
        if self.write_error is not None:
            raise self.write_error
        self.writes.append(data)
        self.write_times.append(asyncio.get_running_loop().time())
        received = self._stream.receive(data)
        if isinstance(received, packet.ReceivedPayload):
            self._handle(command.Command.from_bytes(received.data))

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True

    # --- Test controls -------------------------------------------------------------

    def notify(self, data: bytes) -> None:
        """Hand raw bytes to the session as a notification, on the next loop turn."""
        assert self._on_notification is not None, "start_notify was never called"
        if self.deliver_inline:
            self._on_notification(data)
        else:
            asyncio.get_running_loop().call_soon(self._on_notification, data)

    def send_response(self, answer: object) -> None:
        """Frame a Layer 3 response the way the lock would and send it."""
        for frame in self._stream.frame(answer.to_bytes()):
            self.notify(frame)

    def drop_link(self) -> None:
        """The radio link breaks."""
        self.closed = True
        assert self._on_disconnect is not None
        self._on_disconnect()

    # --- The lock ------------------------------------------------------------------

    def _handle(self, received: object) -> None:
        self.commands.append(received)
        self.lock.commands.append(received)
        command_id = received.command_id
        if command_id in self.silent:
            return
        for event in self.events_before_answer.pop(command_id, []):
            self.send_response(event)
        status = self.status_overrides.get(command_id)
        if status is not None:
            self._answer(received, status)
            return
        if self.require_login and command_id not in _OPEN_COMMANDS and not self.authenticated:
            self._answer(received, Status.SECURITY_ERROR)
            return
        handler = getattr(self, f"_on_{command_id.name.lower()}", None)
        if handler is None:
            self._answer(received, Status.NOT_SUPPORTED_ERROR)
            return
        handler(received, streams.ByteReader(received.payload))

    def _answer(self, received: object, status: int = Status.SUCCESS, payload: bytes = b"") -> None:
        if received.command_id in self.lost_answers:
            return
        if status == Status.SUCCESS:
            payload = self.payload_overrides.get(received.command_id, payload)
        self.send_response(
            response.Response(ResponseId(received.command_id), received.command_ref, status, payload)
        )

    def _on_exchange_key_pub_m(self, received, reader) -> None:
        phone_public_key = reader.read_bytes(const.PUBLIC_KEY_LENGTH)
        if self.lock.link_override is not None:
            lock_public_key, link = self.lock.link_override
        else:
            lock_public_key = public_key(self.lock.link_private_key)
            link = crypto.LinkKeys.from_shared_secret(ecdh_reversed(self.lock.link_private_key, phone_public_key))
        self._answer(received, payload=lock_public_key)
        # After the answer is framed: ExchangeKeyPubL goes out in the clear.
        self._stream.cipher = crypto.Aes128Cbc(link.key, link.iv, iv_reset=False)
        self._link_iv = link.iv

    def _on_device_model_get(self, received, reader) -> None:
        self._answer(received, payload=bytes([self.lock.model]))

    def _on_user_auth_begin(self, received, reader) -> None:
        user_id = reader.read_uint8()
        device_id = reader.read_bytes(const.DEVICE_ID_LENGTH)
        self.authenticated = False
        self._begun_device_id = device_id if user_id == 0 else None
        self._answer(received, payload=self.lock.challenge)

    def _on_user_auth_finalize(self, received, reader) -> None:
        answer = reader.read_bytes(const.CHALLENGE_LENGTH)
        aes = crypto.Aes128Cbc(self.lock.owner_key, self._link_iv, iv_reset=False)
        expected = aes.encrypt(bytes(b ^ 0xFF for b in aes.decrypt(self.lock.challenge)))
        if self._begun_device_id != self.lock.device_id or answer != expected:
            self._answer(received, Status.SECURITY_ERROR)
            return
        self.authenticated = True
        self._answer(received, payload=b"\x01")

    def _on_user_auth_update(self, received, reader) -> None:
        reader.read_uint8()  # user id
        reader.read_uint8()  # credentials
        phone_public_key = reader.read_bytes(const.PUBLIC_KEY_LENGTH)
        self.lock.owner_key = ecdh_reversed(self.lock.update_private_key, phone_public_key)[:16]
        self._answer(received, payload=public_key(self.lock.update_private_key))

    def _on_device_id_set(self, received, reader) -> None:
        self.lock.device_id = reader.read_bytes(const.DEVICE_ID_LENGTH)
        self._answer(received)

    def _on_current_time_set(self, received, reader) -> None:
        self.lock.clock = reader.read_uint32()
        self._answer(received)

    def _on_server_key_update(self, received, reader) -> None:
        self.lock.server_public_key = reader.read_bytes(const.PUBLIC_KEY_LENGTH)
        self._answer(received, payload=public_key(self.lock.server_private_key))

    def _on_device_name_set(self, received, reader) -> None:
        self.lock.name = reader.read_string(const.DEVICE_NAME_MAX_LENGTH)
        self._answer(received)

    def _on_batt_info_get(self, received, reader) -> None:
        self._answer(received, payload=BATT_INFO_PAYLOAD)

    def _on_pin_code_set(self, received, reader) -> None:
        slot = reader.read_uint16()
        length = reader.read_uint8()
        self.lock.pins[slot] = reader.read_bytes(length).decode("ascii")
        self._answer(received)

    def _on_pin_code_clear(self, received, reader) -> None:
        slot = reader.read_uint16()
        self._answer(received, Status.SUCCESS if self.lock.pins.pop(slot, None) else Status.NOT_FOUND_ERROR)

    def _on_fingerprint_scan(self, received, reader) -> None:
        self._scan(received, reader.read_uint16(), self.lock.fingerprints, const.UserAddedStatusId.FINGERPRINT)

    def _on_scan_rfid_code(self, received, reader) -> None:
        self._scan(received, reader.read_uint16(), self.lock.rfids, const.UserAddedStatusId.RFID_CODE)

    def _scan(self, received, slot: int, slots: set[int], added: int) -> None:
        slots.add(slot)
        event_payload = streams.ByteWriter().write_uint16(slot).write_uint8(added).to_bytes()
        self.send_response(response.Response(ResponseId.USER_ADDED, response.EVENT_COMMAND_REF, 0, event_payload))
        answer = streams.ByteWriter().write_uint16(slot).write_uint8(const.LockStatusId.OK).to_bytes()
        self._answer(received, payload=answer)

    def _on_fingerprint_clear(self, received, reader) -> None:
        self._clear(received, reader.read_uint16(), self.lock.fingerprints)

    def _on_rfid_code_clear(self, received, reader) -> None:
        self._clear(received, reader.read_uint16(), self.lock.rfids)

    def _clear(self, received, slot: int, slots: set[int]) -> None:
        if slot not in slots:
            self._answer(received, Status.NOT_FOUND_ERROR)
            return
        slots.discard(slot)
        self._answer(received)


# --- The same lock behind bleak's BleakClient ----------------------------------------


DEVICE_INFORMATION_SERVICE_UUID = "0000180a-0000-1000-8000-00805f9b34fb"
MANUFACTURER_NAME_UUID = "00002a29-0000-1000-8000-00805f9b34fb"


class FakeCharacteristic:
    """bleak's BleakGATTCharacteristic: UUID, handle, properties, description, its service.

    The service fields are filled in when a FakeService takes it.
    """

    def __init__(self, uuid: str, properties: list[str], description: str = "", *, handle: int = 0) -> None:
        self.uuid = uuid
        self.properties = properties
        self.description = description
        self.handle = handle
        self.descriptors: list[object] = []
        self.service_uuid = ""
        self.service_handle = 0

    def __repr__(self) -> str:
        return f"FakeCharacteristic({self.uuid})"


class FakeService:
    """bleak's BleakGATTService: UUID, handle, description and its characteristics."""

    def __init__(
        self, uuid: str, characteristics: list[FakeCharacteristic], description: str = "", *, handle: int = 0
    ) -> None:
        self.uuid = uuid
        self.handle = handle
        self.description = description
        self.characteristics = characteristics
        for characteristic in characteristics:
            characteristic.service_uuid = uuid
            characteristic.service_handle = handle

    def get_characteristic(self, uuid: object) -> FakeCharacteristic | None:
        wanted = str(uuid).lower()
        return next((c for c in self.characteristics if c.uuid == wanted), None)

    def __repr__(self) -> str:
        return f"FakeService({self.uuid})"


class FakeServices:
    """bleak's BleakGATTServiceCollection.

    Iterating gives the services in discovery order, as bleak's does;
    services and characteristics are dicts by handle, and get_service and
    get_characteristic look up by UUID. Handles are numbered here when the
    services were built without them.
    """

    def __init__(self, services: list[FakeService]) -> None:
        handle = 0
        for service in services:
            handle += 1
            service.handle = service.handle or handle
            for characteristic in service.characteristics:
                handle += 1
                characteristic.handle = characteristic.handle or handle
                characteristic.service_handle = service.handle
        self.services = {service.handle: service for service in services}
        self.characteristics = {c.handle: c for service in services for c in service.characteristics}

    def __iter__(self) -> Iterator[FakeService]:
        return iter(self.services.values())

    def get_service(self, uuid: object) -> FakeService | None:
        wanted = str(uuid).lower()
        return next((s for s in self.services.values() if s.uuid == wanted), None)

    def get_characteristic(self, uuid: object) -> FakeCharacteristic | None:
        wanted = str(uuid).lower()
        return next((c for c in self.characteristics.values() if c.uuid == wanted), None)


class FakeBleakClient:
    """A bleak.BleakClient whose far end is a FakeLock.

    Built like BleakClient, with a FakeLock in place of the BLEDevice, so it
    can stand in for the client class a caller connects with. The lock side
    is one FakeTransport (link), which frames, decrypts and answers exactly
    as it does for tests that use it directly; this class only gives it
    bleak's shape: the characteristic handed to the notification callback,
    bytearrays, the response flag on writes, and the disconnected callback
    called with the client, also on our own disconnect(), as bleak does.

    The GATT table is what the lock presents: the Device Information service
    with the software revision and the manufacturer name, and the lock's own
    service with the communication characteristic. read_gatt_char answers
    from gatt_values, and refuses a characteristic without a value there the
    way a stack does a read the peripheral rejects.

    bleak is imported only when a method has to raise one of its errors, so
    this module still loads where bleak is not installed.
    """

    def __init__(
        self,
        lock: FakeLock,
        disconnected_callback: Callable[[FakeBleakClient], None] | None = None,
        *,
        timeout: float = 10.0,
        properties: tuple[str, ...] = ("read", "write", "notify"),
        mtu_size: int = 23,
        connected: bool = False,
        **link_kwargs: object,
    ) -> None:
        self.lock = lock
        self.timeout = timeout
        self.link = lock.connect(**link_kwargs)
        self._disconnected_callback = disconnected_callback
        self.communication = FakeCharacteristic(client_const.COMMUNICATION_CHARACTERISTIC_UUID, list(properties))
        self.software_revision = FakeCharacteristic(
            client_const.SOFTWARE_REVISION_CHARACTERISTIC_UUID, ["read"], "Software Revision String"
        )
        self.manufacturer_name = FakeCharacteristic(MANUFACTURER_NAME_UUID, ["read"], "Manufacturer Name String")
        self.services = FakeServices(
            [
                FakeService(
                    DEVICE_INFORMATION_SERVICE_UUID,
                    [self.software_revision, self.manufacturer_name],
                    "Device Information",
                ),
                FakeService(client_const.SERVICE_UUID, [self.communication], "Unknown"),
            ]
        )
        # Values read_gatt_char returns by UUID. The software revision is the
        # lock's firmware, read when asked; the rest answer nothing by default.
        self.gatt_values: dict[str, bytes] = {}
        self.read_calls: list[str] = []
        self.mtu_size = mtu_size
        self.is_connected = connected
        # What the client was asked to do, in order.
        self.write_calls: list[tuple[bytes, bool | None]] = []
        self.notifying: FakeCharacteristic | None = None
        self.stop_notify_calls = 0
        self.disconnect_calls = 0
        # Raised by the next call of that name, once.
        self.errors: dict[str, BaseException] = {}

    def _raise_if_set(self, name: str) -> None:
        error = self.errors.pop(name, None)
        if error is not None:
            raise error

    def _require_connection(self) -> None:
        if not self.is_connected:
            from bleak.exc import BleakError

            raise BleakError("Not connected")

    def _resolve(self, specifier: object) -> FakeCharacteristic:
        if isinstance(specifier, FakeCharacteristic):
            return specifier
        characteristic = self.services.get_characteristic(specifier)
        if characteristic is None:
            from bleak.exc import BleakCharacteristicNotFoundError

            raise BleakCharacteristicNotFoundError(str(specifier))
        return characteristic

    async def connect(self, **kwargs: object) -> None:
        self._raise_if_set("connect")
        self.is_connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._raise_if_set("disconnect")
        if self.is_connected:
            self._lose_link()

    async def read_gatt_char(self, specifier: object, **kwargs: object) -> bytearray:
        self._require_connection()
        self._raise_if_set("read_gatt_char")
        characteristic = self._resolve(specifier)
        self.read_calls.append(characteristic.uuid)
        if characteristic is self.software_revision:
            return bytearray(self.lock.firmware)
        value = self.gatt_values.get(characteristic.uuid)
        if value is None or "read" not in characteristic.properties:
            from bleak.exc import BleakError

            raise BleakError(f"Failed to read characteristic {characteristic.handle}: read not permitted")
        return bytearray(value)

    async def start_notify(self, specifier: object, callback: Callable[..., None], **kwargs: object) -> None:
        self._require_connection()
        self._raise_if_set("start_notify")
        characteristic = self._resolve(specifier)
        self.notifying = characteristic

        def deliver(data: bytes) -> None:
            # A notification that was already queued when the link dropped
            # is not delivered, as on a real stack.
            if self.is_connected and self.notifying is characteristic:
                callback(characteristic, bytearray(data))

        await self.link.start_notify(deliver, self._lose_link)

    async def stop_notify(self, specifier: object) -> None:
        self.stop_notify_calls += 1
        self._require_connection()
        self._raise_if_set("stop_notify")
        self._resolve(specifier)
        self.notifying = None

    async def write_gatt_char(self, specifier: object, data: bytes, response: bool | None = None) -> None:
        self._require_connection()
        self._raise_if_set("write_gatt_char")
        characteristic = self._resolve(specifier)
        wanted = "write" if response else "write-without-response"
        if wanted not in characteristic.properties:
            from bleak.exc import BleakError

            raise BleakError(f"{characteristic.uuid} does not allow {wanted}")
        self.write_calls.append((bytes(data), response))
        await self.link.write(bytes(data))

    # --- Test controls -------------------------------------------------------------

    def drop_link(self) -> None:
        """The radio link breaks: the lock is gone and bleak reports it."""
        self._lose_link()

    def _lose_link(self) -> None:
        self.is_connected = False
        self.link.closed = True
        self.notifying = None
        if self._disconnected_callback is not None:
            self._disconnected_callback(self)

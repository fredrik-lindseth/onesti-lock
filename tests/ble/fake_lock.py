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
silent and events_before_answer, and read what it saw in commands and writes.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
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

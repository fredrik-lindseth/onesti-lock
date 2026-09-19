"""One connection to a lock: key exchange, then commands and their answers.

Session does what the app's NimlyEkeyDeviceBase, CommandStream and
PayloadStream do together, over a Transport instead of Android's GATT:

1. Read the firmware revision and refuse anything below 4.6.0. Below 4.7.90
   every command carries the static CommandRef 16, above it a counter that
   runs 1-127 (CommandRefCounter).
2. Subscribe to the communication characteristic.
3. Send ExchangeKeyPubM with a fresh secp256r1 key, in the clear, and derive
   the link key and IV from the lock's ExchangeKeyPubL answer. From then on
   the packet stream encrypts every outgoing command as a whole before it is
   cut into packets, and decrypts every incoming payload after reassembly.
4. On firmware 4.7.90 and up, ask for the lock model (DeviceModelGet), as the
   app does before it reports the lock connected.

After that, send() and request() run one command at a time: the next command
waits for the answer to the last one, or its timeout, plus the app's 320 ms
pause. An answer is matched on its CommandRef, as CommandStream matches it,
and a status other than SUCCESS raises the mapped BleOperationError. The
lock's unsolicited events, LockStatus and UserAdded under CommandRef 128, go
to the event listeners and never touch the command in flight.

Late answers under the static CommandRef. Below 4.7.90 every command carries
ref 16, so an answer that arrives after its command timed out looks like the
answer to whatever was sent next. The app has the same weakness: CommandStream
matches on the ref alone, and sends the next command right after a timeout.
Two things here narrow it without changing a byte on the wire. After a timeout
under the static ref, the next command holds back for late_answer_grace, and
whatever arrives meanwhile finds no command waiting and is dropped. And while
a command waits, an answer under ref 16 whose response id belongs to another
command is taken as a late answer and ignored; if nothing else comes, the
timeout error names it as its cause. What is left: a late answer to a command
with the same id, arriving after the grace period, still completes the next
one. Nothing on the wire tells the two apart. With the counter (4.7.90 and
up) a late answer carries an old ref and is ignored; an answer with the right
ref and the wrong id there is a BleProtocolError, as before.

The length of a decrypted payload always comes from the Layer 3 header: the
cipher returns the zero padding with it, and Response.from_bytes reads only
what the header declares.

A malformed notification is logged and dropped, as the app drops it. The
command waiting for an answer then runs into its timeout, and the timeout
error names the dropped frame as its cause. Nothing logged here carries
payload bytes, keys or PINs: the library's errors describe sizes and ids
only, a listener's exception is logged by type alone, and no log call
carries a traceback.
"""
from __future__ import annotations

import asyncio
import enum
import logging
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Self

from ..crypto import KeyPair, LinkKeys, derive_link_keys, generate_key_pair
from ..errors import (
    BleDisconnectedError,
    BleError,
    BleFirmwareTooOldError,
    BleProtocolError,
    BleSessionStateError,
    BleTimeoutError,
)
from ..protocol.command import CommandPayload, CommandRefCounter
from ..protocol.commands import device_model_get, exchange_key_pub_m
from ..protocol.const import DEFAULT_MTU, MIN_FIRMWARE_ADMIN, CommandId, FirmwareVersion, LockModelId, ResponseId
from ..protocol.packet import PacketStream, ReceivedPayload
from ..protocol.response import Response, expected_response_id
from ..protocol.responses import LockStatus, UserAdded, parse_device_model, parse_event, parse_exchange_key_pub_l
from .const import (
    COMMAND_RESPONSE_DELAY_S,
    DEFAULT_RESPONSE_TIMEOUT_S,
    LATE_ANSWER_GRACE_S,
    MIN_FIRMWARE_CONNECT,
)
from .transport import Transport

_LOGGER = logging.getLogger(__name__)

type LockEvent = LockStatus | UserAdded
type EventListener = Callable[[LockEvent], None]


def parse_software_revision(raw: bytes) -> FirmwareVersion:
    """The firmware version in a Software Revision String value, "major.minor.bugfix".

    SoftwareRevisionString demands exactly three dot-separated integers.
    Trailing NUL bytes and whitespace are dropped first, which the app does
    not do; a GATT string with a terminator should not lock us out.
    """
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise BleProtocolError("Software revision is not ASCII") from None
    parts = text.rstrip("\0 \t\r\n").split(".")
    if len(parts) != 3 or not all(part.isdecimal() for part in parts):
        raise BleProtocolError(f"Software revision {text!r} is not major.minor.bugfix")
    return int(parts[0]), int(parts[1]), int(parts[2])


class _State(enum.Enum):
    NEW = enum.auto()
    CONNECTING = enum.auto()
    CONNECTED = enum.auto()
    CLOSED = enum.auto()


@dataclass(slots=True)
class _Pending:
    command_id: CommandId
    command_ref: int
    # Firmware below 4.7.90: every command shares the ref (see the module docstring).
    static_ref: bool
    future: asyncio.Future[Response]


class Session:
    """An encrypted command channel to one lock over a Transport.

    Use it as an async context manager, or call connect() and close(). A
    Session connects once; after a disconnect, build a new one on a new
    Transport, as the app does.

    response_timeout is how long a command waits for its answer (the app's
    20 s). command_delay is the pause after an answer before the next command
    goes out (320 ms in the app); tests set it to 0. mtu is what the
    packets are cut for, the app's 23 unless a test against a lock tries
    more; the session does not ask the transport what the link negotiated.
    late_answer_grace is how
    long the next command holds back after a timeout under the static
    CommandRef (firmware below 4.7.90), which the app does not do; see the
    module docstring. key_pair_factory makes the key pair for the link key
    exchange, and exists so tests can fix it.
    """

    def __init__(
        self,
        transport: Transport,
        *,
        response_timeout: float = DEFAULT_RESPONSE_TIMEOUT_S,
        command_delay: float = COMMAND_RESPONSE_DELAY_S,
        late_answer_grace: float = LATE_ANSWER_GRACE_S,
        mtu: int = DEFAULT_MTU,
        key_pair_factory: Callable[[], KeyPair] = generate_key_pair,
    ) -> None:
        self._transport = transport
        self.response_timeout = response_timeout
        self.command_delay = command_delay
        self.late_answer_grace = late_answer_grace
        self._key_pair_factory = key_pair_factory
        self._stream = PacketStream(mtu=mtu)
        self._state = _State.NEW
        self._refs: CommandRefCounter | None = None
        self._firmware: FirmwareVersion | None = None
        self._model: LockModelId | None = None
        self._link_keys: LinkKeys | None = None
        self._pending: _Pending | None = None
        self._dropped: BleProtocolError | None = None
        self._listeners: list[EventListener] = []
        self._command_lock = asyncio.Lock()
        self._ready_at = 0.0

    def __repr__(self) -> str:
        return f"Session(state={self._state.name}, firmware={self._firmware})"

    # --- Lifecycle -------------------------------------------------------------

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def connect(self) -> None:
        """Read the firmware, subscribe, exchange keys and read the model.

        On any failure the transport is closed and the error raised: a
        BleFirmwareTooOldError below 4.6.0, a BleProtocolError for a revision
        or key that does not parse, BleTimeoutError or BleDisconnectedError
        from the link.
        """
        if self._state is not _State.NEW:
            raise BleSessionStateError("A Session connects once; build a new one to reconnect")
        self._state = _State.CONNECTING
        try:
            firmware = parse_software_revision(await self._transport.read_software_revision())
            if firmware < MIN_FIRMWARE_CONNECT:
                raise BleFirmwareTooOldError(firmware, MIN_FIRMWARE_CONNECT)
            self._firmware = firmware
            self._refs = CommandRefCounter.for_firmware(firmware)
            await self._transport.start_notify(self._on_notification, self._on_disconnect)

            key_pair = self._key_pair_factory()
            answer = await self._exchange(exchange_key_pub_m(key_pair.public_key))
            lock_public_key = parse_exchange_key_pub_l(answer).public_key
            self._link_keys = derive_link_keys(key_pair.private_key, lock_public_key)
            # Only now: ExchangeKeyPubL itself arrived in the clear.
            self._stream.cipher = self._link_keys.cipher()

            if firmware >= MIN_FIRMWARE_ADMIN:
                self._model = parse_device_model(await self._exchange(device_model_get())).model
        except BaseException:
            await self.close()
            raise
        self._state = _State.CONNECTED

    async def close(self) -> None:
        """Fail the command in flight, if any, and close the transport."""
        self._state = _State.CLOSED
        self._fail_pending("The session was closed before the lock answered")
        await self._transport.close()

    @property
    def connected(self) -> bool:
        return self._state is _State.CONNECTED

    @property
    def firmware(self) -> FirmwareVersion:
        """The lock's firmware version, read when connecting."""
        if self._firmware is None:
            raise BleSessionStateError("The firmware is read by connect()")
        return self._firmware

    @property
    def model(self) -> LockModelId | None:
        """What DeviceModelGet said; None below firmware 4.7.90, where the app does not ask."""
        return self._model

    @property
    def link_keys(self) -> LinkKeys:
        """This connection's AES key and IV. Owner authentication needs the IV."""
        if self._link_keys is None:
            raise BleSessionStateError("The link keys exist once connect() has exchanged keys")
        return self._link_keys

    # --- Commands --------------------------------------------------------------

    async def send(self, command: CommandPayload) -> Response:
        """Send a command and return its answer once the status says SUCCESS.

        Raises the BleOperationError subclass for a failed status,
        BleProtocolError for an answer of the wrong kind, BleTimeoutError
        when none comes in time, and BleDisconnectedError when the link
        drops first.
        """
        if self._state is not _State.CONNECTED:
            raise self._not_connected()
        return await self._exchange(command)

    async def request[T](self, command: CommandPayload, parse: Callable[[Response], T]) -> T:
        """Send a command and read its answer with one of the parsers in protocol/responses.py."""
        return parse(await self.send(command))

    def add_event_listener(self, listener: EventListener) -> Callable[[], None]:
        """Call listener with every LockStatus and UserAdded event; returns the remover.

        Calling the remover again does nothing, so a caller can run it from
        more than one cleanup path.
        """
        self._listeners.append(listener)
        removed = False

        def remove() -> None:
            nonlocal removed
            if not removed:
                removed = True
                self._listeners.remove(listener)

        return remove

    async def _exchange(self, command: CommandPayload) -> Response:
        async with self._command_lock:
            if self._state not in (_State.CONNECTING, _State.CONNECTED):
                raise self._not_connected()
            assert self._refs is not None  # set by connect() before the first exchange
            loop = asyncio.get_running_loop()
            pause = self._ready_at - loop.time()
            if pause > 0:
                await asyncio.sleep(pause)
                # The link can drop or close() run during the pause. A transport
                # that writes into a dead link without raising would otherwise
                # leave this command waiting out the whole response timeout.
                if self._state not in (_State.CONNECTING, _State.CONNECTED):
                    raise self._not_connected()

            command_ref = self._refs.next()
            frames = self._stream.frame(command.with_ref(command_ref).to_bytes())
            pending = _Pending(command.command_id, command_ref, self._refs.static, loop.create_future())
            # Waiting starts before the first write, as CommandStream arms its
            # receiver when the write begins: an answer can beat the last write.
            self._pending = pending
            self._dropped = None
            answered = False
            try:
                async with asyncio.timeout(self.response_timeout) as deadline:
                    for frame in frames:
                        await self._transport.write(frame)
                    response = await pending.future
                answered = True
            except TimeoutError as err:
                if not deadline.expired():
                    raise
                if pending.static_ref:
                    self._ready_at = loop.time() + self.late_answer_grace
                raise BleTimeoutError(
                    f"{command.command_id.name} got no answer within {self.response_timeout:g} s"
                ) from (self._dropped or err)
            finally:
                self._pending = None
                _settle(pending.future)
                if answered:
                    self._ready_at = loop.time() + self.command_delay

        response.raise_for_status()
        expected = expected_response_id(command.command_id)
        if response.response_id != expected:
            raise BleProtocolError(
                f"{command.command_id.name} was answered by {_response_name(response.response_id)} "
                f"instead of {expected.name}"
            )
        return response

    # --- Incoming --------------------------------------------------------------

    def _on_notification(self, data: bytes) -> None:
        try:
            received = self._stream.receive(data)
        except BleProtocolError as err:
            self._drop(err)
            return
        if not isinstance(received, ReceivedPayload):
            if received is not None:
                # ACK, NAC or ERROR: the app never sends or waits for them.
                _LOGGER.debug("Ignoring a packet of type %s from the lock", received.packet_type.name)
            return
        try:
            response = Response.from_bytes(received.data)
        except BleProtocolError as err:
            self._drop(err)
            return

        if response.is_event:
            self._dispatch_event(response)
            return
        pending = self._pending
        if pending is None or pending.future.done() or response.command_ref != pending.command_ref:
            _LOGGER.debug(
                "Ignoring %s with CommandRef %d that no command is waiting for",
                _response_name(response.response_id),
                response.command_ref,
            )
            return
        if pending.static_ref and response.response_id != expected_response_id(pending.command_id):
            late = BleProtocolError(
                f"{_response_name(response.response_id)} arrived under the static CommandRef while "
                f"{pending.command_id.name} waited, and was taken as a late answer to an earlier command"
            )
            _LOGGER.debug("Ignoring %s", late)
            self._dropped = late
            return
        pending.future.set_result(response)

    def _dispatch_event(self, response: Response) -> None:
        try:
            event = parse_event(response)
        except BleProtocolError as err:
            self._drop(err)
            return
        if event is None:
            _LOGGER.debug("Ignoring event %s, which the app does not read either", _response_name(response.response_id))
            return
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception as err:
                # A listener's bug must not take down the notification path.
                # Its message is not ours and could quote anything, and
                # redact_digits lives outside ble/, so only the type is logged,
                # without a traceback.
                _LOGGER.error("A lock event listener failed with %s", type(err).__name__)

    def _on_disconnect(self) -> None:
        if self._state is _State.CLOSED:
            return
        self._state = _State.CLOSED
        self._stream.reset()
        self._fail_pending("The lock disconnected before it answered")

    def _drop(self, err: BleProtocolError) -> None:
        # Our own BleProtocolError, whose text holds sizes and ids only.
        _LOGGER.warning("Dropped a malformed notification from the lock: %s", err)
        self._dropped = err

    def _fail_pending(self, message: str) -> None:
        pending = self._pending
        if pending is not None and not pending.future.done():
            pending.future.set_exception(BleDisconnectedError(message))

    def _not_connected(self) -> BleError:
        if self._state is _State.NEW:
            return BleSessionStateError("Call connect() before sending commands")
        if self._state is _State.CONNECTING:
            return BleSessionStateError("The session is still connecting")
        return BleDisconnectedError("The session is closed")


def _settle(future: asyncio.Future[Response]) -> None:
    """Cancel a future nobody will await, or mark its exception as seen.

    Otherwise asyncio logs "exception was never retrieved" when a disconnect
    lands while the writes are still going out.
    """
    if not future.done():
        future.cancel()
    elif not future.cancelled():
        future.exception()


def _response_name(response_id: ResponseId | int) -> str:
    if isinstance(response_id, ResponseId):
        return response_id.name
    return f"unknown response 0x{response_id:02X}"

"""Talk to a Nimly/Onesti lock over Bluetooth from a computer, to validate the BLE library.

The library in custom_components/onesti_lock/ble/ was written from the
decompiled app and has not yet run against a lock. This tool runs it against
one, over bleak, one step at a time and from safe to risky, and writes a frame
log that can explain afterwards what went wrong:

    scan [--watch S]           listen for 0xFD00 advertisements; sends nothing
    info ADDR                  GATT services, characteristic properties, MTU, 0x2A28
    handshake ADDR             firmware, key exchange, DeviceModelGet; no login
    login ADDR                 owner login (--factory, --state FILE, or the stored lock)
    read ADDR                  after login: BattInfoGet, DeviceLogGet, DeviceModelGet and friends
    operate ADDR lock|unlock   EkeyOperate                               (--yes)
    pin set|clear ADDR SLOT    PinCodeSet / PinCodeClear, slots 800-899   (--yes)
    rfid scan|clear ADDR SLOT  ScanRfidCode / RfidCodeClear, 900-999      (--yes)
    fingerprint scan|clear ADDR SLOT   FingerprintScan / FingerprintClear, 150-199 (--yes)
    enroll ADDR --name NAME    take over a factory-reset lock             (--yes)
    enroll ADDR --resume       finish an enrollment that stopped partway  (--yes)

What it will never do. It has no FactoryResetModule command at all, and the
three commands that change who owns the lock (DeviceIdSet, UserAuthUpdate,
ServerKeyUpdate) go out only inside the library's enroll() and
resume_enrollment(); _send() refuses them everywhere else. Every command that
changes the lock or moves the bolt prints what it is about to send and does
nothing without --yes. A PIN is never taken on the command line, where the
shell history and the process list would keep it: it is typed at a prompt,
or read from stdin with --pin-stdin.

State. An enrollment is the only copy of the lock's new owner key, so it is
written before anything else happens with it, also when enrollment stops
partway. Each lock is one JSON file in --state-dir (default
~/.config/onesti-lock-ble/, mode 0700, files 0600), named by a hash of its
device id and holding Enrollment.to_dict() plus the address it was last seen at. On
macOS that address is a CoreBluetooth UUID that differs from Mac to Mac, so
scan finds a stored lock again by its advertisement (Advertisement.matches)
and records the address it saw.

Trace. Every session writes a JSON-lines frame log, by default
<state-dir>/traces/<UTC timestamp>.jsonl: each Layer 1 packet in hex (clear
text during the key exchange, ciphertext after it), each command and response
by name with CommandRef, status and payload length, and the payload itself
only for commands and answers on a list that cannot carry a secret. PINs,
owner keys, challenges and device ids appear as lengths. --trace-secrets adds
every payload and the session's link key and IV, so a failed AES chain can be
recomputed offline; use it with test PINs on test slots only, and delete the
file afterwards.

Run it with the project's uv environment, which has bleak and cryptography:

    just ble scan
    just ble handshake <ADDR>

docs/nimly-ble-app/ble-library.md, "Running it against a lock", has the macOS
details and the order to run the steps in.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import hashlib
import json
import logging
import os
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Protocol, TextIO

# The library is imported as the top-level package `ble`: importing it as
# custom_components.onesti_lock.ble would run the component's __init__.py,
# which needs Home Assistant.
COMPONENT_DIR: Final = Path(__file__).resolve().parent.parent / "custom_components" / "onesti_lock"
if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

from ble import (  # noqa: E402
    ADVERTISING_UUID,
    DEFAULT_OWNER_CREDENTIAL,
    SOFTWARE_REVISION_CHARACTERISTIC_UUID,
    Advertisement,
    BleEnrollmentError,
    BleError,
    BleOperationError,
    BleTimeoutError,
    EkeyOperationId,
    Enrollment,
    LockEvent,
    LockStatus,
    OwnerCredential,
    Session,
    Transport,
    UserAdded,
    authenticate_owner,
    commands,
    enroll,
    parse_advertisement,
    responses,
    resume_enrollment,
)
from ble.protocol.command import Command, CommandPayload  # noqa: E402
from ble.protocol.const import MIN_FIRMWARE_ADMIN, CommandId, ResponseId  # noqa: E402
from ble.protocol.packet import Packet  # noqa: E402
from ble.protocol.response import Response  # noqa: E402
from ble.protocol.responses import STATUS_ONLY_RESPONSES  # noqa: E402

DEFAULT_STATE_DIR: Final = Path("~/.config/onesti-lock-ble")
STATE_FORMAT: Final = 1
TRACE_FORMAT: Final = 1

# How long scan listens by default, and how long enroll listens for the
# lock's advertisement before it refuses to go on without seeing the seed.
DEFAULT_SCAN_S: Final = 10.0
# Each --watch window restarts the scan (see _watch).
DEFAULT_WATCH_WINDOW_S: Final = 2.0
DEFAULT_CONNECT_TIMEOUT_S: Final = 20.0

# Nobody knows whether the lock or the module locks out after failed owner
# logins. After this many recorded failures against one address the CLI
# stops trying unless told to (--force-login).
FAILED_LOGIN_LIMIT: Final = 2
FAILED_LOGIN_WINDOW: Final = timedelta(days=1)

# Exit codes: 0 done, 1 failed, 2 refused (a missing --yes, a safety check).
EXIT_OK: Final = 0
EXIT_FAILED: Final = 1
EXIT_REFUSED: Final = 2

# The Device Information Service characteristics info reads when present.
DEVICE_INFORMATION: Final = {
    "00002a29-0000-1000-8000-00805f9b34fb": "Manufacturer Name",
    "00002a24-0000-1000-8000-00805f9b34fb": "Model Number",
    "00002a25-0000-1000-8000-00805f9b34fb": "Serial Number",
    "00002a27-0000-1000-8000-00805f9b34fb": "Hardware Revision",
    "00002a26-0000-1000-8000-00805f9b34fb": "Firmware Revision",
    SOFTWARE_REVISION_CHARACTERISTIC_UUID: "Software Revision",
}

# Commands only enroll() and resume_enrollment() may send, and the one no
# path in this tool may send. _send() checks every command against both.
ENROLLMENT_ONLY_COMMANDS: Final = frozenset(
    {CommandId.DEVICE_ID_SET, CommandId.USER_AUTH_UPDATE, CommandId.SERVER_KEY_UPDATE}
)
NEVER_SENT_COMMANDS: Final = frozenset({CommandId.FACTORY_RESET_MODULE})

# Payloads the trace writes in hex without --trace-secrets. Anything not
# listed is written as a length only: PinCodeSet (the PIN), UserAuthBegin
# (the device id) and its answer (the challenge), UserAuthFinalize (the
# challenge answer), UserAuthUpdate and ServerKeyUpdate (the key exchange
# that makes the owner key), DeviceIdSet/DeviceIdGet (the device id, which
# identifies the lock's advertisement), and any id this list does not know.
TRACE_PAYLOAD_COMMANDS: Final = frozenset(
    {
        CommandId.EXCHANGE_KEY_PUB_M,
        CommandId.DEVICE_MODEL_GET,
        CommandId.BATT_INFO_GET,
        CommandId.DEVICE_LOG_GET,
        CommandId.DEVICE_NAME_GET,
        CommandId.DEVICE_NAME_SET,
        CommandId.CURRENT_TIME_GET,
        CommandId.CURRENT_TIME_SET,
        CommandId.EKEY_OPERATE,
        CommandId.PIN_CODE_CLEAR,
        CommandId.SCAN_RFID_CODE,
        CommandId.RFID_CODE_CLEAR,
        CommandId.FINGERPRINT_SCAN,
        CommandId.FINGERPRINT_CLEAR,
    }
)
TRACE_PAYLOAD_RESPONSES: Final = frozenset(
    {
        ResponseId.EXCHANGE_KEY_PUB_L,
        ResponseId.DEVICE_MODEL_GET,
        ResponseId.BATT_INFO_GET,
        ResponseId.DEVICE_LOG_GET,
        ResponseId.DEVICE_NAME_GET,
        ResponseId.CURRENT_TIME_GET,
        ResponseId.LOCK_STATUS,
        ResponseId.USER_ADDED,
        ResponseId.SCAN_RFID_CODE,
        ResponseId.FINGERPRINT_SCAN,
    }
    | STATUS_ONLY_RESPONSES
)


class CliError(Exception):
    """A failure the CLI explains itself; printed without a traceback."""

    def __init__(self, message: str, exit_code: int = EXIT_FAILED) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# --- Private files -------------------------------------------------------------


def ensure_private_dir(path: Path) -> Path:
    """Create path as 0700, or tighten it to 0700 if it exists looser."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_mode & 0o077:
        os.chmod(path, 0o700)
    return path


def write_private_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON as 0600, atomically: a crash leaves the old file or the new one."""
    ensure_private_dir(path.parent)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        # mkstemp already creates 0600; fchmod makes that independent of it.
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp)
        raise


def open_private_append(path: Path) -> TextIO:
    """Open path for appending, created 0600 if new. The directory must exist."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    return os.fdopen(fd, "a")


# --- Stored locks ----------------------------------------------------------------


@dataclass
class StoredLock:
    """One state file: the enrollment and where the lock was last seen."""

    path: Path
    enrollment: Enrollment
    address: str | None

    @property
    def label(self) -> str:
        return f"{self.enrollment.name or '(no name)'} ({self.path.name})"


class StateStore:
    """The --state-dir: one JSON file per lock, named by a hash of its device id."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path_for(self, enrollment: Enrollment) -> Path:
        # A hash, not the device id itself: the name ends up in terminal
        # output and traces, and the device id is what recognises the lock's
        # advertisement, so a shared trace would let anyone track the lock.
        digest = hashlib.sha256(enrollment.device_id).hexdigest()[:16]
        return self.directory / f"lock-{digest}.json"

    def check_writable(self) -> None:
        """Fail before a session starts if an enrollment could not be saved afterwards."""
        try:
            ensure_private_dir(self.directory)
            write_private_json(self.directory / ".write-check", {})
            (self.directory / ".write-check").unlink()
        except OSError as err:
            raise CliError(f"Cannot write to the state directory {self.directory}: {err.strerror}") from None

    def save(self, enrollment: Enrollment, address: str | None) -> Path:
        path = self.path_for(enrollment)
        write_private_json(
            path,
            {
                "format": STATE_FORMAT,
                "address": address,
                "saved": _now_iso(),
                "enrollment": enrollment.to_dict(),
            },
        )
        return path

    def set_address(self, stored: StoredLock, address: str) -> None:
        if stored.address != address:
            self.save(stored.enrollment, address)
            stored.address = address

    def load(self, path: Path) -> StoredLock:
        try:
            if path.stat().st_mode & 0o077:
                _warn(f"{path} is readable by other users; it holds the owner key. chmod 600 it.")
            data = json.loads(path.read_text())
        except OSError as err:
            raise CliError(f"Cannot read {path}: {err.strerror}") from None
        except json.JSONDecodeError:
            raise CliError(f"{path} is not valid JSON") from None
        if not isinstance(data, dict) or data.get("format") != STATE_FORMAT:
            raise CliError(f"{path} is not a state file this tool wrote (format {STATE_FORMAT})")
        address = data.get("address")
        try:
            enrollment = Enrollment.from_dict(data.get("enrollment") or {})
        except BleError as err:
            # from_dict names the field, never its value.
            raise CliError(f"{path}: {err}") from None
        return StoredLock(path, enrollment, address if isinstance(address, str) else None)

    def all(self) -> list[StoredLock]:
        """Every readable state file; one that does not load is skipped with a warning."""
        if not self.directory.is_dir():
            return []
        found = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                found.append(self.load(path))
            except CliError as err:
                _warn(f"skipping {err}")
        return found

    def by_address(self, address: str) -> list[StoredLock]:
        return [stored for stored in self.all() if stored.address is not None and _same_address(stored.address, address)]


def _same_address(a: str, b: str) -> bool:
    return a.casefold() == b.casefold()


class FailedLogins:
    """Failed owner logins per address, so the CLI can stop before an unknown lockout."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def recent(self, address: str, now: datetime) -> int:
        if not self.path.exists():
            return 0
        count = 0
        for line in self.path.read_text().splitlines():
            try:
                entry = json.loads(line)
                when = datetime.fromisoformat(entry["t"])
            except (ValueError, KeyError, TypeError):
                continue
            if _same_address(str(entry.get("address", "")), address) and now - when < FAILED_LOGIN_WINDOW:
                count += 1
        return count

    def record(self, address: str, credential: str, status: str) -> None:
        ensure_private_dir(self.path.parent)
        with open_private_append(self.path) as handle:
            handle.write(json.dumps({"t": _now_iso(), "address": address, "credential": credential, "status": status}))
            handle.write("\n")


# --- Trace -----------------------------------------------------------------------


class RedactingTracer:
    """The Session tracer: one JSON object per line, secrets as lengths unless asked.

    Every line is flushed as it is written, so a crash or Ctrl-C still leaves
    a readable log up to that point. A tracer error cannot stop the session
    (the library swallows it), so the first one is kept and reported at the
    end instead of vanishing.
    """

    def __init__(self, handle: TextIO | None, *, secrets: bool, path: Path | None = None) -> None:
        self._handle = handle
        self.secrets = secrets
        self.path = path
        self._started = time.monotonic()
        self.failure: str | None = None

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    # --- Tracer protocol (ble.client.tracing.Tracer) ----------------------------

    def packet_out(self, data: bytes) -> None:
        self._write("packet", dir="out", **_packet_fields(data))

    def packet_in(self, data: bytes) -> None:
        self._write("packet", dir="in", **_packet_fields(data))

    def command(self, command: Command) -> None:
        fields: dict[str, Any] = {
            "id": _id_name(command.command_id, CommandId),
            "ref": command.command_ref,
            "len": len(command.payload),
        }
        if self.secrets or command.command_id in TRACE_PAYLOAD_COMMANDS:
            fields["payload"] = command.payload.hex()
        self._write("command", dir="out", **fields)

    def response(self, response: Response) -> None:
        fields: dict[str, Any] = {
            "id": _id_name(response.response_id, ResponseId),
            "ref": response.command_ref,
            "status": _status_name(response.status),
            "len": len(response.payload),
        }
        if response.is_event:
            fields["unsolicited"] = True
        if self.secrets or response.response_id in TRACE_PAYLOAD_RESPONSES:
            fields["payload"] = response.payload.hex()
        self._write("response", dir="in", **fields)

    def dropped(self, error: BleError, data: bytes) -> None:
        # data can be a decrypted payload, the owner challenge included, so
        # only its length goes in by default. The raw packets are in the log
        # as ciphertext, and --trace-secrets has the link key to open them.
        fields: dict[str, Any] = {"error": str(error), "len": len(data)}
        if self.secrets:
            fields["data"] = data.hex()
        self._write("dropped", dir="in", **fields)

    # --- The CLI's own events ------------------------------------------------------

    def note(self, event: str, **fields: Any) -> None:
        self._write(event, **fields)

    def secret(self, event: str, **fields: Any) -> None:
        """An event that is written only with --trace-secrets."""
        if self.secrets:
            self._write(event, **fields)

    def _write(self, event: str, **fields: Any) -> None:
        if self._handle is None:
            return
        record = {
            "t": _now_iso(),
            "dt": round(time.monotonic() - self._started, 4),
            "event": event,
            **fields,
        }
        try:
            self._handle.write(json.dumps(record) + "\n")
            self._handle.flush()
        except (OSError, ValueError) as err:
            if self.failure is None:
                self.failure = f"{type(err).__name__}: {err}"


def _packet_fields(data: bytes) -> dict[str, Any]:
    """Layer 1 fields for the log. The header is never encrypted, only the payload."""
    fields: dict[str, Any] = {"hex": data.hex(), "len": len(data)}
    try:
        packet = Packet.from_bytes(data)
    except BleError as err:
        fields["parse_error"] = str(err)
    else:
        fields["type"] = packet.packet_type.name
        fields["seq"] = packet.sequence_number
    return fields


def _id_name(value: int, enum: type[CommandId] | type[ResponseId]) -> str:
    try:
        return enum(value).name
    except ValueError:
        return f"0x{value:02X}"


def _status_name(status: int) -> str:
    return getattr(status, "name", f"0x{status:02X}")


def open_trace(args: argparse.Namespace, state_dir: Path) -> RedactingTracer:
    if args.no_trace:
        return RedactingTracer(None, secrets=False)
    try:
        if args.trace is not None:
            # A path of the user's choosing: its directory is theirs, left as it is.
            path = Path(args.trace).expanduser()
        else:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
            path = ensure_private_dir(ensure_private_dir(state_dir) / "traces") / f"{stamp}-{args.command}.jsonl"
        handle = open_private_append(path)
    except OSError as err:
        raise CliError(f"Cannot open the trace file: {err}") from None
    tracer = RedactingTracer(handle, secrets=args.trace_secrets, path=path)
    tracer.note(
        "start",
        format=TRACE_FORMAT,
        command=args.command,
        address=getattr(args, "address", None),
        secrets=args.trace_secrets,
        python=sys.version.split()[0],
        platform=sys.platform,
    )
    return tracer


# --- Radio -------------------------------------------------------------------------


@dataclass(frozen=True)
class Seen:
    """One advertisement as the scanner reported it."""

    address: str
    name: str | None
    rssi: int | None
    service_data: dict[str, bytes]
    monotonic: float = field(default_factory=time.monotonic)

    @property
    def lock_data(self) -> bytes | None:
        return self.service_data.get(ADVERTISING_UUID)


class Radio(Protocol):
    """What the CLI needs from a Bluetooth stack; bleak by default, a fake in tests."""

    async def scan(self, seconds: float, on_seen: Callable[[Seen], None]) -> None:
        """Report every advertisement seen during seconds."""

    async def connect(self, address: str, timeout: float) -> Any:
        """A connected BleakClient (or a stand-in) for address."""

    async def disconnect(self, client: Any) -> None:
        """Let go of a client connect() returned, when no transport owns it."""


class BleakRadio:
    """The real radio. bleak is imported here, so --help works without it."""

    async def scan(self, seconds: float, on_seen: Callable[[Seen], None]) -> None:
        from bleak import BleakScanner

        def detected(device: Any, advertisement: Any) -> None:
            on_seen(
                Seen(
                    address=device.address,
                    name=advertisement.local_name or device.name,
                    rssi=advertisement.rssi,
                    service_data={uuid.lower(): bytes(data) for uuid, data in advertisement.service_data.items()},
                )
            )

        async with BleakScanner(detection_callback=detected):
            await asyncio.sleep(seconds)

    async def connect(self, address: str, timeout: float) -> Any:
        from bleak import BleakClient, BleakScanner

        device = await BleakScanner.find_device_by_address(address, timeout=timeout)
        if device is None:
            raise CliError(
                f"{address} was not seen within {timeout:g} s. Is the lock in range and awake? "
                "Touching the keypad may wake it."
            )
        client = BleakClient(device, timeout=timeout)
        await client.connect()
        return client

    async def disconnect(self, client: Any) -> None:
        await client.disconnect()


def bleak_transport(client: Any) -> Transport:
    from ble.client.bleak_transport import BleakTransport

    transport: Transport = BleakTransport(client)
    return transport


def default_session(transport: Transport, tracer: RedactingTracer, response_timeout: float | None) -> Session:
    if response_timeout is None:
        return Session(transport, tracer=tracer)
    return Session(transport, tracer=tracer, response_timeout=response_timeout)


# --- Context -----------------------------------------------------------------------


@dataclass
class Deps:
    """What main() runs against. Tests replace the radio and, if they must, the rest."""

    radio: Radio = field(default_factory=BleakRadio)
    transport_factory: Callable[[Any], Transport] = bleak_transport
    session_factory: Callable[[Transport, RedactingTracer, float | None], Session] = default_session
    stdin: TextIO | None = None
    out: TextIO | None = None
    err: TextIO | None = None
    getpass: Callable[[str], str] = getpass.getpass


@dataclass
class Context:
    args: argparse.Namespace
    deps: Deps
    store: StateStore
    trace: RedactingTracer
    out: TextIO
    err: TextIO

    def say(self, message: str = "") -> None:
        print(message, file=self.out, flush=True)

    def warn(self, message: str) -> None:
        print(f"warning: {message}", file=self.err, flush=True)

    @property
    def failed_logins(self) -> FailedLogins:
        return FailedLogins(self.store.directory / "failed-logins.jsonl")


# The context of the running command, for the few messages that are emitted
# from code with no Context at hand (StateStore.load's permission warning).
_CURRENT: Context | None = None


def _warn(message: str) -> None:
    if _CURRENT is not None:
        _CURRENT.warn(message)
    else:
        print(f"warning: {message}", file=sys.stderr)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


# --- Sessions ------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def open_session(ctx: Context, address: str) -> AsyncIterator[Session]:
    """Connect, run the key exchange and yield the session; always let go afterwards."""
    ctx.say(f"Connecting to {address} ...")
    client = await ctx.deps.radio.connect(address, ctx.args.connect_timeout)
    try:
        transport = ctx.deps.transport_factory(client)
    except BaseException:
        await ctx.deps.radio.disconnect(client)
        raise
    mtu = getattr(transport, "mtu_size", None)
    ctx.say(f"  connected, MTU {mtu} (the session frames for 23 regardless)")
    ctx.trace.note("connected", address=address, mtu=mtu)
    try:
        session = ctx.deps.session_factory(transport, ctx.trace, ctx.args.response_timeout)
    except BaseException:
        await transport.close()
        raise
    try:
        try:
            await session.connect()
        finally:
            _trace_link_keys(ctx, session)
        ctx.trace.note(
            "session",
            firmware=".".join(map(str, session.firmware)),
            command_ref="static 16" if session.firmware < MIN_FIRMWARE_ADMIN else "counter 1-127",
            model=None if session.model is None else session.model.name,
        )
        remove = session.add_event_listener(lambda event: _print_event(ctx, event))
        try:
            yield session
        finally:
            remove()
    finally:
        await session.close()
        # Session.close closes the transport; this covers a transport whose
        # close is not what disconnects the client.
        with contextlib.suppress(Exception):
            await transport.close()
        ctx.trace.note("closed")


def _trace_link_keys(ctx: Context, session: Session) -> None:
    # Also after a failed connect: when DeviceModelGet times out, the keys
    # are exactly what is needed to see whether the lock's answer decrypts.
    with contextlib.suppress(BleError):
        keys = session.link_keys
        ctx.trace.secret("link_keys", key=keys.key.hex(), iv=keys.iv.hex())


def _print_event(ctx: Context, event: LockEvent) -> None:
    if isinstance(event, LockStatus):
        ctx.say(f"  event: LockStatus slot {event.slot}, {event.state.name}, by {event.method.name}")
    elif isinstance(event, UserAdded):
        ctx.say(f"  event: UserAdded slot {event.slot}, {event.status.name}")


def _describe_session(ctx: Context, session: Session) -> None:
    firmware = ".".join(map(str, session.firmware))
    refs = "static CommandRef 16" if session.firmware < MIN_FIRMWARE_ADMIN else "CommandRef counter 1-127"
    ctx.say(f"  firmware {firmware}, {refs}")
    ctx.say(f"  model {session.model.name if session.model is not None else '(not asked below 4.7.90)'}")
    ctx.say("  key exchange done, the link is encrypted")


async def _send(session: Session, payload: CommandPayload) -> Response:
    """Every command the CLI sends outside enrollment goes through here."""
    if payload.command_id in NEVER_SENT_COMMANDS:
        raise CliError(f"{payload.command_id.name} is never sent by this tool", EXIT_REFUSED)
    if payload.command_id in ENROLLMENT_ONLY_COMMANDS:
        raise CliError(f"{payload.command_id.name} is sent only by enroll", EXIT_REFUSED)
    return await session.send(payload)


# --- Credentials ---------------------------------------------------------------------


@dataclass
class Login:
    credential: OwnerCredential
    description: str
    kind: str
    stored: StoredLock | None = None


def resolve_login(ctx: Context, address: str) -> Login:
    args = ctx.args
    if args.factory:
        return Login(DEFAULT_OWNER_CREDENTIAL, "the factory credential (user 0, device id 00 x 6, key 11 x 16)", "factory")
    if args.state is not None:
        stored = ctx.store.load(Path(args.state).expanduser())
    else:
        found = ctx.store.by_address(address)
        if not found:
            raise CliError(
                f"No stored enrollment was last seen at {address}. Pass --factory for a factory-reset lock, "
                "--state FILE for a stored one, or run scan to find the stored lock's current address.",
                EXIT_REFUSED,
            )
        if len(found) > 1:
            names = ", ".join(stored.path.name for stored in found)
            raise CliError(f"More than one stored enrollment was last seen at {address} ({names}); pick one with --state")
        stored = found[0]
    if not stored.enrollment.complete:
        steps = ", ".join(step.value for step in stored.enrollment.remaining)
        ctx.warn(f"The enrollment in {stored.path.name} is not finished ({steps} left); enroll --resume finishes it.")
    return Login(stored.enrollment.owner_credential, f"the stored enrollment {stored.label}", "stored", stored)


def check_login_budget(ctx: Context, address: str) -> None:
    failures = ctx.failed_logins.recent(address, datetime.now(UTC))
    if failures == 0:
        return
    message = (
        f"{failures} failed login(s) against {address} in the last {FAILED_LOGIN_WINDOW.days} day(s) "
        f"are recorded in {ctx.failed_logins.path}. Whether the lock locks out after failed logins is unknown."
    )
    if failures >= FAILED_LOGIN_LIMIT and not ctx.args.force_login:
        raise CliError(message + " Not trying again without --force-login.", EXIT_REFUSED)
    ctx.warn(message)


async def log_in(ctx: Context, session: Session, address: str, login: Login) -> None:
    ctx.say(f"Logging in with {login.description} ...")
    ctx.trace.note("login", credential=login.kind)
    try:
        await authenticate_owner(session, login.credential)
    except BleOperationError as err:
        status = _status_name(err.status)
        ctx.failed_logins.record(address, login.kind, status)
        ctx.trace.note("login_refused", status=status)
        raise CliError(f"The lock refused the login: {err}") from None
    ctx.say("  logged in")
    ctx.trace.note("logged_in")
    if login.stored is not None:
        ctx.store.set_address(login.stored, address)


def require_admin_firmware(session: Session, what: str) -> None:
    if session.firmware < MIN_FIRMWARE_ADMIN:
        firmware = ".".join(map(str, session.firmware))
        raise CliError(
            f"{what} needs firmware 4.7.90 or newer, as in the app; this lock runs {firmware}", EXIT_REFUSED
        )


# --- Commands: no session -------------------------------------------------------------


async def cmd_scan(ctx: Context) -> int:
    stored = ctx.store.all()
    if ctx.args.watch is not None:
        return await _watch(ctx, stored, ctx.args.watch)
    ctx.say(f"Listening for {ctx.args.seconds:g} s for 0xFD00 advertisements (nothing is sent to any lock) ...")
    latest: dict[str, Seen] = {}

    def on_seen(seen: Seen) -> None:
        if seen.lock_data is not None:
            latest[seen.address] = seen
            _trace_advertisement(ctx, seen)

    await ctx.deps.radio.scan(ctx.args.seconds, on_seen)
    if not latest:
        ctx.say(
            f"No 0xFD00 advertiser was seen in {ctx.args.seconds:g} s. The lock may advertise only when awake: "
            "touch the keypad and scan again. On macOS, check that the terminal has Bluetooth permission."
        )
        return EXIT_FAILED
    for seen in latest.values():
        _describe_advertisement(ctx, seen, stored)
    return EXIT_OK


async def _watch(ctx: Context, stored: list[StoredLock], seconds: float) -> int:
    """Log advertisements with timestamps, restarting the scan every window.

    bleak starts a CoreBluetooth scan without the allow-duplicates option, so
    macOS reports a device once per scan unless its advertisement changes.
    Restarting the scan every window turns that into a presence timeline:
    whether the lock was heard in each window, which says whether it
    advertises all the time or only when woken.
    """
    window = ctx.args.window
    ctx.say(f"Watching for {seconds:g} s in windows of {window:g} s (nothing is sent to any lock).")
    ctx.say("Touch the keypad at some point to see whether that changes anything.")
    start = time.monotonic()
    known: set[str] = set()
    heard_any = False
    while (elapsed := time.monotonic() - start) < seconds:
        heard: set[str] = set()

        def on_seen(seen: Seen, heard: set[str] = heard) -> None:
            if seen.lock_data is None:
                return
            offset = seen.monotonic - start
            ctx.say(f"{offset:8.2f} s  {seen.address}  rssi {seen.rssi}  {_advertisement_summary(seen, stored)}")
            _trace_advertisement(ctx, seen)
            heard.add(seen.address)

        await ctx.deps.radio.scan(min(window, seconds - elapsed), on_seen)
        heard_any = heard_any or bool(heard)
        for address in sorted(known - heard):
            ctx.say(f"{time.monotonic() - start:8.2f} s  {address}  not heard in this window")
        known |= heard
    if not heard_any:
        ctx.say(f"No 0xFD00 advertiser was heard in {seconds:g} s.")
        return EXIT_FAILED
    return EXIT_OK


def _trace_advertisement(ctx: Context, seen: Seen) -> None:
    # The advertisement is broadcast in the clear; nothing in it is secret.
    ctx.trace.note(
        "advertisement",
        address=seen.address,
        name=seen.name,
        rssi=seen.rssi,
        service_data={uuid: data.hex() for uuid, data in seen.service_data.items()},
    )


def _parse(seen: Seen) -> Advertisement | BleError:
    try:
        return parse_advertisement(seen.lock_data or b"")
    except BleError as err:
        return err


def _matches(advertisement: Advertisement, stored: Iterable[StoredLock]) -> list[StoredLock]:
    return [lock for lock in stored if advertisement.matches(lock.enrollment.device_id)]


def _advertisement_summary(seen: Seen, stored: list[StoredLock]) -> str:
    advertisement = _parse(seen)
    if isinstance(advertisement, BleError):
        return f"unreadable 0xFD00 data {seen.lock_data.hex() if seen.lock_data else ''}: {advertisement}"
    state = "enrolled" if advertisement.enrolled else "factory state"
    text = f"seed {advertisement.seed.hex()} id {advertisement.identifier.hex()} ({state})"
    matches = _matches(advertisement, stored)
    if matches:
        text += ", stored as " + ", ".join(lock.label for lock in matches)
    return text


def _describe_advertisement(ctx: Context, seen: Seen, stored: list[StoredLock]) -> None:
    ctx.say(f"{seen.address}  {seen.name or '(no name)'}  rssi {seen.rssi}")
    advertisement = _parse(seen)
    if isinstance(advertisement, BleError):
        ctx.say(f"  0xFD00 data {seen.lock_data.hex() if seen.lock_data else ''} does not parse: {advertisement}")
        return
    ctx.say(f"  seed       {advertisement.seed.hex()}")
    ctx.say(f"  identifier {advertisement.identifier.hex()}")
    if advertisement.enrolled:
        ctx.say("  enrolled   yes: someone owns this lock over BLE; the factory credential should not work")
    else:
        factory_id = advertisement.factory_id.hex() if advertisement.factory_id else ""
        ctx.say(f"  enrolled   no: factory state, factory id {factory_id}")
    matches = _matches(advertisement, stored)
    for lock in matches:
        ctx.say(f"  stored     yes, {lock.label}")
        ctx.store.set_address(lock, seen.address)
    if not matches and stored and advertisement.enrolled:
        ctx.say("  stored     no stored enrollment matches")


async def cmd_info(ctx: Context) -> int:
    address = ctx.args.address
    ctx.say(f"Connecting to {address} (GATT only, no protocol frames) ...")
    client = await ctx.deps.radio.connect(address, ctx.args.connect_timeout)
    try:
        mtu = getattr(client, "mtu_size", None)
        ctx.say(f"MTU {mtu} (the session frames for 23 regardless)")
        ctx.trace.note("connected", address=address, mtu=mtu)
        readable: list[Any] = []
        for service in client.services:
            ctx.say(f"service {service.uuid}  {service.description}")
            characteristics = []
            for characteristic in service.characteristics:
                properties = sorted(characteristic.properties)
                ctx.say(f"  characteristic {characteristic.uuid}  [{', '.join(properties)}]  {characteristic.description}")
                characteristics.append({"uuid": characteristic.uuid, "properties": properties})
                if characteristic.uuid.lower() in DEVICE_INFORMATION and "read" in properties:
                    readable.append(characteristic)
            ctx.trace.note("service", uuid=service.uuid, characteristics=characteristics)
        for characteristic in readable:
            label = DEVICE_INFORMATION[characteristic.uuid.lower()]
            try:
                value = bytes(await client.read_gatt_char(characteristic))
            except Exception as err:  # a failed read is a finding, not a reason to stop
                ctx.say(f"{label}: read failed, {type(err).__name__}: {err}")
                ctx.trace.note("read_failed", uuid=characteristic.uuid, error=type(err).__name__)
                continue
            ctx.say(f"{label}: {_printable(value)}")
            ctx.trace.note("read", uuid=characteristic.uuid, hex=value.hex())
    finally:
        await ctx.deps.radio.disconnect(client)
        ctx.trace.note("closed")
    return EXIT_OK


def _printable(value: bytes) -> str:
    text = value.decode("ascii", errors="replace")
    return f"{text!r} ({value.hex()})"


# --- Commands: sessions ----------------------------------------------------------------


async def cmd_handshake(ctx: Context) -> int:
    async with open_session(ctx, ctx.args.address) as session:
        _describe_session(ctx, session)
    return EXIT_OK


async def cmd_login(ctx: Context) -> int:
    address = ctx.args.address
    login = resolve_login(ctx, address)
    check_login_budget(ctx, address)
    async with open_session(ctx, address) as session:
        _describe_session(ctx, session)
        await log_in(ctx, session, address, login)
    return EXIT_OK


# What read asks for, in order: (label, builder, parser).
READS: Final[list[tuple[str, Callable[[], CommandPayload], Callable[[Response], Any]]]] = [
    ("DeviceModelGet", commands.device_model_get, responses.parse_device_model),
    ("BattInfoGet", commands.batt_info_get, responses.parse_batt_info),
    ("DeviceLogGet", commands.device_log_get, responses.parse_device_log),
    ("DeviceNameGet", commands.device_name_get, responses.parse_device_name_get),
    ("CurrentTimeGet", commands.current_time_get, responses.parse_current_time),
]


async def cmd_read(ctx: Context) -> int:
    address = ctx.args.address
    login = resolve_login(ctx, address)
    check_login_budget(ctx, address)
    failed = False
    async with open_session(ctx, address) as session:
        _describe_session(ctx, session)
        if session.firmware < MIN_FIRMWARE_ADMIN:
            ctx.warn("Below firmware 4.7.90 the app does not offer these reads; sending them anyway to see the answer.")
        await log_in(ctx, session, address, login)
        for label, build, parse in READS:
            try:
                result = parse(await _send(session, build()))
            except BleOperationError as err:
                ctx.say(f"{label}: refused, {err}")
                failed = True
                continue
            except BleTimeoutError as err:
                ctx.say(f"{label}: {err}; stopping here")
                failed = True
                break
            ctx.say(f"{label}: {_format_read(result)}")
    return EXIT_FAILED if failed else EXIT_OK


def _format_read(result: Any) -> str:
    if isinstance(result, responses.DeviceModel):
        return f"{result.model.name} (raw {result.raw})"
    if isinstance(result, responses.BattInfo):
        return f"level {result.level}, {result.percent} %, low battery {'yes' if result.low_battery else 'no'}"
    if isinstance(result, responses.DeviceLog):
        return f"{len(result.log)} byte(s) {result.log.hex()}"
    if isinstance(result, responses.DeviceName):
        return repr(result.name)
    if isinstance(result, responses.CurrentTime):
        return f"{result.moment.isoformat()} ({result.minutes} lock minutes)"
    return repr(result)


# --- Commands: writes ------------------------------------------------------------------


@dataclass
class Write:
    """A command that changes the lock, described before it is sent."""

    payload: CommandPayload
    description: str
    parse: Callable[[Response], Any] | None = None
    interactive: str | None = None


def confirm(ctx: Context, address: str, login: Login | None, steps: list[str]) -> bool:
    """Print what will be sent; True only with --yes."""
    ctx.say(f"On {address} this will:")
    ctx.say("  1. connect and run the key exchange")
    number = 2
    if login is not None:
        ctx.say(f"  2. log in with {login.description}")
        number = 3
    for step in steps:
        ctx.say(f"  {number}. {step}")
        number += 1
    if not ctx.args.yes:
        ctx.say("Nothing was sent. Run it again with --yes to send it.")
        return False
    return True


async def run_write(ctx: Context, write: Write, *, gate: Callable[[Session], None] | None = None) -> int:
    address = ctx.args.address
    login = resolve_login(ctx, address)
    if not confirm(ctx, address, login, [write.description]):
        return EXIT_REFUSED
    check_login_budget(ctx, address)
    async with open_session(ctx, address) as session:
        _describe_session(ctx, session)
        if gate is not None:
            gate(session)
        await log_in(ctx, session, address, login)
        if write.interactive:
            ctx.say(write.interactive)
        ctx.say(f"Sending: {write.description}")
        try:
            response = await _send(session, write.payload)
        except BleOperationError as err:
            ctx.say(f"  the lock answered with a failure: {err}")
            return EXIT_FAILED
        ctx.say(f"  status {_status_name(response.status)}")
        if write.parse is not None:
            result = write.parse(response)
            ctx.say(f"  {_format_scan(result)}")
    return EXIT_OK


def _format_scan(result: Any) -> str:
    if isinstance(result, responses.ScanResult):
        status = getattr(result.status, "name", result.status)
        return f"slot {result.slot}, result {status}"
    return repr(result)


def _validated[T](build: Callable[[], T]) -> T:
    """Run a builder before anything connects, so a bad slot or PIN costs nothing."""
    try:
        return build()
    except BleError as err:
        raise CliError(str(err), EXIT_REFUSED) from None


async def cmd_operate(ctx: Context) -> int:
    operation = EkeyOperationId.LOCK if ctx.args.operation == "lock" else EkeyOperationId.UNLOCK
    payload = _validated(lambda: commands.ekey_operate(operation))
    what = f"send EkeyOperate {operation.name}: the bolt moves. Stand at the door."
    return await run_write(ctx, Write(payload, what))


def read_pin(ctx: Context) -> str:
    """The PIN, from stdin with --pin-stdin, else typed twice at a prompt that does not echo."""
    if ctx.args.pin_stdin:
        stdin = ctx.deps.stdin or sys.stdin
        return stdin.readline().strip()
    first = ctx.deps.getpass("New PIN (4-8 digits, not echoed): ")
    again = ctx.deps.getpass("Same PIN again: ")
    if first != again:
        raise CliError("The two PINs differ; nothing was sent", EXIT_REFUSED)
    return first


async def cmd_pin(ctx: Context) -> int:
    slot = ctx.args.slot
    if ctx.args.action == "clear":
        payload = _validated(lambda: commands.pin_code_clear(slot))
        return await run_write(ctx, Write(payload, f"send PinCodeClear for slot {slot}"), gate=_admin_gate("PinCodeClear"))
    # Refuse a bad slot before asking for a PIN.
    _validated(lambda: commands.pin_code_clear(slot))
    if not ctx.args.yes:
        login = resolve_login(ctx, ctx.args.address)
        confirm(ctx, ctx.args.address, login, [f"send PinCodeSet for slot {slot} with a PIN you type at a prompt"])
        return EXIT_REFUSED
    pin = read_pin(ctx)
    payload = _validated(lambda: commands.pin_code_set(slot, pin))
    digits = len(pin)
    what = f"send PinCodeSet for slot {slot}, a PIN of {digits} digits. Check it on the keypad afterwards."
    return await run_write(ctx, Write(payload, what), gate=_admin_gate("PinCodeSet"))


def _admin_gate(what: str, *, fingerprint: bool = False) -> Callable[[Session], None]:
    def gate(session: Session) -> None:
        require_admin_firmware(session, what)
        if fingerprint and session.model is not None and not session.model.features.fingerprint:
            raise CliError(f"The app offers {what} only on models with a fingerprint reader, not {session.model.name}", EXIT_REFUSED)

    return gate


async def cmd_rfid(ctx: Context) -> int:
    slot = ctx.args.slot
    if ctx.args.action == "clear":
        payload = _validated(lambda: commands.rfid_code_clear(slot))
        return await run_write(ctx, Write(payload, f"send RfidCodeClear for slot {slot}"), gate=_admin_gate("RfidCodeClear"))
    payload = _validated(lambda: commands.scan_rfid_code(slot))
    write = Write(
        payload,
        f"send ScanRfidCode for slot {slot}: the lock waits for a tag",
        parse=responses.parse_scan_rfid_code,
        interactive=f"Hold the tag to the lock within {_answer_window(ctx):g} s.",
    )
    return await run_write(ctx, write, gate=_admin_gate("ScanRfidCode"))


async def cmd_fingerprint(ctx: Context) -> int:
    slot = ctx.args.slot
    if ctx.args.action == "clear":
        payload = _validated(lambda: commands.fingerprint_clear(slot))
        gate = _admin_gate("FingerprintClear", fingerprint=True)
        return await run_write(ctx, Write(payload, f"send FingerprintClear for slot {slot}"), gate=gate)
    payload = _validated(lambda: commands.fingerprint_scan(slot))
    write = Write(
        payload,
        f"send FingerprintScan for slot {slot}: the lock waits for a finger",
        parse=responses.parse_fingerprint_scan,
        interactive=f"Put the finger on the reader within {_answer_window(ctx):g} s, as often as the lock asks.",
    )
    return await run_write(ctx, write, gate=_admin_gate("FingerprintScan", fingerprint=True))


def _answer_window(ctx: Context) -> float:
    from ble.client.const import DEFAULT_RESPONSE_TIMEOUT_S

    timeout: float = ctx.args.response_timeout or DEFAULT_RESPONSE_TIMEOUT_S
    return timeout


# --- Enrollment ------------------------------------------------------------------------


async def find_advertisement(ctx: Context, address: str, seconds: float) -> Advertisement | None:
    found: list[Advertisement] = []

    def on_seen(seen: Seen) -> None:
        if seen.lock_data is not None and _same_address(seen.address, address):
            _trace_advertisement(ctx, seen)
            parsed = _parse(seen)
            if isinstance(parsed, Advertisement):
                found.append(parsed)

    await ctx.deps.radio.scan(seconds, on_seen)
    return found[-1] if found else None


async def cmd_enroll(ctx: Context) -> int:
    if ctx.args.resume:
        return await _resume(ctx)
    address = ctx.args.address
    name = ctx.args.name
    if name is None:
        raise CliError("enroll needs --name (at most 8 ASCII characters), or --resume", EXIT_REFUSED)
    _validated(lambda: commands.device_name_set(name))
    existing = ctx.store.by_address(address)
    if existing:
        raise CliError(
            f"{existing[0].path} already holds an enrollment last seen at {address}. "
            "Use enroll --resume to finish it; this tool does not enroll a lock twice.",
            EXIT_REFUSED,
        )
    steps = [
        "log in with the factory credential (user 0, device id 00 x 6, key 11 x 16)",
        "send UserAuthUpdate: the lock gets a new owner key and the factory key stops working",
        "send DeviceIdSet with a random device id",
        "send CurrentTimeSet with the current time",
        "send ServerKeyUpdate with a server key generated here",
        f"send DeviceNameSet {name!r}",
        f"save the enrollment in {ctx.store.directory} as each step lands",
    ]
    if not confirm(ctx, address, None, steps):
        return EXIT_REFUSED
    ctx.store.check_writable()
    ctx.say(f"Listening up to {ctx.args.seconds:g} s for {address}'s advertisement, to check the seed ...")
    advertisement = await find_advertisement(ctx, address, ctx.args.seconds)
    if advertisement is None:
        raise CliError(
            f"No 0xFD00 advertisement from {address} in {ctx.args.seconds:g} s, so its factory state cannot be "
            "confirmed. Wake the lock and try again.",
            EXIT_REFUSED,
        )
    if advertisement.enrolled:
        raise CliError(
            f"{address} advertises seed {advertisement.seed.hex()}: someone owns it over BLE already. "
            "This tool enrolls only a lock whose seed is 0000.",
            EXIT_REFUSED,
        )
    ctx.say("  seed 0000: factory state")
    check_login_budget(ctx, address)
    ctx.say("Do not interrupt from here on: the new owner key exists only in this process until it is saved.")
    async with open_session(ctx, address) as session:
        _describe_session(ctx, session)
        ctx.trace.note("enroll", step="start")
        try:
            enrollment = await enroll(session, name=name)
        except BleEnrollmentError as err:
            return _enrollment_stopped(ctx, address, err)
        except BleOperationError as err:
            ctx.failed_logins.record(address, "factory", _status_name(err.status))
            raise CliError(f"The lock refused the factory credential ({err}). Nothing changed on it.") from None
        path = ctx.store.save(enrollment, address)
    ctx.trace.note("enroll", step="done")
    _enrolled(ctx, path, address)
    return EXIT_OK


async def _resume(ctx: Context) -> int:
    address = ctx.args.address
    if ctx.args.state is not None:
        stored = ctx.store.load(Path(ctx.args.state).expanduser())
    else:
        found = ctx.store.by_address(address)
        if len(found) != 1:
            raise CliError(
                f"{'No' if not found else 'More than one'} stored enrollment was last seen at {address}; "
                "name it with --state FILE",
                EXIT_REFUSED,
            )
        stored = found[0]
    if stored.enrollment.complete:
        ctx.say(f"{stored.label} is complete already; nothing to resume.")
        return EXIT_OK
    remaining = [step.value for step in stored.enrollment.remaining]
    steps = [
        f"log in with the stored owner key ({stored.label}); if the lock refuses the factory device id, "
        "once more with the enrolled one",
        f"run the remaining steps: {', '.join(remaining)}",
        f"save the enrollment in {stored.path} as each step lands",
    ]
    if not confirm(ctx, address, None, steps):
        return EXIT_REFUSED
    ctx.store.check_writable()
    check_login_budget(ctx, address)
    async with open_session(ctx, address) as session:
        _describe_session(ctx, session)
        ctx.trace.note("enroll", step="resume", remaining=remaining)
        try:
            enrollment = await resume_enrollment(session, stored.enrollment)
        except BleEnrollmentError as err:
            return _enrollment_stopped(ctx, address, err)
        except BleOperationError as err:
            ctx.failed_logins.record(address, "stored", _status_name(err.status))
            raise CliError(f"The lock refused the stored owner key ({err}).") from None
        path = ctx.store.save(enrollment, address)
    _enrolled(ctx, path, address)
    return EXIT_OK


def _enrollment_stopped(ctx: Context, address: str, err: BleEnrollmentError) -> int:
    # Save first, print second: the partial enrollment holds the only copy of
    # the owner key the lock now has.
    if err.enrollment is not None:
        path = ctx.store.save(err.enrollment, address)
        ctx.trace.note("enroll", step="stopped", at=err.step.value, saved=True)
        ctx.say(f"Saved the partial enrollment to {path}.")
        ctx.say(f"Enrollment stopped: {err}")
        if err.__cause__ is not None:
            ctx.say(f"  cause: {type(err.__cause__).__name__}: {err.__cause__}")
        ctx.say(f"Finish it with: enroll {address} --resume --yes")
    else:
        ctx.trace.note("enroll", step="stopped", at=err.step.value, saved=False)
        ctx.say(f"Enrollment stopped: {err}")
        if err.__cause__ is not None:
            ctx.say(f"  cause: {type(err.__cause__).__name__}: {err.__cause__}")
        ctx.say(
            "UserAuthUpdate did not complete, so there was no owner key to save. The lock most likely still takes "
            "the factory credential (login --factory tells). If it took the new key and only its answer was lost, "
            "only a module reset gets it back."
        )
    return EXIT_FAILED


def _enrolled(ctx: Context, path: Path, address: str) -> None:
    ctx.say(f"Enrolled. Saved to {path}; it holds the owner key, so keep it and back it up.")
    ctx.say("Check it:")
    ctx.say(f"  login {address}: must work with the stored key")
    ctx.say(f"  login {address} --factory: must be refused")
    ctx.say("  scan: must show a seed other than 0000, and this lock as stored")


# --- Arguments ---------------------------------------------------------------------------


def _global_options(parser: argparse.ArgumentParser, *, defaults: bool) -> argparse.ArgumentParser:
    """The options every command takes, before or after its name.

    Only the top-level parser sets defaults. After the command the options
    default to SUPPRESS, so a command's parser leaves alone what was given
    before its name; an explicit default there would silently reset it.
    """

    def default(value: Any) -> Any:
        return value if defaults else argparse.SUPPRESS

    parser.add_argument(
        "--state-dir", default=default(str(DEFAULT_STATE_DIR)), help="where enrollments and traces are kept"
    )
    trace = parser.add_mutually_exclusive_group()
    trace.add_argument("--trace", metavar="FILE", help="frame log path (default: <state-dir>/traces/<time>.jsonl)")
    trace.add_argument("--no-trace", action="store_true", help="write no frame log")
    parser.add_argument(
        "--trace-secrets",
        action="store_true",
        help="also log every payload and the link keys: PINs and keys end up in the file",
    )
    parser.add_argument("--debug", action="store_true", help="library and bleak debug logging, and tracebacks")
    parser.add_argument("--connect-timeout", type=float, default=default(DEFAULT_CONNECT_TIMEOUT_S), metavar="S")
    parser.add_argument(
        "--response-timeout",
        type=float,
        default=default(None),
        metavar="S",
        help="per command (default: the app's 20 s)",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = _global_options(
        argparse.ArgumentParser(
            prog="ble_cli.py",
            description="Validate the Onesti/Nimly BLE library against a real lock, safe steps first.",
        ),
        defaults=True,
    )
    # The same options after the command too: `pin set ADDR 803 --yes --trace-secrets`.
    common = _global_options(
        argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS), defaults=False
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    scan = sub.add_parser("scan", parents=[common], help="list locks by their 0xFD00 advertisement; sends nothing")
    scan.add_argument("--seconds", type=float, default=DEFAULT_SCAN_S)
    scan.add_argument("--watch", type=float, metavar="S", help="log every advertisement for S seconds")
    scan.add_argument("--window", type=float, default=DEFAULT_WATCH_WINDOW_S, metavar="S", help="--watch scan window")

    address = argparse.ArgumentParser(add_help=False, parents=[common])
    address.add_argument("address", help="the lock's address as scan shows it (a UUID on macOS)")

    credentials = argparse.ArgumentParser(add_help=False)
    which = credentials.add_mutually_exclusive_group()
    which.add_argument("--factory", action="store_true", help="log in with the factory credential")
    which.add_argument("--state", metavar="FILE", help="log in with this stored enrollment")
    credentials.add_argument(
        "--force-login",
        action="store_true",
        help=f"try even after {FAILED_LOGIN_LIMIT} recorded failed logins",
    )

    yes = argparse.ArgumentParser(add_help=False)
    yes.add_argument("--yes", action="store_true", help="send it; without this, only print what would be sent")

    sub.add_parser("info", parents=[address], help="GATT services, characteristic properties, MTU; no protocol")
    sub.add_parser("handshake", parents=[address], help="firmware, key exchange, model; no login")
    sub.add_parser("login", parents=[address, credentials], help="owner login")
    sub.add_parser("read", parents=[address, credentials], help="login, then battery, log, model, name, clock")

    operate = sub.add_parser("operate", parents=[address, credentials, yes], help="lock or unlock the door")
    operate.add_argument("operation", choices=["lock", "unlock"])

    pin = sub.add_parser("pin", help="PIN codes in BLE slots 800-899")
    pin_actions = pin.add_subparsers(dest="action", required=True)
    pin_set = pin_actions.add_parser("set", parents=[address, credentials, yes])
    pin_set.add_argument("slot", type=int)
    pin_set.add_argument("--pin-stdin", action="store_true", help="read the PIN from stdin instead of a prompt")
    pin_clear = pin_actions.add_parser("clear", parents=[address, credentials, yes])
    pin_clear.add_argument("slot", type=int)

    for kind, slots in (("rfid", "900-999"), ("fingerprint", "150-199")):
        parser_kind = sub.add_parser(kind, help=f"{kind} in BLE slots {slots}")
        actions = parser_kind.add_subparsers(dest="action", required=True)
        for action in ("scan", "clear"):
            actions.add_parser(action, parents=[address, credentials, yes]).add_argument("slot", type=int)

    enroll_parser = sub.add_parser("enroll", parents=[address, yes], help="take over a factory-reset lock")
    enroll_parser.add_argument("--name", help="written to the lock, at most 8 ASCII characters")
    enroll_parser.add_argument("--resume", action="store_true", help="finish an enrollment that stopped partway")
    enroll_parser.add_argument("--state", metavar="FILE", help="with --resume: the stored enrollment to finish")
    enroll_parser.add_argument(
        "--seconds", type=float, default=DEFAULT_SCAN_S, help="how long to listen for the advertisement first"
    )
    enroll_parser.add_argument("--force-login", action="store_true", help=argparse.SUPPRESS)
    return parser


COMMANDS: Final[dict[str, Callable[[Context], Awaitable[int]]]] = {
    "scan": cmd_scan,
    "info": cmd_info,
    "handshake": cmd_handshake,
    "login": cmd_login,
    "read": cmd_read,
    "operate": cmd_operate,
    "pin": cmd_pin,
    "rfid": cmd_rfid,
    "fingerprint": cmd_fingerprint,
    "enroll": cmd_enroll,
}


def main(argv: list[str] | None = None, deps: Deps | None = None) -> int:
    global _CURRENT
    deps = deps or Deps()
    out = deps.out or sys.stdout
    err = deps.err or sys.stderr
    args = build_parser().parse_args(argv)
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, stream=err)
    else:
        logging.basicConfig(level=logging.WARNING, stream=err)
    state_dir = Path(args.state_dir).expanduser()
    if args.trace_secrets and not args.no_trace:
        print(
            "warning: --trace-secrets writes PINs, the owner challenge and the link keys to the trace file. "
            "Use test PINs on test slots, and delete the file when done.",
            file=err,
        )
    try:
        tracer = open_trace(args, state_dir)
    except CliError as failure:
        print(f"error: {failure}", file=err)
        return failure.exit_code
    ctx = Context(args, deps, StateStore(state_dir), tracer, out, err)
    _CURRENT = ctx
    try:
        code = asyncio.run(COMMANDS[args.command](ctx))
    except CliError as failure:
        tracer.note("error", kind="cli", message=str(failure))
        print(f"error: {failure}", file=err)
        code = failure.exit_code
    except BleError as failure:
        # The library's messages hold ids, statuses and lengths only.
        tracer.note("error", kind=type(failure).__name__, message=str(failure))
        print(f"error: {type(failure).__name__}: {failure}", file=err)
        if failure.__cause__ is not None:
            print(f"  cause: {type(failure.__cause__).__name__}: {failure.__cause__}", file=err)
        code = EXIT_FAILED
    except KeyboardInterrupt:
        tracer.note("error", kind="interrupted")
        print("interrupted", file=err)
        code = 130
    except Exception as failure:
        # bleak and the OS. Not ours, so only the type goes in the trace.
        tracer.note("error", kind=type(failure).__name__)
        if args.debug:
            raise
        print(f"error: {type(failure).__name__}: {failure} (--debug shows the traceback)", file=err)
        code = EXIT_FAILED
    finally:
        _CURRENT = None
        tracer.note("end")
        tracer.close()
    if tracer.failure is not None:
        print(f"warning: the trace is incomplete, writing it failed: {tracer.failure}", file=err)
    if tracer.path is not None:
        print(f"trace: {tracer.path}", file=err)
    return code


if __name__ == "__main__":
    sys.exit(main())

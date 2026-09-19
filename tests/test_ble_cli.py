"""scripts/ble_cli.py, the tool that validates the BLE library against a real lock.

The CLI runs here against tests/ble/fake_lock.py through an injected radio,
so every command goes through the real Session, login and enrollment code.
What these tests hold the CLI to, beyond "the command works":

- Nothing that changes the lock goes out without --yes, and nothing connects.
- A PIN, the owner key, the challenge and the link keys never reach the
  trace file, stdout or stderr without --trace-secrets, and do reach the
  trace with it (so the check can see a leak when there is one).
- A partial enrollment is saved before the error is shown, and resumes.
- State files are 0600 in a 0700 directory.
- FactoryResetModule is never sent, and the enrollment-only commands never
  go out outside enroll.

No pytest-asyncio: main() runs its own event loop, as it does from a shell.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import io
import json
import stat
import sys
from pathlib import Path

import pytest

from .ble.fake_lock import CHALLENGE, FakeBleakClient, FakeLock
from .conftest import COMPONENT_DIR, load_component_module

CLI_PATH = Path(__file__).resolve().parent.parent / "scripts" / "ble_cli.py"

fake_const = load_component_module("ble.protocol.const")
client_const = load_component_module("ble.client.const")


def _load_cli():
    """Import scripts/ble_cli.py as a module, and undo its sys.path insert.

    The CLI puts the component directory first on sys.path so it can import
    `ble` on its own. Left there, every module in the component (const.py,
    events.py, ...) would shadow a top-level module of the same name for the
    rest of the test session.
    """
    component = str(Path(COMPONENT_DIR).resolve())
    had_path = component in sys.path
    spec = importlib.util.spec_from_file_location("ble_cli_under_test", CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not had_path:
        sys.path.remove(component)
    return module


cli = _load_cli()
ble = sys.modules["ble"]
ble_const = sys.modules["ble.protocol.const"]
BleakTransport = importlib.import_module("ble.client.bleak_transport").BleakTransport

ADDRESS = "5F0C2B1A-0000-4000-8000-00000000A0CE"
PIN = "80418822"
PIN_HEX = PIN.encode("ascii").hex()
LOCK_UUID = client_const.ADVERTISING_UUID


# --- Doubles -------------------------------------------------------------------------


def _session(transport, tracer, response_timeout):
    # The CLI's own Session, minus the app's pauses, which only slow the tests.
    kwargs = {"command_delay": 0, "late_answer_grace": 0}
    if response_timeout is not None:
        kwargs["response_timeout"] = response_timeout
    return ble.Session(transport, tracer=tracer, **kwargs)


class FakeRadio:
    """Advertisements to report, and a FakeLock to connect to.

    open() goes through the real BleakTransport.connect, with FakeBleakClient
    as the client class, so the CLI runs on the transport it uses on a Mac.
    configure gets each connection's lock side (a FakeTransport) to set
    status overrides, silences and lost answers on.
    """

    def __init__(self, lock=None, adverts=(), configure=None):
        self.lock = lock
        self.adverts = list(adverts)
        self.configure = configure
        self.connects: list[str] = []
        self.clients = []
        self.scans = 0

    async def scan(self, seconds, on_seen):
        import asyncio

        self.scans += 1
        for seen in self.adverts:
            on_seen(seen)
        await asyncio.sleep(seconds)

    async def open(self, address, timeout):
        self.connects.append(address)
        if self.lock is None:
            raise cli.CliError(f"{address} was not seen")

        def client_class(device, **kwargs):
            client = FakeBleakClient(device, **kwargs)
            if self.configure is not None:
                self.configure(client.link)
            self.clients.append(client)
            return client

        return await BleakTransport.connect(self.lock, timeout=timeout, client_class=client_class)

    async def connect(self, address, timeout):
        raise AssertionError("only info inspects GATT; its tests use _GattRadio")

    async def disconnect(self, client):
        raise AssertionError("only info inspects GATT; its tests use _GattRadio")


FACTORY_IDENTIFIER = bytes.fromhex("0a0b0c0d0e0f")


def advert(address=ADDRESS, service_data=None, *, seed=bytes(2), identifier=FACTORY_IDENTIFIER):
    data = seed + identifier if service_data is None else service_data
    return cli.Seen(address=address, name="NimlyLock", rssi=-61, service_data={LOCK_UUID: data})


def enrolled_advert(device_id: bytes, address=ADDRESS, seed=b"\x12\x34"):
    identifier = hashlib.sha1(seed + device_id).digest()[:6]
    return advert(address, seed=seed, identifier=identifier)


class Run:
    """One CLI invocation's result."""

    def __init__(self, code, out, err, trace_path):
        self.code = code
        self.out = out
        self.err = err
        self.trace_path = trace_path

    @property
    def trace_text(self):
        return self.trace_path.read_text() if self.trace_path and self.trace_path.exists() else ""

    @property
    def trace(self):
        return [json.loads(line) for line in self.trace_text.splitlines()]

    def events(self, name):
        return [record for record in self.trace if record["event"] == name]


@pytest.fixture(autouse=True)
def default_state_dir(tmp_path, monkeypatch):
    """Points the default state dir away from the real home, and fails if anything used it.

    Every test passes --state-dir. A parser bug once reset it to the
    default whenever an option followed the command, and the tests wrote
    enrollments and failed logins into ~/.config/onesti-lock-ble.
    """
    default = tmp_path / "default-state-dir-must-stay-unused"
    monkeypatch.setattr(cli, "DEFAULT_STATE_DIR", default)
    yield default
    assert not default.exists(), "a command ignored --state-dir and used the default"


@pytest.fixture
def state_dir(tmp_path):
    return tmp_path / "state"


@pytest.fixture
def run_cli(state_dir, tmp_path):
    counter = iter(range(1000))

    def run(*argv, radio, stdin="", getpass=None, trace=True):
        out, err = io.StringIO(), io.StringIO()
        trace_path = tmp_path / f"trace-{next(counter)}.jsonl"
        options = ["--state-dir", str(state_dir), "--connect-timeout", "1", "--response-timeout", "2"]
        options += ["--trace", str(trace_path)] if trace else ["--no-trace"]
        deps = cli.Deps(
            radio=radio,
            session_factory=_session,
            stdin=io.StringIO(stdin),
            out=out,
            err=err,
            getpass=getpass or (lambda prompt: pytest.fail("unexpected PIN prompt")),
        )
        code = cli.main([*options, *argv], deps)
        return Run(code, out.getvalue(), err.getvalue(), trace_path if trace else None)

    return run


def enroll_lock(run_cli, lock, name="Door"):
    radio = FakeRadio(lock, [advert()])
    result = run_cli("enroll", ADDRESS, "--name", name, "--yes", "--seconds", "0", radio=radio)
    assert result.code == 0, result.out + result.err
    return result


def stored_files(state_dir):
    return sorted(state_dir.glob("*.json"))


# --- --yes ----------------------------------------------------------------------------


WRITES = [
    ["operate", ADDRESS, "unlock", "--factory"],
    ["operate", ADDRESS, "lock", "--factory"],
    ["pin", "set", ADDRESS, "803", "--factory", "--pin-stdin"],
    ["pin", "clear", ADDRESS, "803", "--factory"],
    ["rfid", "scan", ADDRESS, "900", "--factory"],
    ["rfid", "clear", ADDRESS, "900", "--factory"],
    ["fingerprint", "scan", ADDRESS, "150", "--factory"],
    ["fingerprint", "clear", ADDRESS, "150", "--factory"],
    ["enroll", ADDRESS, "--name", "Door"],
]


@pytest.mark.parametrize("argv", WRITES, ids=lambda argv: " ".join(argv[:2]))
def test_writes_need_yes(run_cli, state_dir, argv):
    lock = FakeLock()
    radio = FakeRadio(lock, [advert()])
    result = run_cli(*argv, radio=radio, stdin=PIN + "\n")
    assert result.code == cli.EXIT_REFUSED
    assert "Nothing was sent" in result.out
    assert "this will" in result.out
    assert radio.connects == []
    assert lock.commands == []
    assert stored_files(state_dir) == []


def test_pin_set_without_yes_does_not_read_the_pin(run_cli):
    stdin = io.StringIO(PIN + "\n")
    radio = FakeRadio(FakeLock())
    out = io.StringIO()
    deps = cli.Deps(radio=radio, stdin=stdin, out=out, err=io.StringIO())
    code = cli.main(["--no-trace", "pin", "set", ADDRESS, "803", "--factory", "--pin-stdin"], deps)
    assert code == cli.EXIT_REFUSED
    assert stdin.read() == PIN + "\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["pin", "set", ADDRESS, "5", "--factory", "--pin-stdin", "--yes"],
        ["pin", "clear", ADDRESS, "900", "--factory", "--yes"],
        ["rfid", "scan", ADDRESS, "803", "--factory", "--yes"],
        ["fingerprint", "clear", ADDRESS, "900", "--factory", "--yes"],
    ],
)
def test_slots_outside_the_range_are_refused_before_connecting(run_cli, argv):
    radio = FakeRadio(FakeLock())
    result = run_cli(*argv, radio=radio, stdin=PIN + "\n")
    assert result.code == cli.EXIT_REFUSED
    assert "Invalid SlotNumber" in result.err
    assert radio.connects == []


def test_a_malformed_pin_is_refused_before_connecting(run_cli):
    radio = FakeRadio(FakeLock())
    result = run_cli("pin", "set", ADDRESS, "803", "--factory", "--pin-stdin", "--yes", radio=radio, stdin="12ab\n")
    assert result.code == cli.EXIT_REFUSED
    assert radio.connects == []
    assert "12ab" not in result.out + result.err


def test_the_pin_prompt_asks_twice_and_refuses_a_mismatch(run_cli):
    answers = iter(["80418822", "80418823"])
    radio = FakeRadio(FakeLock())
    result = run_cli(
        "pin", "set", ADDRESS, "803", "--factory", "--yes", radio=radio, getpass=lambda prompt: next(answers)
    )
    assert result.code == cli.EXIT_REFUSED
    assert "differ" in result.err
    assert radio.connects == []


# --- Commands that never send anything ------------------------------------------------


def test_scan_reports_factory_and_enrolled_locks(run_cli, state_dir):
    lock = FakeLock()
    enroll_lock(run_cli, lock)
    [path] = stored_files(state_dir)
    device_id = bytes.fromhex(json.loads(path.read_text())["enrollment"]["device_id"])
    other = "11111111-2222-3333-4444-555555555555"
    radio = FakeRadio(
        adverts=[
            advert("AAAA0000-0000-0000-0000-000000000001"),
            enrolled_advert(device_id, address=other),
            advert("AAAA0000-0000-0000-0000-000000000002", service_data=b"\x00\x00\x01"),
            cli.Seen(address="not-a-lock", name="Speaker", rssi=-40, service_data={}),
        ]
    )
    result = run_cli("scan", "--seconds", "0", radio=radio)
    assert result.code == 0, result.err
    assert "enrolled   no: factory state, factory id 0f0e0d0c0b0a" in result.out
    assert "seed       1234" in result.out
    assert "stored     yes, Door" in result.out
    assert "does not parse" in result.out
    assert "not-a-lock" not in result.out
    # The stored lock was found at a new address, and that is remembered.
    assert json.loads(path.read_text())["address"] == other
    assert len(result.events("advertisement")) == 3
    assert radio.connects == []


def test_scan_says_so_when_nothing_is_heard(run_cli):
    result = run_cli("scan", "--seconds", "0", radio=FakeRadio())
    assert result.code == cli.EXIT_FAILED
    assert "No 0xFD00 advertiser was seen" in result.out


def test_scan_watch_logs_each_advertisement(run_cli):
    radio = FakeRadio(adverts=[advert()])
    result = run_cli("scan", "--watch", "0.05", "--window", "0.02", radio=radio)
    assert result.code == 0
    assert radio.scans >= 2
    assert result.out.count(ADDRESS) >= 2
    assert "seed 0000" in result.out


class _Characteristic:
    def __init__(self, uuid, properties, description=""):
        self.uuid = uuid
        self.properties = properties
        self.description = description


class _Service:
    def __init__(self, uuid, characteristics, description=""):
        self.uuid = uuid
        self.characteristics = characteristics
        self.description = description


class _GattClient:
    """The GATT side of a BleakClient, as much as info reads."""

    mtu_size = 185

    def __init__(self):
        self.services = [
            _Service(
                "0000180a-0000-1000-8000-00805f9b34fb",
                [
                    _Characteristic(client_const.SOFTWARE_REVISION_CHARACTERISTIC_UUID, ["read"]),
                    _Characteristic("00002a29-0000-1000-8000-00805f9b34fb", ["read"]),
                ],
                "Device Information",
            ),
            _Service(
                client_const.SERVICE_UUID,
                [_Characteristic(client_const.COMMUNICATION_CHARACTERISTIC_UUID, ["write", "notify"])],
            ),
        ]
        self.disconnected = False

    async def read_gatt_char(self, characteristic):
        if characteristic.uuid == client_const.SOFTWARE_REVISION_CHARACTERISTIC_UUID:
            return bytearray(b"4.8.0")
        raise OSError("read not permitted")


class _GattRadio(FakeRadio):
    def __init__(self):
        super().__init__()
        self.client = _GattClient()

    async def connect(self, address, timeout):
        self.connects.append(address)
        return self.client

    async def disconnect(self, client):
        client.disconnected = True


def test_info_lists_gatt_without_protocol_frames(run_cli):
    radio = _GattRadio()
    result = run_cli("info", ADDRESS, radio=radio)
    assert result.code == 0, result.err
    assert "MTU 185" in result.out
    assert f"characteristic {client_const.COMMUNICATION_CHARACTERISTIC_UUID}  [notify, write]" in result.out
    assert "Software Revision: '4.8.0'" in result.out
    assert "Manufacturer Name: read failed" in result.out
    assert radio.client.disconnected
    assert result.events("packet") == []


# --- Sessions ---------------------------------------------------------------------------


def test_handshake_reports_firmware_and_model(run_cli):
    lock = FakeLock()
    radio = FakeRadio(lock)
    result = run_cli("handshake", ADDRESS, radio=radio)
    assert result.code == 0, result.err
    assert "connected, MTU 23" in result.out
    [client] = radio.clients
    assert not client.is_connected and client.disconnect_calls == 1
    [exchange] = [r for r in result.events("command") if r["id"] == "EXCHANGE_KEY_PUB_M"]
    assert exchange["len"] == 64 and len(exchange["payload"]) == 128
    [model] = [r for r in result.events("response") if r["id"] == "DEVICE_MODEL_GET"]
    assert model["status"] == "SUCCESS" and model["payload"] == "21"
    assert "firmware 4.8.0, CommandRef counter 1-127" in result.out
    assert "model NIMLY_PRO_24" in result.out
    assert [c.command_id for c in lock.commands] == [
        fake_const.CommandId.EXCHANGE_KEY_PUB_M,
        fake_const.CommandId.DEVICE_MODEL_GET,
    ]
    packets = result.events("packet")
    assert packets[0]["dir"] == "out" and packets[0]["type"] == "BLOB_START"
    assert {p["dir"] for p in packets} == {"out", "in"}
    [session] = result.events("session")
    assert session["firmware"] == "4.8.0"
    assert result.events("link_keys") == []


def test_handshake_on_old_firmware_uses_the_static_ref(run_cli):
    result = run_cli("handshake", ADDRESS, radio=FakeRadio(FakeLock(firmware=b"4.7.10")))
    assert result.code == 0, result.err
    assert "static CommandRef 16" in result.out


def test_login_with_the_factory_credential(run_cli):
    result = run_cli("login", ADDRESS, "--factory", radio=FakeRadio(FakeLock()))
    assert result.code == 0, result.err
    assert "logged in" in result.out


def test_login_without_a_credential_is_refused(run_cli):
    radio = FakeRadio(FakeLock())
    result = run_cli("login", ADDRESS, radio=radio)
    assert result.code == cli.EXIT_REFUSED
    assert "--factory" in result.err
    assert radio.connects == []


def test_failed_logins_are_counted_and_then_refused(run_cli, state_dir):
    lock = FakeLock(owner_key=bytes(16))
    radio = FakeRadio(lock)
    for _ in range(cli.FAILED_LOGIN_LIMIT):
        result = run_cli("login", ADDRESS, "--factory", radio=radio)
        assert result.code == cli.EXIT_FAILED
        assert "refused the login" in result.err
        assert "SECURITY_ERROR" in result.err
    assert len(radio.connects) == cli.FAILED_LOGIN_LIMIT
    assert (state_dir / "failed-logins.jsonl").stat().st_mode & 0o777 == 0o600

    result = run_cli("login", ADDRESS, "--factory", radio=radio)
    assert result.code == cli.EXIT_REFUSED
    assert "--force-login" in result.err
    assert len(radio.connects) == cli.FAILED_LOGIN_LIMIT

    result = run_cli("login", ADDRESS, "--factory", "--force-login", radio=radio)
    assert result.code == cli.EXIT_FAILED
    assert len(radio.connects) == cli.FAILED_LOGIN_LIMIT + 1


def test_read_reports_each_answer_and_carries_on_after_a_refusal(run_cli):
    result = run_cli("read", ADDRESS, "--factory", radio=FakeRadio(FakeLock()))
    # The fake lock does not know DeviceLogGet, DeviceNameGet or CurrentTimeGet.
    assert result.code == cli.EXIT_FAILED
    assert "DeviceModelGet: NIMLY_PRO_24" in result.out
    assert "BattInfoGet: level 5800, 80 %, low battery no" in result.out
    assert "DeviceLogGet: refused" in result.out
    assert "CurrentTimeGet: refused" in result.out


def test_operate_moves_the_bolt(run_cli):
    lock = FakeLock()
    # The fake has no EkeyOperate handler, so it answers NOT_SUPPORTED; the
    # CLI must still have sent exactly that command, after the login.
    result = run_cli("operate", ADDRESS, "unlock", "--factory", "--yes", radio=FakeRadio(lock))
    ids = [c.command_id for c in lock.commands]
    assert ids[-1] == fake_const.CommandId.EKEY_OPERATE
    assert lock.commands[-1].payload == bytes([fake_const.EkeyOperationId.UNLOCK])
    assert result.code == cli.EXIT_FAILED
    assert "NOT_SUPPORTED_ERROR" in result.out


def test_pin_set_and_clear(run_cli):
    lock = FakeLock()
    result = run_cli("pin", "set", ADDRESS, "803", "--factory", "--pin-stdin", "--yes", radio=FakeRadio(lock), stdin=PIN)
    assert result.code == 0, result.err
    assert lock.pins == {803: PIN}
    assert "a PIN of 8 digits" in result.out
    assert "status SUCCESS" in result.out

    result = run_cli("pin", "clear", ADDRESS, "803", "--factory", "--yes", radio=FakeRadio(lock))
    assert result.code == 0, result.err
    assert lock.pins == {}


def test_pin_set_refuses_old_firmware_before_login(run_cli):
    lock = FakeLock(firmware=b"4.7.10")
    result = run_cli("pin", "set", ADDRESS, "803", "--factory", "--pin-stdin", "--yes", radio=FakeRadio(lock), stdin=PIN)
    assert result.code == cli.EXIT_REFUSED
    assert "UNAVAILABLE_VERSION" in result.err and "4.7.90" in result.err
    assert fake_const.CommandId.USER_AUTH_BEGIN not in [c.command_id for c in lock.commands]


def test_fingerprint_is_refused_on_a_model_without_a_reader(run_cli):
    lock = FakeLock(model=fake_const.LockModelId.NIMLY_CODE_2)
    result = run_cli("fingerprint", "scan", ADDRESS, "150", "--factory", "--yes", radio=FakeRadio(lock))
    assert result.code == cli.EXIT_REFUSED
    assert "NIMLY_CODE_2" in result.err
    assert fake_const.CommandId.FINGERPRINT_SCAN not in [c.command_id for c in lock.commands]


def test_read_on_old_firmware_skips_what_the_app_does_not_offer(run_cli):
    lock = FakeLock(firmware=b"4.7.10")
    result = run_cli("read", ADDRESS, "--factory", radio=FakeRadio(lock))
    assert "BattInfoGet: not sent, the app does not offer it on this lock (UNAVAILABLE_VERSION)" in result.out
    assert fake_const.CommandId.BATT_INFO_GET not in [c.command_id for c in lock.commands]


def test_rfid_and_fingerprint_scans(run_cli):
    lock = FakeLock()
    result = run_cli("rfid", "scan", ADDRESS, "900", "--factory", "--yes", radio=FakeRadio(lock))
    assert result.code == 0, result.err
    assert "Hold the tag to the lock within 2 s" in result.out
    assert "event: UserAdded slot 900, RFID_CODE" in result.out
    assert "slot 900, result OK" in result.out
    result = run_cli("fingerprint", "scan", ADDRESS, "150", "--factory", "--yes", radio=FakeRadio(lock))
    assert result.code == 0, result.err
    assert "slot 150, result OK" in result.out
    assert lock.rfids == {900} and lock.fingerprints == {150}
    result = run_cli("rfid", "clear", ADDRESS, "900", "--factory", "--yes", radio=FakeRadio(lock))
    assert result.code == 0, result.err
    assert lock.rfids == set()


# --- Enrollment --------------------------------------------------------------------------


def test_enroll_saves_the_enrollment_and_later_logins_use_it(run_cli, state_dir):
    lock = FakeLock()
    result = enroll_lock(run_cli, lock)
    [path] = stored_files(state_dir)
    saved = json.loads(path.read_text())
    assert saved["address"] == ADDRESS
    enrollment = saved["enrollment"]
    assert bytes.fromhex(enrollment["owner_key"]) == lock.owner_key
    assert bytes.fromhex(enrollment["device_id"]) == lock.device_id
    device_hash = hashlib.sha256(bytes.fromhex(enrollment["device_id"])).hexdigest()[:16]
    assert path.name == f"lock-{device_hash}.json"
    assert lock.name == "Door"
    assert "Enrolled" in result.out
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700

    # The stored lock is found by its address without naming the file.
    result = run_cli("login", ADDRESS, radio=FakeRadio(lock))
    assert result.code == 0, result.err
    assert "the stored enrollment Door" in result.out
    result = run_cli("login", ADDRESS, "--factory", radio=FakeRadio(lock))
    assert result.code == cli.EXIT_FAILED


def test_enroll_refuses_a_lock_that_advertises_an_owner(run_cli, state_dir):
    lock = FakeLock()
    radio = FakeRadio(lock, [advert(seed=b"\x12\x34")])
    result = run_cli("enroll", ADDRESS, "--name", "Door", "--yes", "--seconds", "0", radio=radio)
    assert result.code == cli.EXIT_REFUSED
    assert "seed 1234" in result.err
    assert radio.connects == []


def test_enroll_refuses_without_seeing_the_advertisement(run_cli):
    radio = FakeRadio(FakeLock(), [advert("SOMEONE-ELSE")])
    result = run_cli("enroll", ADDRESS, "--name", "Door", "--yes", "--seconds", "0", radio=radio)
    assert result.code == cli.EXIT_REFUSED
    assert "cannot be confirmed" in result.err
    assert radio.connects == []


def test_enroll_refuses_a_lock_with_a_state_file(run_cli):
    lock = FakeLock()
    enroll_lock(run_cli, lock)
    radio = FakeRadio(lock, [advert()])
    result = run_cli("enroll", ADDRESS, "--name", "Door", "--yes", "--seconds", "0", radio=radio)
    assert result.code == cli.EXIT_REFUSED
    assert "--resume" in result.err
    assert radio.connects == []


def test_enroll_refuses_a_bad_name_before_anything(run_cli):
    radio = FakeRadio(FakeLock(), [advert()])
    result = run_cli("enroll", ADDRESS, "--name", "Front door", "--yes", "--seconds", "0", radio=radio)
    assert result.code == cli.EXIT_REFUSED
    assert radio.scans == 0


def test_a_partial_enrollment_is_saved_before_the_error_and_resumes(run_cli, state_dir):
    lock = FakeLock()

    def fail_server_key(transport):
        transport.status_overrides[fake_const.CommandId.SERVER_KEY_UPDATE] = fake_const.ResponseStatusId.FAILED

    radio = FakeRadio(lock, [advert()], configure=fail_server_key)
    result = run_cli("enroll", ADDRESS, "--name", "Door", "--yes", "--seconds", "0", radio=radio)
    assert result.code == cli.EXIT_FAILED
    assert result.out.index("Saved the partial enrollment") < result.out.index("Enrollment stopped")
    assert "server_key" in result.out
    [path] = stored_files(state_dir)
    partial = json.loads(path.read_text())["enrollment"]
    assert "server_key" not in partial["completed"]
    assert bytes.fromhex(partial["owner_key"]) == lock.owner_key
    [stopped] = [r for r in result.events("enroll") if r.get("step") == "stopped"]
    assert stopped["saved"] is True

    # Without --yes, resume only says what it would do.
    result = run_cli("enroll", ADDRESS, "--resume", radio=FakeRadio(lock))
    assert result.code == cli.EXIT_REFUSED
    assert "server_key, name" in result.out

    result = run_cli("enroll", ADDRESS, "--resume", "--yes", radio=FakeRadio(lock))
    assert result.code == 0, result.out + result.err
    finished = json.loads(path.read_text())["enrollment"]
    assert set(finished["completed"]) == {"owner_key", "device_id", "clock", "server_key", "name"}
    assert lock.name == "Door"


def test_an_enrollment_that_fails_at_the_owner_key_saves_nothing(run_cli, state_dir):
    lock = FakeLock()

    def fail_update(transport):
        transport.status_overrides[fake_const.CommandId.USER_AUTH_UPDATE] = fake_const.ResponseStatusId.FAILED

    radio = FakeRadio(lock, [advert()], configure=fail_update)
    result = run_cli("enroll", ADDRESS, "--name", "Door", "--yes", "--seconds", "0", radio=radio)
    assert result.code == cli.EXIT_FAILED
    assert "no owner key to save" in result.out
    assert stored_files(state_dir) == []


# --- Secrets in the trace and the output ---------------------------------------------------


def _secrets_of(lock, state_dir):
    """Every secret a session with this lock handled, as the strings a leak would show."""
    found = {"PIN": PIN, "PIN as hex": PIN_HEX, "challenge": CHALLENGE.hex(), "owner key": lock.owner_key.hex()}
    for path in stored_files(state_dir):
        enrollment = json.loads(path.read_text())["enrollment"]
        found["server key"] = enrollment["server_private_key"]
        found["device id"] = enrollment["device_id"]
    return found


def test_no_secret_reaches_the_trace_or_the_output(run_cli, state_dir):
    lock = FakeLock()
    enroll_lock(run_cli, lock)
    radio = FakeRadio(lock)
    result = run_cli("pin", "set", ADDRESS, "803", "--pin-stdin", "--yes", radio=radio, stdin=PIN)
    assert result.code == 0, result.err
    assert lock.pins == {803: PIN}
    assert result.trace, "the trace is empty, so this test checks nothing"
    for label, value in _secrets_of(lock, state_dir).items():
        assert value not in result.trace_text, f"{label} in the trace"
        assert value not in result.out + result.err, f"{label} in the output"
    assert result.events("link_keys") == []
    [pin_set] = [r for r in result.events("command") if r["id"] == "PIN_CODE_SET"]
    assert pin_set["len"] == 11 and "payload" not in pin_set
    [begin] = [r for r in result.events("response") if r["id"] == "USER_AUTH_BEGIN"]
    assert begin["len"] == 16 and "payload" not in begin


def test_trace_secrets_writes_them(run_cli, state_dir):
    lock = FakeLock()
    enroll_lock(run_cli, lock)
    result = run_cli(
        "--trace-secrets", "pin", "set", ADDRESS, "803", "--pin-stdin", "--yes", radio=FakeRadio(lock), stdin=PIN
    )
    assert result.code == 0, result.err
    assert "--trace-secrets writes PINs" in result.err
    assert PIN_HEX in result.trace_text
    assert CHALLENGE.hex() in result.trace_text
    [keys] = result.events("link_keys")
    assert len(bytes.fromhex(keys["key"])) == 16 and len(bytes.fromhex(keys["iv"])) == 16


def test_link_keys_are_traced_even_when_connect_fails(run_cli):
    def lose_model(transport):
        transport.silent.add(fake_const.CommandId.DEVICE_MODEL_GET)

    radio = FakeRadio(FakeLock(), configure=lose_model)
    # After the command, where the global options are accepted too, without
    # resetting --state-dir and --trace given before it.
    result = run_cli("handshake", ADDRESS, "--trace-secrets", radio=radio)
    assert result.code == cli.EXIT_FAILED
    assert "BleTimeoutError" in result.err
    assert len(result.events("link_keys")) == 1
    assert result.events("error")[0]["kind"] == "BleTimeoutError"


class _Command:
    def __init__(self, command_id, payload, ref=1):
        self.command_id = command_id
        self.command_ref = ref
        self.payload = payload


class _Response:
    def __init__(self, response_id, payload, status=0, ref=1):
        self.response_id = response_id
        self.command_ref = ref
        self.status = status
        self.payload = payload
        self.is_event = ref == 0x80


def _tracer_lines(secrets, feed):
    handle = io.StringIO()
    tracer = cli.RedactingTracer(handle, secrets=secrets)
    feed(tracer)
    return [json.loads(line) for line in handle.getvalue().splitlines()]


@pytest.mark.parametrize("secrets", [False, True])
def test_the_tracer_redacts_by_command(secrets):
    CommandId = ble_const.CommandId
    ResponseId = ble_const.ResponseId
    pin_payload = bytes.fromhex("2303") + bytes([8]) + PIN.encode()

    def feed(tracer):
        tracer.command(_Command(CommandId.PIN_CODE_SET, pin_payload))
        tracer.command(_Command(CommandId.USER_AUTH_FINALIZE, CHALLENGE))
        tracer.command(_Command(CommandId.DEVICE_ID_SET, b"\x01\x02\x03\x04\x05\x06"))
        tracer.command(_Command(CommandId.BATT_INFO_GET, b""))
        tracer.command(_Command(0x99, b"\xaa\xbb"))
        tracer.response(_Response(ResponseId.USER_AUTH_BEGIN, CHALLENGE))
        tracer.response(_Response(ResponseId.BATT_INFO_GET, bytes.fromhex("a8160050")))
        tracer.response(_Response(ResponseId.LOCK_STATUS, bytes.fromhex("23030102"), ref=0x80))
        tracer.dropped(ble.BleProtocolError("bad"), CHALLENGE)

    lines = _tracer_lines(secrets, feed)
    text = json.dumps(lines)
    assert (PIN_HEX in text) is secrets
    assert (CHALLENGE.hex() in text) is secrets
    assert ("010203040506" in text) is secrets
    by_id = {(line["event"], line.get("id")): line for line in lines}
    assert by_id[("command", "PIN_CODE_SET")]["len"] == 11
    assert by_id[("command", "0x99")]["len"] == 2
    assert by_id[("response", "BATT_INFO_GET")]["payload"] == "a8160050"
    assert by_id[("response", "LOCK_STATUS")]["unsolicited"] is True
    assert by_id[("response", "LOCK_STATUS")]["payload"] == "23030102"
    assert by_id[("command", "BATT_INFO_GET")]["payload"] == ""


def test_a_failing_trace_file_is_reported_not_fatal():
    class Broken(io.StringIO):
        def write(self, text):
            raise OSError(28, "No space left on device")

    tracer = cli.RedactingTracer(Broken(), secrets=False)
    tracer.packet_out(b"\x01\x02\x00\x01\xaa\xbb")
    tracer.note("anything")
    assert "No space left" in tracer.failure


def test_the_default_trace_goes_into_a_private_directory(state_dir):
    radio = FakeRadio(FakeLock())
    err = io.StringIO()
    deps = cli.Deps(
        radio=radio, session_factory=_session, out=io.StringIO(), err=err
    )
    assert cli.main(["--state-dir", str(state_dir), "handshake", ADDRESS], deps) == 0
    [trace] = list((state_dir / "traces").glob("*-handshake.jsonl"))
    assert stat.S_IMODE(trace.stat().st_mode) == 0o600
    assert stat.S_IMODE((state_dir / "traces").stat().st_mode) == 0o700
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert f"trace: {trace}" in err.getvalue()


# --- What the CLI must never send ----------------------------------------------------------


def test_send_refuses_the_commands_only_enroll_may_send():
    import asyncio

    class NoSession:
        async def send(self, payload):
            raise AssertionError("reached the lock")

    for payload in (
        ble.commands.device_id_set(b"\x01" * 6),
        ble.commands.user_auth_update(0, 0, b"\x01" * 64),
        ble.commands.server_key_update(b"\x01" * 64),
        cli.CommandPayload(cli.CommandId.FACTORY_RESET_MODULE),
    ):
        with pytest.raises(cli.CliError) as caught:
            asyncio.run(cli._send(NoSession(), payload))
        assert caught.value.exit_code == cli.EXIT_REFUSED


def test_the_cli_source_never_builds_a_forbidden_command():
    """No builder for an ownership or reset command is ever called from the CLI.

    enroll() and resume_enrollment() send DeviceIdSet, UserAuthUpdate and
    ServerKeyUpdate inside the library; the CLI itself must not name them,
    nor the master PIN or the unchecked PIN slot.
    """
    tree = ast.parse(CLI_PATH.read_text())
    forbidden = {"device_id_set", "user_auth_update", "server_key_update", "master_pin_code_set"}
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not names & forbidden
    keywords = {node.arg for node in ast.walk(tree) if isinstance(node, ast.keyword)}
    assert "ignore_slot_check" not in keywords
    uses = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "FACTORY_RESET_MODULE"
    ]
    assert len(uses) == 1, "FACTORY_RESET_MODULE may appear only in NEVER_SENT_COMMANDS"

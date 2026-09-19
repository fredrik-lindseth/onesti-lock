"""Owner login, and the admin commands it unlocks, through an encrypted session.

The challenge answer is computed here with the cryptography package, not
with ble/crypto.py, and compared with what the session actually sent.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ...conftest import COMPONENT_DIR, load_component_module
from ..fake_lock import CHALLENGE, PHONE_LINK_PRIVATE_KEY, FakeLock, key_pairs
from ..leaks import MARKER, assert_clean, assert_no_material

const = load_component_module("ble.protocol.const")
client_const = load_component_module("ble.client.const")
auth = load_component_module("ble.client.auth")
commands = load_component_module("ble.protocol.commands")
crypto = load_component_module("ble.crypto")
errors = load_component_module("ble.errors")
responses = load_component_module("ble.protocol.responses")
session_mod = load_component_module("ble.client.session")

CommandId = const.CommandId


def run(coro):
    return asyncio.run(coro)


def new_session(transport):
    return session_mod.Session(
        transport, command_delay=0, response_timeout=1.0, key_pair_factory=key_pairs(PHONE_LINK_PRIVATE_KEY)
    )


def expected_answer(owner_key: bytes, link_iv: bytes) -> bytes:
    """NimlyEkeyDevice $27 by hand: decrypt, flip every bit, encrypt, one CBC block from the link IV."""
    cipher = Cipher(algorithms.AES(owner_key), modes.CBC(link_iv))
    decryptor = cipher.decryptor()
    plain = decryptor.update(CHALLENGE) + decryptor.finalize()
    encryptor = cipher.encryptor()
    return encryptor.update(bytes(b ^ 0xFF for b in plain)) + encryptor.finalize()


@contextlib.asynccontextmanager
async def logged_in(lock, credential=auth.DEFAULT_OWNER_CREDENTIAL):
    transport = lock.connect()
    async with new_session(transport) as session:
        await auth.authenticate_owner(session, credential)
        yield transport, session


async def log_in(lock, credential=auth.DEFAULT_OWNER_CREDENTIAL):
    async with logged_in(lock, credential) as (transport, session):
        return transport, session.link_keys


class TestAuthenticateOwner:
    def test_factory_credential_on_a_reset_lock(self):
        lock = FakeLock()

        transport, link = run(log_in(lock))
        assert transport.authenticated
        begin, finalize = transport.commands[2:4]
        assert begin.command_id is CommandId.USER_AUTH_BEGIN
        assert begin.payload == bytes(7)
        assert finalize.command_id is CommandId.USER_AUTH_FINALIZE
        assert finalize.payload == expected_answer(client_const.DEFAULT_ENCRYPTION_KEY, link.iv)

    def test_wrong_key_is_refused(self):
        lock = FakeLock(owner_key=bytes(range(16)))
        with pytest.raises(errors.BleSecurityError):
            run(log_in(lock))

    def test_wrong_device_id_is_refused(self):
        lock = FakeLock(device_id=bytes.fromhex("010203040506"))
        with pytest.raises(errors.BleSecurityError):
            run(log_in(lock))

    def test_right_key_and_device_id_after_enrollment(self):
        device_id = bytes.fromhex("0A0B0C0D0E0F")
        owner_key = bytes(range(16, 32))
        lock = FakeLock(owner_key=owner_key, device_id=device_id)
        credential = auth.OwnerCredential(0, device_id, owner_key)

        transport, _ = run(log_in(lock, credential))
        assert transport.authenticated

    def test_admin_commands_need_the_login(self):
        """The fake lock's rule, which this checks the session reports as the mapped error."""

        async def scenario():
            transport = FakeLock().connect()
            async with new_session(transport) as session:
                await session.send(commands.pin_code_set(803, "8832"))

        with pytest.raises(errors.BleSecurityError):
            run(scenario())


class TestAdminCommandsThroughTheEncryptedSession:
    def test_pin_code_set_and_clear(self):
        lock = FakeLock()

        async def scenario():
            async with logged_in(lock) as (transport, session):
                await session.send(commands.pin_code_set(803, "8832"))
                assert lock.pins == {803: "8832"}
                await session.send(commands.pin_code_clear(803))
                assert lock.pins == {}
                with pytest.raises(errors.BleNotFoundError):
                    await session.send(commands.pin_code_clear(803))
            return transport

        transport = run(scenario())
        set_command = transport.commands[4]
        assert set_command.to_bytes() == bytes.fromhex("52 07 05 00 23 03 04 38 38 33 32")
        # The PIN never crosses the air in the clear.
        assert b"8832" not in b"".join(transport.writes)

    def test_master_pin_in_slot_0(self):
        lock = FakeLock()

        async def scenario():
            async with logged_in(lock) as (_, session):
                await session.send(commands.master_pin_code_set("123456"))

        run(scenario())
        assert lock.pins == {0: "123456"}

    def test_fingerprint_scan_and_clear(self):
        lock = FakeLock()
        seen = []

        async def scenario():
            async with logged_in(lock) as (_, session):
                session.add_event_listener(seen.append)
                result = await session.request(commands.fingerprint_scan(150), responses.parse_fingerprint_scan)
                await session.send(commands.fingerprint_clear(150))
                return result

        assert run(scenario()) == responses.ScanResult(150, const.LockStatusId.OK)
        assert seen == [responses.UserAdded(150, const.UserAddedStatusId.FINGERPRINT)]
        assert lock.fingerprints == set()

    def test_rfid_scan_and_clear(self):
        lock = FakeLock()
        seen = []

        async def scenario():
            async with logged_in(lock) as (_, session):
                session.add_event_listener(seen.append)
                result = await session.request(commands.scan_rfid_code(999), responses.parse_scan_rfid_code)
                assert lock.rfids == {999}
                await session.send(commands.rfid_code_clear(999))
                with pytest.raises(errors.BleNotFoundError):
                    await session.send(commands.rfid_code_clear(999))
                return result

        assert run(scenario()) == responses.ScanResult(999, const.LockStatusId.OK)
        assert seen == [responses.UserAdded(999, const.UserAddedStatusId.RFID_CODE)]
        assert lock.rfids == set()

    def test_a_command_the_lock_does_not_know(self):
        async def scenario():
            async with logged_in(FakeLock()) as (_, session):
                await session.send(commands.volume_set(const.LockVolumeId.LOW))

        with pytest.raises(errors.BleNotSupportedError):
            run(scenario())


class TestOwnerCredential:
    def test_default_credential(self):
        credential = auth.DEFAULT_OWNER_CREDENTIAL
        assert credential.user_id == 0
        assert credential.device_id == bytes(6)
        assert credential.key == bytes([0x11] * 16)

    def test_default_iv_is_never_read(self):
        # Constants.DefaultEncryptionIv (0x22 x 16) is never read by the app:
        # owner auth runs on the link IV. Using it anywhere would be the
        # mistake the docs once suggested; client/const.py only defines it.
        ble_dir = Path(COMPONENT_DIR) / "ble"
        users = []
        for path in sorted(ble_dir.rglob("*.py")):
            if path == ble_dir / "client" / "const.py":
                continue
            tree = ast.parse(path.read_text())
            names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
            names |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
            if "DEFAULT_ENCRYPTION_IV" in names:
                users.append(path.name)
        assert not users

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"user_id": -1}, "User id must be 0-255, got -1"),
            ({"user_id": 256}, "User id must be 0-255, got 256"),
            ({"device_id": bytes(5)}, "Device id must be 6 bytes, got 5"),
            ({"key": MARKER[:15]}, "Owner key must be 16 bytes, got 15"),
        ],
    )
    def test_validation(self, kwargs, message):
        fields = {"user_id": 0, "device_id": bytes(6), "key": bytes([0x11] * 16)} | kwargs
        with pytest.raises(errors.BleValidationError, match=message) as excinfo:
            auth.OwnerCredential(**fields)
        assert_clean(excinfo, MARKER[:15])

    def test_repr_leaves_the_key_out(self):
        text = repr(auth.DEFAULT_OWNER_CREDENTIAL)
        assert_no_material(text, client_const.DEFAULT_ENCRYPTION_KEY)
        assert "user_id=0" in text

"""Session: the key exchange, command correlation, events, errors and timeouts.

The lock is tests/ble/fake_lock.py. Wire bytes are checked against framing
and AES done here with the cryptography package directly, not through the
session's own cipher, so a mistake in the session cannot hide in both
sides of an assertion.

No pytest-asyncio: CI's unit group does not have it, so each test runs its
coroutine through asyncio.run.
"""
from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ...conftest import COMPONENT_DIR, load_component_module
from .. import crypto_vectors, vectors
from ..fake_lock import (
    BATT_INFO_PAYLOAD,
    LOCK_LINK_PRIVATE_KEY,
    PHONE_LINK_PRIVATE_KEY,
    FakeLock,
    ecdh_reversed,
    key_pairs,
    public_key,
)

const = load_component_module("ble.protocol.const")
commands = load_component_module("ble.protocol.commands")
crypto = load_component_module("ble.crypto")
errors = load_component_module("ble.errors")
packet = load_component_module("ble.protocol.packet")
response_mod = load_component_module("ble.protocol.response")
responses = load_component_module("ble.protocol.responses")
session_mod = load_component_module("ble.client.session")

CommandId = const.CommandId
ResponseId = const.ResponseId
Status = const.ResponseStatusId
Session = session_mod.Session

# From conftest, not counted up from this file: parents[2] was right before the
# tests moved into tests/ble/client/, and silently pointed at nothing after.
BLE_DIR = Path(COMPONENT_DIR).resolve() / "ble"


def run(coro):
    return asyncio.run(coro)


def open_transport(**kwargs):
    """A connection to a fresh fake lock that answers without a login."""
    return FakeLock().connect(require_login=False, **kwargs)


def new_session(transport, **kwargs):
    kwargs.setdefault("command_delay", 0)
    kwargs.setdefault("response_timeout", 1.0)
    kwargs.setdefault("key_pair_factory", key_pairs(PHONE_LINK_PRIVATE_KEY))
    return Session(transport, **kwargs)


def expected_link_keys():
    return crypto.LinkKeys.from_shared_secret(
        ecdh_reversed(PHONE_LINK_PRIVATE_KEY, public_key(LOCK_LINK_PRIVATE_KEY))
    )


def aes_cbc(key: bytes, iv: bytes, data: bytes) -> bytes:
    """Zero-pad and encrypt, straight through cryptography."""
    data = data + bytes(-len(data) % 16)
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(data) + encryptor.finalize()


def blob_packets(payload: bytes, *, encrypted: bool) -> list[bytes]:
    """PayloadStream.writeBlob at MTU 23, by hand: 12 bytes after the blob header, then 16 per packet."""
    flags = 1 if encrypted else 0
    first = payload[:12]
    out = [bytes([0x03, 4 + len(first), 0, 1, flags]) + len(payload).to_bytes(2, "little") + b"\x00" + first]
    rest = payload[12:]
    sequence = 2
    while rest:
        chunk, rest = rest[:16], rest[16:]
        out.append(bytes([0x05 if not rest else 0x04, len(chunk), 0, sequence]) + chunk)
        sequence += 1
    return out


# --- Firmware revision ----------------------------------------------------------


class TestSoftwareRevision:
    def test_three_numbers(self):
        assert session_mod.parse_software_revision(b"4.7.90") == (4, 7, 90)

    def test_trailing_terminator_and_whitespace(self):
        assert session_mod.parse_software_revision(b"4.8.0\x00\x00") == (4, 8, 0)
        assert session_mod.parse_software_revision(b"4.8.0\r\n") == (4, 8, 0)

    @pytest.mark.parametrize("raw", [b"4.8", b"4.8.0.1", b"4.x.0", b"", b"4..0", b"-4.8.0"])
    def test_malformed(self, raw):
        with pytest.raises(errors.BleProtocolError, match="major.minor.bugfix"):
            session_mod.parse_software_revision(raw)

    def test_not_ascii(self):
        with pytest.raises(errors.BleProtocolError, match="not ASCII"):
            session_mod.parse_software_revision(b"4.\xff.0")


# --- Connecting -----------------------------------------------------------------


class TestConnect:
    def test_key_exchange_in_the_clear_then_encrypted_model_get(self):
        lock = FakeLock()

        async def scenario():
            transport = lock.connect(require_login=False)
            async with new_session(transport) as session:
                assert session.connected
                assert session.firmware == (4, 8, 0)
                assert session.model is const.LockModelId.NIMLY_PRO_24
                return transport, session.link_keys

        transport, link = run(scenario())
        assert link == expected_link_keys()
        # ExchangeKeyPubM, ref 1, unencrypted blob of 68 bytes.
        pub_m = commands.exchange_key_pub_m(public_key(PHONE_LINK_PRIVATE_KEY)).with_ref(1).to_bytes()
        assert transport.writes[:5] == blob_packets(pub_m, encrypted=False)
        # DeviceModelGet, ref 2, encrypted as one 16-byte block from the link IV.
        model_get = bytes.fromhex("62 00 02 00")
        assert transport.writes[5:] == blob_packets(aes_cbc(link.key, link.iv, model_get), encrypted=True)
        assert transport.closed

    def test_executed_cavs_link_keys(self):
        """Replays the key exchange vector the app's own classes printed (crypto_vectors)."""
        v = crypto_vectors
        lock = FakeLock(
            link_override=(v.CAVS_PEER_PUBLIC_KEY_WIRE, crypto.LinkKeys(v.CAVS_LINK_KEY, v.CAVS_LINK_IV)),
        )

        async def scenario():
            session = new_session(lock.connect(require_login=False), key_pair_factory=key_pairs(v.CAVS_PRIVATE_KEY_WIRE))
            async with session:
                batt = await session.request(commands.batt_info_get(), responses.parse_batt_info)
                return session.link_keys, batt

        link, batt = run(scenario())
        assert (link.key, link.iv) == (v.CAVS_LINK_KEY, v.CAVS_LINK_IV)
        assert batt == responses.BattInfo(5800, False, 80)

    def test_old_firmware_uses_the_static_ref_and_skips_the_model(self):
        lock = FakeLock(firmware=b"4.7.89")

        async def scenario():
            async with new_session(lock.connect(require_login=False)) as session:
                assert session.model is None
                assert session.firmware == (4, 7, 89)
                await session.send(commands.current_time_set(1000))

        run(scenario())
        assert [c.command_id for c in lock.commands] == [CommandId.EXCHANGE_KEY_PUB_M, CommandId.CURRENT_TIME_SET]
        assert {c.command_ref for c in lock.commands} == {const.COMMAND_REF_STATIC}

    def test_firmware_below_the_floor_is_refused(self):
        lock = FakeLock(firmware=b"4.5.9")
        transport = lock.connect(require_login=False)
        with pytest.raises(errors.BleFirmwareTooOldError) as caught:
            run(new_session(transport).connect())
        assert caught.value.firmware == (4, 5, 9)
        assert transport.closed
        assert transport.writes == []

    def test_malformed_revision_closes_the_transport(self):
        transport = FakeLock(firmware=b"garbage").connect()
        with pytest.raises(errors.BleProtocolError):
            run(new_session(transport).connect())
        assert transport.closed

    def test_failed_key_exchange_closes_the_transport(self):
        transport = open_transport()
        transport.status_overrides[CommandId.EXCHANGE_KEY_PUB_M] = Status.FAILED
        with pytest.raises(errors.BleFailedError):
            run(new_session(transport).connect())
        assert transport.closed

    def test_connects_once(self):
        async def scenario():
            session = new_session(open_transport())
            await session.connect()
            with pytest.raises(errors.BleSessionStateError, match="connects once"):
                await session.connect()
            await session.close()

        run(scenario())

    def test_state_before_connect(self):
        session = new_session(open_transport())
        assert not session.connected
        assert session.model is None
        with pytest.raises(errors.BleSessionStateError, match="connect"):
            session.firmware  # noqa: B018
        with pytest.raises(errors.BleSessionStateError, match="connect"):
            session.link_keys  # noqa: B018
        with pytest.raises(errors.BleSessionStateError, match="connect"):
            run(session.send(commands.batt_info_get()))
        assert "NEW" in repr(session)

    def test_send_while_connecting_is_a_bug(self):
        lock = FakeLock()
        early: list[asyncio.Task] = []

        async def scenario():
            session = None
            fixed = key_pairs(PHONE_LINK_PRIVATE_KEY)

            def factory():
                # Runs inside connect(), between subscribing and the exchange.
                early.append(asyncio.get_running_loop().create_task(session.send(commands.batt_info_get())))
                return fixed()

            session = new_session(lock.connect(require_login=False), key_pair_factory=factory)
            async with session:
                with pytest.raises(errors.BleSessionStateError, match="still connecting"):
                    await early[0]

        run(scenario())

    def test_a_command_is_never_framed_in_the_clear(self):
        """Without the link cipher PacketStream frames plaintext, so only the key exchange may.

        A PinCodeSet framed that way would put the PIN on the air in the
        clear, so _exchange refuses every other command instead.
        """

        async def scenario():
            lock = FakeLock()
            session = new_session(lock.connect(require_login=False))
            async with session:
                session._stream.cipher = None  # noqa: SLF001
                with pytest.raises(errors.BleSessionStateError, match="key exchange"):
                    await session.send(commands.batt_info_get())

        run(scenario())

    def test_close_is_idempotent(self):
        transport = open_transport()

        async def scenario():
            session = new_session(transport)
            await session.connect()
            await session.close()
            await session.close()
            with pytest.raises(errors.BleDisconnectedError, match="closed"):
                await session.send(commands.batt_info_get())

        run(scenario())
        assert transport.close_calls == 2


# --- Commands and answers -------------------------------------------------------


class TestCommands:
    def test_request_parses_the_answer(self):
        async def scenario():
            async with new_session(open_transport()) as session:
                return await session.request(commands.batt_info_get(), responses.parse_batt_info)

        assert run(scenario()) == responses.BattInfo(5800, False, 80)

    def test_every_encrypted_command_is_one_cbc_run_from_the_link_iv(self):
        lock = FakeLock()

        async def scenario():
            transport = lock.connect(require_login=False)
            async with new_session(transport) as session:
                await session.send(commands.batt_info_get())
                await session.send(commands.batt_info_get())
            return transport

        transport = run(scenario())
        link = expected_link_keys()
        # Writes 5-6 are DeviceModelGet; then ref 3 and ref 4, each encrypted on its own.
        for ref, writes in ((3, transport.writes[7:9]), (4, transport.writes[9:11])):
            plain = bytes([0x5D, 0x00, ref, 0x00])
            assert writes == blob_packets(aes_cbc(link.key, link.iv, plain), encrypted=True)

    def test_refs_count_up_from_one(self):
        lock = FakeLock()

        async def scenario():
            async with new_session(lock.connect(require_login=False)) as session:
                for _ in range(3):
                    await session.send(commands.batt_info_get())

        run(scenario())
        assert [c.command_ref for c in lock.commands] == [1, 2, 3, 4, 5]

    def test_long_command_goes_as_an_encrypted_blob_and_decrypts_whole(self):
        """A 68-byte command: 80 bytes of ciphertext over 6 packets, decrypted in one piece by the lock."""
        lock = FakeLock()

        async def scenario():
            transport = lock.connect(require_login=False)
            async with new_session(transport) as session:
                await session.send(commands.server_key_update(bytes(range(64))))
            return transport

        transport = run(scenario())
        blob = transport.writes[7:]
        assert len(blob) == 6
        assert blob[0][4] == const.BLOB_FLAG_ENCRYPTED
        assert int.from_bytes(blob[0][5:7], "little") == 80
        assert lock.server_public_key == bytes(range(64))

    def test_decrypted_answer_is_cut_to_its_header_length(self):
        """The lock's answer arrives padded to 16 bytes; only the declared payload is read."""
        async def scenario():
            async with new_session(open_transport()) as session:
                return await session.send(commands.batt_info_get())

        answer = run(scenario())
        assert answer.payload == BATT_INFO_PAYLOAD
        assert answer.response_id is ResponseId.BATT_INFO_GET

    def test_answer_before_the_last_write_still_counts(self):
        lock = FakeLock()

        async def scenario():
            transport = lock.connect(deliver_inline=True, require_login=False)
            async with new_session(transport) as session:
                return await session.request(commands.batt_info_get(), responses.parse_batt_info)

        assert run(scenario()).percent == 80

    def test_pause_between_commands(self):
        lock = FakeLock()

        async def scenario():
            transport = lock.connect(require_login=False)
            async with new_session(transport, command_delay=0.05) as session:
                await session.send(commands.batt_info_get())
            return transport

        transport = run(scenario())
        # Last write of DeviceModelGet, then the first of BattInfoGet.
        assert transport.write_times[7] - transport.write_times[6] >= 0.05

    @pytest.mark.parametrize("status_id", list(errors.STATUS_ERRORS))
    def test_status_maps_to_its_error(self, status_id):
        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                transport.status_overrides[CommandId.PIN_CODE_SET] = status_id
                await session.send(commands.pin_code_set(803, "8832"))

        with pytest.raises(errors.STATUS_ERRORS[status_id]) as caught:
            run(scenario())
        assert caught.value.status is status_id
        assert caught.value.command is ResponseId.PIN_CODE_SET
        assert "8832" not in str(caught.value)

    def test_unknown_status_is_the_base_error(self):
        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                transport.status_overrides[CommandId.BATT_INFO_GET] = 0x42
                await session.send(commands.batt_info_get())

        with pytest.raises(errors.BleOperationError) as caught:
            run(scenario())
        assert type(caught.value) is errors.BleOperationError
        assert caught.value.status == 0x42

    def test_the_session_survives_a_failed_status(self):
        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                transport.status_overrides[CommandId.PIN_CODE_SET] = Status.SECURITY_ERROR
                with pytest.raises(errors.BleSecurityError):
                    await session.send(commands.pin_code_set(803, "8832"))
                del transport.status_overrides[CommandId.PIN_CODE_SET]
                return await session.request(commands.batt_info_get(), responses.parse_batt_info)

        assert run(scenario()).level == 5800

    def test_right_ref_wrong_response_is_a_protocol_error(self):
        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                transport.silent.add(CommandId.BATT_INFO_GET)
                task = asyncio.create_task(session.send(commands.batt_info_get()))
                await asyncio.sleep(0)
                transport.send_response(response_mod.Response(ResponseId.VOLUME_SET, 3, Status.SUCCESS))
                await task

        with pytest.raises(errors.BleProtocolError, match="BATT_INFO_GET was answered by VOLUME_SET"):
            run(scenario())

    def test_unknown_response_id_with_the_right_ref(self):
        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                transport.silent.add(CommandId.BATT_INFO_GET)
                task = asyncio.create_task(session.send(commands.batt_info_get()))
                await asyncio.sleep(0)
                transport.send_response(response_mod.Response(0x99, 3, Status.SUCCESS))
                await task

        with pytest.raises(errors.BleProtocolError, match="unknown response 0x99"):
            run(scenario())

    def test_answers_to_other_refs_are_ignored(self, caplog):
        caplog.set_level(logging.DEBUG)

        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                transport.events_before_answer[CommandId.BATT_INFO_GET] = [
                    response_mod.Response(ResponseId.BATT_INFO_GET, 77, Status.FAILED),
                ]
                return await session.request(commands.batt_info_get(), responses.parse_batt_info)

        assert run(scenario()).percent == 80
        assert "CommandRef 77 that no command is waiting for" in caplog.text

    def test_status_packets_are_ignored(self, caplog):
        caplog.set_level(logging.DEBUG)

        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                transport.notify(packet.Packet(const.PacketTypeId.ACK, 1).to_bytes())
                await asyncio.sleep(0)
                return await session.request(commands.batt_info_get(), responses.parse_batt_info)

        assert run(scenario()).percent == 80
        assert "Ignoring a packet of type ACK" in caplog.text


# --- The app's firmware and model gates ---------------------------------------------


class TestAppGates:
    def test_an_admin_command_below_4_7_90_is_refused_before_anything_is_sent(self):
        lock = FakeLock(firmware=b"4.7.89")

        async def scenario():
            async with new_session(lock.connect(require_login=False)) as session:
                assert session.availability(commands.pin_code_set(803, "8832")) is const.DeviceFeature.UNAVAILABLE_VERSION
                await session.send(commands.pin_code_set(803, "8832"))

        with pytest.raises(errors.BleFeatureUnavailableError) as caught:
            run(scenario())
        assert caught.value.feature is const.DeviceFeature.UNAVAILABLE_VERSION
        assert caught.value.firmware == (4, 7, 89)
        assert caught.value.model is None
        assert "8832" not in str(caught.value)
        assert [c.command_id for c in lock.commands] == [CommandId.EXCHANGE_KEY_PUB_M]

    def test_a_feature_the_model_lacks_is_refused(self):
        lock = FakeLock(model=const.LockModelId.NIMLY_CODE)

        async def scenario():
            async with new_session(lock.connect(require_login=False)) as session:
                await session.request(commands.fingerprint_scan(150), responses.parse_fingerprint_scan)

        with pytest.raises(errors.BleFeatureUnavailableError) as caught:
            run(scenario())
        assert caught.value.feature is const.DeviceFeature.UNAVAILABLE
        assert caught.value.model is const.LockModelId.NIMLY_CODE
        assert CommandId.FINGERPRINT_SCAN not in [c.command_id for c in lock.commands]

    def test_skip_app_gates_sends_it_anyway_and_says_so(self, caplog):
        lock = FakeLock(firmware=b"4.7.89")

        async def scenario():
            async with new_session(lock.connect(require_login=False)) as session:
                await session.send(commands.pin_code_set(803, "8832"), skip_app_gates=True)
                return await session.request(commands.batt_info_get(), responses.parse_batt_info, skip_app_gates=True)

        assert run(scenario()).percent == 80
        assert lock.pins == {803: "8832"}
        assert "Sending PIN_CODE_SET past the app's gate (UNAVAILABLE_VERSION)" in caplog.text
        assert "8832" not in caplog.text

    def test_available_commands_log_nothing(self, caplog):
        async def scenario():
            async with new_session(open_transport()) as session:
                assert session.availability(commands.batt_info_get()) is const.DeviceFeature.AVAILABLE
                await session.send(commands.batt_info_get(), skip_app_gates=True)

        run(scenario())
        assert "past the app's gate" not in caplog.text

    def test_availability_needs_a_connected_session(self):
        session = new_session(open_transport())
        with pytest.raises(errors.BleSessionStateError, match="connect"):
            session.availability(commands.batt_info_get())


# --- Events on CommandRef 128 --------------------------------------------------------


LOCK_STATUS_EVENT = response_mod.Response.from_bytes(vectors.LOCK_STATUS_SLOT_803_UNLOCKED_PANEL_RESPONSE)
USER_ADDED_EVENT = response_mod.Response.from_bytes(vectors.USER_ADDED_SLOT_151_FINGERPRINT_RESPONSE)


class TestEvents:
    def test_event_before_the_answer_goes_to_listeners_and_leaves_the_command_alone(self):
        seen = []

        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                session.add_event_listener(seen.append)
                transport.events_before_answer[CommandId.BATT_INFO_GET] = [LOCK_STATUS_EVENT, USER_ADDED_EVENT]
                return await session.request(commands.batt_info_get(), responses.parse_batt_info)

        assert run(scenario()).percent == 80
        assert seen == [
            responses.LockStatus(803, const.LockStateId.UNLOCKED, const.DoorlockMethodId.PANEL),
            responses.UserAdded(151, const.UserAddedStatusId.FINGERPRINT),
        ]

    def test_event_with_the_pending_response_id_is_still_an_event(self):
        """Ref 128 wins over the id: a LockStatus-shaped answer never completes a command."""
        seen = []

        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                session.add_event_listener(seen.append)
                transport.events_before_answer[CommandId.BATT_INFO_GET] = [
                    response_mod.Response(ResponseId.BATT_INFO_GET, response_mod.EVENT_COMMAND_REF, 0, b"\x00" * 4)
                ]
                return await session.request(commands.batt_info_get(), responses.parse_batt_info)

        assert run(scenario()).level == 5800
        assert seen == []

    def test_events_with_no_command_in_flight(self):
        seen = []

        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                session.add_event_listener(seen.append)
                transport.send_response(LOCK_STATUS_EVENT)
                await asyncio.sleep(0.01)

        run(scenario())
        assert len(seen) == 1

    def test_removed_listener_hears_nothing(self):
        seen = []

        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                remove = session.add_event_listener(seen.append)
                remove()
                transport.send_response(LOCK_STATUS_EVENT)
                await asyncio.sleep(0.01)

        run(scenario())
        assert seen == []

    def test_removing_twice_leaves_the_same_listener_added_again(self):
        # The remover is idempotent: the second call must not take out the
        # other registration of the same function.
        seen = []

        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                remove = session.add_event_listener(seen.append)
                session.add_event_listener(seen.append)
                remove()
                remove()
                transport.send_response(LOCK_STATUS_EVENT)
                await asyncio.sleep(0.01)

        run(scenario())
        assert len(seen) == 1

    def test_a_failing_listener_does_not_stop_the_others(self, caplog):
        seen = []

        def broken(event):
            raise RuntimeError("listener bug near 8832")

        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                session.add_event_listener(broken)
                session.add_event_listener(seen.append)
                transport.send_response(LOCK_STATUS_EVENT)
                await asyncio.sleep(0.01)

        run(scenario())
        assert len(seen) == 1
        assert "A lock event listener failed with RuntimeError" in caplog.text
        assert "8832" not in caplog.text
        assert all(record.exc_info is None for record in caplog.records)

    def test_other_events_are_ignored(self, caplog):
        caplog.set_level(logging.DEBUG)
        seen = []

        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                session.add_event_listener(seen.append)
                transport.send_response(
                    response_mod.Response(ResponseId.VOLUME_SET, response_mod.EVENT_COMMAND_REF, 0)
                )
                await asyncio.sleep(0.01)

        run(scenario())
        assert seen == []
        assert "Ignoring event VOLUME_SET" in caplog.text

    def test_malformed_event_is_dropped(self, caplog):
        seen = []

        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                session.add_event_listener(seen.append)
                # LockStateId 9 does not exist.
                transport.send_response(
                    response_mod.Response(ResponseId.LOCK_STATUS, response_mod.EVENT_COMMAND_REF, 0, b"\x23\x03\x09\x02")
                )
                await asyncio.sleep(0.01)
                return await session.request(commands.batt_info_get(), responses.parse_batt_info)

        assert run(scenario()).percent == 80
        assert seen == []
        assert "Unknown LockStateId value 9" in caplog.text


# --- Timeouts, drops and disconnects ------------------------------------------------


class TestFailures:
    def test_timeout_then_the_next_command_gets_a_new_ref(self):
        lock = FakeLock()

        async def scenario():
            transport = lock.connect(require_login=False)
            async with new_session(transport, response_timeout=0.05) as session:
                transport.silent.add(CommandId.PIN_CODE_CLEAR)
                with pytest.raises(errors.BleTimeoutError, match=r"PIN_CODE_CLEAR got no answer within 0.05 s"):
                    await session.send(commands.pin_code_clear(803))
                return await session.request(commands.batt_info_get(), responses.parse_batt_info)

        assert run(scenario()).percent == 80
        assert [c.command_ref for c in lock.commands][-2:] == [3, 4]

    def test_counter_firmware_does_not_hold_back_after_a_timeout(self):
        """A late answer there carries an old ref, so there is nothing to wait out."""

        async def scenario():
            transport = open_transport()
            async with new_session(transport, response_timeout=0.05, late_answer_grace=10.0) as session:
                transport.silent.add(CommandId.PIN_CODE_CLEAR)
                with pytest.raises(errors.BleTimeoutError):
                    await session.send(commands.pin_code_clear(803))
                loop = asyncio.get_running_loop()
                started = loop.time()
                await session.send(commands.batt_info_get())
                return loop.time() - started

        assert run(scenario()) < 1.0

    def test_timeout_names_a_dropped_frame_as_its_cause(self, caplog):
        async def scenario():
            transport = open_transport()
            async with new_session(transport, response_timeout=0.05) as session:
                transport.silent.add(CommandId.BATT_INFO_GET)
                task = asyncio.create_task(session.send(commands.batt_info_get()))
                await asyncio.sleep(0)
                # An encrypted single packet whose payload is not whole AES blocks.
                transport.notify(packet.Packet(const.PacketTypeId.SINGLE_ENCRYPTED, 1, b"\x01\x02\x03").to_bytes())
                await task

        with pytest.raises(errors.BleTimeoutError) as caught:
            run(scenario())
        assert isinstance(caught.value.__cause__, errors.BleProtocolError)
        assert "Dropped a malformed notification" in caplog.text

    def test_undecodable_packet_is_dropped(self, caplog):
        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                transport.notify(b"\xee\x00\x00\x01")
                await asyncio.sleep(0)
                return await session.request(commands.batt_info_get(), responses.parse_batt_info)

        assert run(scenario()).percent == 80
        assert "Unknown packet type 0xEE" in caplog.text

    def test_short_response_is_dropped(self, caplog):
        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                # Decrypts to 16 bytes, but the Layer 3 header claims a payload
                # longer than what is left.
                link = session.link_keys
                garbage = aes_cbc(link.key, link.iv, bytes([0x5D, 0x40, 0x09, 0x00]))
                for frame in packet.packetize(garbage, encrypted=True):
                    transport.notify(frame.to_bytes())
                await asyncio.sleep(0.01)
                return await session.request(commands.batt_info_get(), responses.parse_batt_info)

        assert run(scenario()).percent == 80
        assert "Tried to read 64 byte" in caplog.text

    def test_disconnect_fails_the_command_in_flight_and_every_later_one(self):
        async def scenario():
            transport = open_transport()
            session = new_session(transport)
            await session.connect()
            transport.silent.add(CommandId.BATT_INFO_GET)
            first = asyncio.create_task(session.send(commands.batt_info_get()))
            second = asyncio.create_task(session.send(commands.batt_info_get()))
            await asyncio.sleep(0.01)
            transport.drop_link()
            transport.drop_link()  # a second report changes nothing
            with pytest.raises(errors.BleDisconnectedError, match="disconnected before it answered"):
                await first
            with pytest.raises(errors.BleDisconnectedError, match="closed"):
                await second
            assert not session.connected
            with pytest.raises(errors.BleDisconnectedError):
                await session.send(commands.batt_info_get())
            await session.close()

        run(scenario())

    @pytest.mark.parametrize("ending", ["drop_link", "close"])
    def test_link_lost_during_the_pause_fails_before_writing(self, ending):
        """A transport that writes into a dead link without raising is not waited out."""

        async def scenario():
            transport = open_transport()
            session = new_session(transport, command_delay=0.05, response_timeout=5.0)
            await session.connect()

            async def swallow(data):
                transport.writes.append(data)

            transport.write = swallow
            writes_before = len(transport.writes)
            task = asyncio.create_task(session.send(commands.batt_info_get()))
            await asyncio.sleep(0.01)
            if ending == "drop_link":
                transport.drop_link()
            else:
                await session.close()
            loop = asyncio.get_running_loop()
            started = loop.time()
            with pytest.raises(errors.BleDisconnectedError, match="closed"):
                await task
            return loop.time() - started, len(transport.writes) - writes_before

        waited, writes = run(scenario())
        assert waited < 1.0
        assert writes == 0

    def test_disconnect_during_the_writes(self):
        """The link drops between two packets of a blob; the error surfaces once, cleanly."""

        async def scenario():
            transport = open_transport()
            session = new_session(transport)
            await session.connect()
            original = transport.write

            async def write_then_drop(data):
                await original(data)
                if not transport.closed:
                    transport.drop_link()

            transport.write = write_then_drop
            await session.send(commands.batt_info_get())

        with pytest.raises(errors.BleDisconnectedError, match="Fake link is closed"):
            run(scenario())

    def test_write_error_that_is_not_our_timeout_passes_through(self):
        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                transport.write_error = errors.BleTimeoutError("radio write timed out")
                await session.send(commands.batt_info_get())

        with pytest.raises(errors.BleTimeoutError, match="radio write timed out"):
            run(scenario())

    def test_cancelling_a_command(self):
        async def scenario():
            transport = open_transport()
            async with new_session(transport) as session:
                transport.silent.add(CommandId.BATT_INFO_GET)
                task = asyncio.create_task(session.send(commands.batt_info_get()))
                await asyncio.sleep(0.01)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                transport.silent.clear()
                return await session.request(commands.batt_info_get(), responses.parse_batt_info)

        assert run(scenario()).percent == 80


STATIC_FIRMWARE = b"4.7.89"


class TestLateAnswersUnderTheStaticRef:
    """Firmware below 4.7.90 puts CommandRef 16 on every command."""

    def test_the_next_command_holds_back_and_a_late_answer_meanwhile_is_dropped(self, caplog):
        caplog.set_level(logging.DEBUG)
        lock = FakeLock(firmware=STATIC_FIRMWARE)

        async def scenario():
            transport = lock.connect(require_login=False)
            async with new_session(transport, response_timeout=0.05, late_answer_grace=0.2) as session:
                transport.silent.add(CommandId.DEVICE_NAME_SET)
                with pytest.raises(errors.BleTimeoutError):
                    await session.send(commands.device_name_set("Door"))
                loop = asyncio.get_running_loop()
                timed_out = loop.time()
                # The lock's answer to the timed-out command, late, and a failure.
                late = response_mod.Response(ResponseId.DEVICE_NAME_SET, const.COMMAND_REF_STATIC, Status.FAILED)
                loop.call_later(0.1, transport.send_response, late)
                transport.silent.clear()
                await session.send(commands.device_name_set("Hall"))
                return transport.write_times[-1] - timed_out

        held_back = run(scenario())
        assert held_back >= 0.2
        assert lock.name == "Hall"
        assert "Ignoring DEVICE_NAME_SET with CommandRef 16 that no command is waiting for" in caplog.text

    def test_a_late_answer_with_another_id_does_not_complete_the_next_command(self, caplog):
        caplog.set_level(logging.DEBUG)
        lock = FakeLock(firmware=STATIC_FIRMWARE)

        async def scenario():
            transport = lock.connect(require_login=False)
            async with new_session(transport, response_timeout=0.05, late_answer_grace=0) as session:
                transport.silent.add(CommandId.CURRENT_TIME_SET)
                with pytest.raises(errors.BleTimeoutError):
                    await session.send(commands.current_time_set(1000))
                transport.silent.clear()
                # The late failure lands while DeviceNameSet waits, before its own answer.
                transport.events_before_answer[CommandId.DEVICE_NAME_SET] = [
                    response_mod.Response(ResponseId.CURRENT_TIME_SET, const.COMMAND_REF_STATIC, Status.FAILED),
                ]
                await session.send(commands.device_name_set("Hall"))

        run(scenario())
        assert lock.name == "Hall"
        assert "CURRENT_TIME_SET arrived under the static CommandRef while DEVICE_NAME_SET waited" in caplog.text

    def test_a_timeout_names_the_ignored_late_answer_as_its_cause(self):
        lock = FakeLock(firmware=STATIC_FIRMWARE)

        async def scenario():
            transport = lock.connect(require_login=False)
            async with new_session(transport, response_timeout=0.05) as session:
                transport.silent.add(CommandId.DEVICE_NAME_SET)
                task = asyncio.create_task(session.send(commands.device_name_set("Hall")))
                await asyncio.sleep(0)
                transport.send_response(
                    response_mod.Response(ResponseId.CURRENT_TIME_SET, const.COMMAND_REF_STATIC, Status.SUCCESS)
                )
                await task

        with pytest.raises(errors.BleTimeoutError) as caught:
            run(scenario())
        assert isinstance(caught.value.__cause__, errors.BleProtocolError)
        assert "late answer to an earlier command" in str(caught.value.__cause__)

    def test_what_is_left_a_late_answer_with_the_same_id_after_the_grace(self):
        """The known limit: nothing on the wire tells this answer from the right one."""
        lock = FakeLock(firmware=STATIC_FIRMWARE)

        async def scenario():
            transport = lock.connect(require_login=False)
            async with new_session(transport, response_timeout=0.05, late_answer_grace=0) as session:
                transport.silent.add(CommandId.DEVICE_NAME_SET)
                with pytest.raises(errors.BleTimeoutError):
                    await session.send(commands.device_name_set("Door"))
                transport.silent.clear()
                transport.events_before_answer[CommandId.DEVICE_NAME_SET] = [
                    response_mod.Response(ResponseId.DEVICE_NAME_SET, const.COMMAND_REF_STATIC, Status.FAILED),
                ]
                await session.send(commands.device_name_set("Hall"))

        # The lock took the name, but the late FAILED completed the command.
        with pytest.raises(errors.BleFailedError):
            run(scenario())
        assert lock.name == "Hall"


# --- Nothing secret leaves through logs or reprs --------------------------------------

_SECRET_WORDS = {"key", "keys", "pin", "code", "secret", "challenge", "answer", "payload", "data", "frame", "frames"}


def _logger_calls(path):
    """Every _LOGGER.<level>(...) call in one module."""
    for node in ast.walk(ast.parse(path.read_text())):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "_LOGGER"
        ):
            yield node


def test_ble_log_calls_pass_no_secret_shaped_values():
    """Log calls in ble/ may pass ids, names and errors, never keys, PINs or raw bytes.

    Error messages in ble/ are built from sizes and ids only (tests for each
    module check that), so passing an exception is fine. The walk is
    recursive, and the count keeps it honest: a flat glob, and a path that
    pointed nowhere after the tests moved, both once let it pass on nothing.
    """
    offenders = []
    seen = 0
    for path in sorted(BLE_DIR.rglob("*.py")):
        for node in _logger_calls(path):
            seen += 1
            for arg in node.args[1:] + [kw.value for kw in node.keywords]:
                for sub in ast.walk(arg):
                    name = sub.id if isinstance(sub, ast.Name) else sub.attr if isinstance(sub, ast.Attribute) else None
                    if name and set(name.lower().strip("_").split("_")) & _SECRET_WORDS:
                        offenders.append(f"{path.relative_to(BLE_DIR)}:{node.lineno} passes {name}")
    assert seen, "the walk found no _LOGGER call in ble/, so it checked nothing"
    assert not offenders, offenders


def test_ble_logs_only_through_module_loggers_named_logger():
    """The guard above reads _LOGGER calls, so every logger in ble/ must be one.

    A logger bound to another name, or a call on the logging module itself,
    would be invisible to it.
    """
    strays = []
    for path in sorted(BLE_DIR.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                func = node.value.func
                if isinstance(func, ast.Attribute) and func.attr == "getLogger":
                    targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                    if targets != ["_LOGGER"]:
                        strays.append(f"{path.relative_to(BLE_DIR)}:{node.lineno} binds a logger to {targets}")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logging"
                and node.func.attr != "getLogger"
            ):
                strays.append(f"{path.relative_to(BLE_DIR)}:{node.lineno} logs through logging.{node.func.attr}")
    assert not strays, strays


def test_session_repr_shows_state_only():
    async def scenario():
        async with new_session(open_transport()) as session:
            return repr(session), session.link_keys

    text, link = run(scenario())
    assert text == "Session(state=CONNECTED, firmware=(4, 8, 0))"
    assert link.key.hex() not in text

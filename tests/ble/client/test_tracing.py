"""The Session's tracer hook: every frame out and in, every command, answer and drop.

The lock is tests/ble/fake_lock.py, and what the tracer is handed is compared
with what the fake lock saw on its side of the link, not with the session's
own bookkeeping.
"""
from __future__ import annotations

import asyncio
import importlib

from ...conftest import PACKAGE, load_component_module
from ..fake_lock import PHONE_LINK_PRIVATE_KEY, FakeLock, key_pairs

const = load_component_module("ble.protocol.const")
commands = load_component_module("ble.protocol.commands")
errors = load_component_module("ble.errors")
packet = load_component_module("ble.protocol.packet")
response_mod = load_component_module("ble.protocol.response")
responses = load_component_module("ble.protocol.responses")
session_mod = load_component_module("ble.client.session")
tracing = load_component_module("ble.client.tracing")

CommandId = const.CommandId
ResponseId = const.ResponseId


def run(coro):
    return asyncio.run(coro)


class RecordingTracer:
    """Keeps every call in order as (event, argument...)."""

    def __init__(self):
        self.events = []

    def packet_out(self, data):
        self.events.append(("packet_out", data))

    def packet_in(self, data):
        self.events.append(("packet_in", data))

    def command(self, command):
        self.events.append(("command", command))

    def response(self, response):
        self.events.append(("response", response))

    def dropped(self, error, data):
        self.events.append(("dropped", error, data))

    def of(self, kind):
        return [event[1:] if kind == "dropped" else event[1] for event in self.events if event[0] == kind]


def open_transport():
    transport = FakeLock().connect(require_login=False)
    # Record what the lock sends, on its side of the link.
    sent = []
    notify = transport.notify

    def recording_notify(data):
        sent.append(data)
        notify(data)

    transport.notify = recording_notify
    transport.sent = sent
    return transport


def new_session(transport, tracer):
    return session_mod.Session(
        transport,
        command_delay=0,
        response_timeout=1.0,
        key_pair_factory=key_pairs(PHONE_LINK_PRIVATE_KEY),
        tracer=tracer,
    )


def test_traces_every_packet_command_and_answer():
    tracer = RecordingTracer()
    transport = open_transport()

    async def scenario():
        async with new_session(transport, tracer) as session:
            await session.request(commands.batt_info_get(), responses.parse_batt_info)

    run(scenario())
    assert tracer.of("packet_out") == transport.writes
    assert tracer.of("packet_in") == transport.sent
    # The same commands the lock decrypted, refs and payloads included.
    assert tracer.of("command") == transport.commands
    assert [r.response_id for r in tracer.of("response")] == [
        ResponseId.EXCHANGE_KEY_PUB_L,
        ResponseId.DEVICE_MODEL_GET,
        ResponseId.BATT_INFO_GET,
    ]
    assert tracer.of("dropped") == []


def test_a_command_is_traced_before_its_packets_and_answered_after_them():
    tracer = RecordingTracer()

    async def scenario():
        async with new_session(open_transport(), tracer):
            pass

    run(scenario())
    kinds = [event[0] for event in tracer.events]
    # ExchangeKeyPubM (64-byte key) is a blob: several packets each way.
    first_answer = kinds.index("response")
    assert kinds[0] == "command"
    assert set(kinds[1 : kinds.index("packet_in")]) == {"packet_out"}
    assert kinds.count("packet_out") > 1
    assert set(kinds[kinds.index("packet_in") : first_answer]) == {"packet_in"}
    assert kinds[first_answer + 1] == "command"


def test_events_are_traced_as_responses():
    tracer = RecordingTracer()
    event = response_mod.Response(ResponseId.LOCK_STATUS, response_mod.EVENT_COMMAND_REF, 0, b"\x23\x03\x01\x02")

    async def scenario():
        transport = open_transport()
        async with new_session(transport, tracer):
            transport.send_response(event)
            await asyncio.sleep(0.01)

    run(scenario())
    assert tracer.of("response")[-1] == event


class TestDropped:
    def test_a_packet_that_does_not_frame_is_handed_over_as_received(self):
        tracer = RecordingTracer()

        async def scenario():
            transport = open_transport()
            async with new_session(transport, tracer):
                transport.notify(b"\xee\x00\x00\x01")
                await asyncio.sleep(0.01)

        run(scenario())
        [(error, data)] = tracer.of("dropped")
        assert isinstance(error, errors.BleProtocolError)
        assert data == b"\xee\x00\x00\x01"
        assert tracer.of("packet_in")[-1] == data

    def test_a_response_that_does_not_parse_is_handed_over_decrypted(self):
        tracer = RecordingTracer()

        async def scenario():
            transport = open_transport()
            async with new_session(transport, tracer) as session:
                cipher = session.link_keys.cipher()
                # The Layer 3 header claims more payload than the 16 bytes carry.
                for frame in packet.packetize(cipher.encrypt(b"\x5d\x40\x09\x00"), encrypted=True):
                    transport.notify(frame.to_bytes())
                await asyncio.sleep(0.01)

        run(scenario())
        [(error, data)] = tracer.of("dropped")
        assert "Tried to read 64 byte" in str(error)
        assert data == b"\x5d\x40\x09\x00" + bytes(12)

    def test_an_event_that_does_not_parse_is_handed_over_as_its_response_bytes(self):
        tracer = RecordingTracer()
        # LockStateId 9 does not exist.
        event = response_mod.Response(ResponseId.LOCK_STATUS, response_mod.EVENT_COMMAND_REF, 0, b"\x23\x03\x09\x02")

        async def scenario():
            transport = open_transport()
            async with new_session(transport, tracer):
                transport.send_response(event)
                await asyncio.sleep(0.01)

        run(scenario())
        [(error, data)] = tracer.of("dropped")
        assert "Unknown LockStateId value 9" in str(error)
        assert data == event.to_bytes()
        assert tracer.of("response")[-1] == event


class BrokenTracer:
    """Raises from every hook, quoting something that must not reach the log."""

    def _fail(self, *args):
        raise RuntimeError("tracer bug near 8832")

    packet_out = packet_in = command = response = dropped = _fail


def test_a_failing_tracer_does_not_break_the_session(caplog):
    async def scenario():
        transport = open_transport()
        async with new_session(transport, BrokenTracer()) as session:
            transport.notify(b"\xee\x00\x00\x01")
            await asyncio.sleep(0.01)
            return await session.request(commands.batt_info_get(), responses.parse_batt_info)

    assert run(scenario()).percent == 80
    for event in ("packet_out", "packet_in", "command", "response", "dropped"):
        assert f"The session tracer failed on {event} with RuntimeError" in caplog.text
    assert "8832" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_without_a_tracer_every_hook_is_a_no_op():
    tracer = tracing.guarded_tracer(None)
    tracer.packet_out(b"\x01")
    tracer.packet_in(b"\x01")
    tracer.command(commands.batt_info_get().with_ref(1))
    tracer.response(response_mod.Response(ResponseId.BATT_INFO_GET, 1, 0))
    tracer.dropped(errors.BleProtocolError("x"), b"\x01")


def test_a_recording_tracer_satisfies_the_protocol():
    # Structural: nothing to inherit, the five methods are the whole contract.
    assert {name for name in vars(tracing.Tracer) if not name.startswith("_")} == {
        "packet_out",
        "packet_in",
        "command",
        "response",
        "dropped",
    }
    assert importlib.import_module(f"{PACKAGE}.ble").Tracer is tracing.Tracer

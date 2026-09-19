"""BleakTransport: the Transport over a connected bleak client.

The client is FakeBleakClient from tests/ble/fake_lock.py, which puts the
fake lock behind bleak's shape, and the errors it raises are bleak's own
classes. One test runs a whole enrollment and a PIN write through Session,
BleakTransport and the fake client, the path the command line tool and Home
Assistant take.

No pytest-asyncio: CI's unit group does not have it, so each test runs its
coroutine through asyncio.run.
"""
from __future__ import annotations

import ast
import asyncio
import functools
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("bleak")

from bleak.exc import BleakCharacteristicNotFoundError, BleakError  # noqa: E402

from ...conftest import COMPONENT_DIR, load_component_module  # noqa: E402
from ..fake_lock import (  # noqa: E402
    DEVICE_INFORMATION_SERVICE_UUID,
    PHONE_LINK_PRIVATE_KEY,
    PHONE_SERVER_PRIVATE_KEY,
    PHONE_UPDATE_PRIVATE_KEY,
    FakeBleakClient,
    FakeLock,
    FakeService,
    FakeServices,
    key_pairs,
)

auth = load_component_module("ble.client.auth")
bleak_transport = load_component_module("ble.client.bleak_transport")
client_const = load_component_module("ble.client.const")
commands = load_component_module("ble.protocol.commands")
const = load_component_module("ble.protocol.const")
enrollment_mod = load_component_module("ble.client.enrollment")
errors = load_component_module("ble.errors")
responses = load_component_module("ble.protocol.responses")
session_mod = load_component_module("ble.client.session")

BleakTransport = bleak_transport.BleakTransport
CommandId = const.CommandId
SOURCE = Path(COMPONENT_DIR).resolve() / "ble" / "client" / "bleak_transport.py"

# Packets the fake lock parses and ignores (ACK), for tests about the write itself.
ACK = bytes([const.PacketTypeId.ACK, 0, 0, 1])
ACK_2 = bytes([const.PacketTypeId.ACK, 0, 0, 2])


def run(coro):
    return asyncio.run(coro)


def connected_client(lock=None, **kwargs):
    kwargs.setdefault("require_login", False)
    return FakeBleakClient(lock or FakeLock(), connected=True, **kwargs)


def wrap(client):
    """A transport on client, its disconnected callback wired as a caller must."""
    transport = BleakTransport(client)
    client._disconnected_callback = transport.client_disconnected
    return transport


def new_session(transport, *private_keys, **kwargs):
    keys = private_keys or (PHONE_LINK_PRIVATE_KEY,)
    return session_mod.Session(
        transport, command_delay=0, response_timeout=1.0, key_pair_factory=key_pairs(*keys), **kwargs
    )


# --- The path the tools take --------------------------------------------------------


class Recorder:
    def __init__(self):
        self.commands = []
        self.packets_out = []

    def packet_out(self, data):
        self.packets_out.append(data)

    def packet_in(self, data):
        pass

    def command(self, command):
        self.commands.append(command.command_id)

    def response(self, response):
        pass

    def dropped(self, error, data):
        pass


def test_enrollment_and_a_pin_end_to_end_through_bleak():
    lock = FakeLock()
    client_class = functools.partial(FakeBleakClient, properties=("read", "write", "notify"))
    tracer = Recorder()
    saved = []

    async def scenario():
        transport = await BleakTransport.connect(lock, client_class=client_class)
        async with new_session(transport, tracer=tracer) as session:
            enrollment = await enrollment_mod.enroll(
                session,
                name="Door",
                save=saved.append,
                device_id=bytes.fromhex("5A 17 C3 09 E4 21"),
                server_private_key=PHONE_SERVER_PRIVATE_KEY,
                now=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
                key_pair_factory=key_pairs(PHONE_UPDATE_PRIVATE_KEY),
            )
        first_client = transport._client

        transport = await BleakTransport.connect(lock, client_class=client_class)
        async with new_session(transport) as session:
            await auth.authenticate_owner(session, enrollment.owner_credential)
            await session.send(commands.pin_code_set(803, "8832"))
        return enrollment, first_client, transport._client

    enrollment, first, second = run(scenario())
    assert enrollment.complete
    assert saved[-1] == enrollment
    assert lock.device_id == bytes.fromhex("5A 17 C3 09 E4 21")
    assert lock.pins == {803: "8832"}
    # Every packet went through bleak as a write with response, and both
    # connections were let go the way close() lets go.
    assert [data for data, _ in first.write_calls] == tracer.packets_out
    assert {response for _, response in first.write_calls + second.write_calls} == {True}
    for client in (first, second):
        assert client.stop_notify_calls == 1
        assert client.disconnect_calls == 1
        assert not client.is_connected
    assert tracer.commands[-1] == CommandId.DEVICE_NAME_SET
    assert lock.commands[-1].command_id == CommandId.PIN_CODE_SET


def test_a_lock_with_another_owner_refuses_the_factory_key_through_bleak():
    # The status the lock answers with travels back through bleak intact.
    lock = FakeLock(owner_key=bytes(range(16)))

    async def scenario():
        transport = await BleakTransport.connect(lock, client_class=FakeBleakClient)
        async with new_session(transport) as session:
            await auth.authenticate_owner(session, auth.DEFAULT_OWNER_CREDENTIAL)

    with pytest.raises(errors.BleSecurityError):
        run(scenario())


# --- Connecting ---------------------------------------------------------------------


class TestConnect:
    def test_passes_the_timeout_and_wires_the_disconnect(self):
        lock = FakeLock()
        disconnected = []

        async def scenario():
            transport = await BleakTransport.connect(lock, timeout=3.5, client_class=FakeBleakClient)
            await transport.start_notify(lambda data: None, lambda: disconnected.append(True))
            transport._client.drop_link()
            return transport._client

        client = run(scenario())
        assert client.timeout == 3.5
        assert disconnected == [True]

    def test_a_timeout_is_a_ble_timeout(self):
        def client_class(*args, **kwargs):
            client = FakeBleakClient(*args, **kwargs)
            client.errors["connect"] = TimeoutError()
            return client

        with pytest.raises(errors.BleTimeoutError, match="timed out after 10 s"):
            run(BleakTransport.connect(FakeLock(), client_class=client_class))

    def test_a_bleak_error_is_a_ble_error(self):
        def client_class(*args, **kwargs):
            client = FakeBleakClient(*args, **kwargs)
            client.errors["connect"] = BleakError("Device with address X was not found")
            return client

        with pytest.raises(errors.BleError, match="Connecting to the lock failed: BleakError: Device with"):
            run(BleakTransport.connect(FakeLock(), client_class=client_class))

    def test_refuses_a_client_that_is_not_connected(self):
        with pytest.raises(errors.BleDisconnectedError, match="not connected"):
            BleakTransport(FakeBleakClient(FakeLock()))

    def test_a_disconnect_before_the_transport_exists_is_not_lost(self):
        # connect() leaves no await between the client connecting and the
        # transport taking over, so the only way to miss a disconnect is a
        # client that is already down, which __init__ refuses.
        def client_class(*args, **kwargs):
            client = FakeBleakClient(*args, **kwargs)
            original = client.connect

            async def connect_then_drop(**kw):
                await original(**kw)
                client.drop_link()

            client.connect = connect_then_drop
            return client

        with pytest.raises(errors.BleDisconnectedError):
            run(BleakTransport.connect(FakeLock(), client_class=client_class))


# --- The Transport methods ----------------------------------------------------------


class TestReadSoftwareRevision:
    def test_returns_bytes(self):
        client = connected_client(FakeLock(firmware=b"4.8.2"))
        value = run(wrap(client).read_software_revision())
        assert value == b"4.8.2"
        assert type(value) is bytes
        # The transport reads that one characteristic and nothing else in the table.
        assert client.read_calls == [client_const.SOFTWARE_REVISION_CHARACTERISTIC_UUID]

    @pytest.mark.parametrize(
        ("error", "expected", "message"),
        [
            (TimeoutError(), errors.BleTimeoutError, "Reading the software revision timed out"),
            (BleakError("ATT error 0x0e"), errors.BleError, "failed: BleakError: ATT error 0x0e"),
            (EOFError(), errors.BleError, "failed: EOFError$"),
            (BrokenPipeError("pipe"), errors.BleError, "failed: BrokenPipeError: pipe"),
        ],
    )
    def test_errors_are_translated(self, error, expected, message):
        client = connected_client()
        client.errors["read_gatt_char"] = error
        with pytest.raises(expected, match=message) as caught:
            run(wrap(client).read_software_revision())
        assert not isinstance(caught.value, errors.BleDisconnectedError)
        assert caught.value.__cause__ is error

    def test_a_failure_on_a_dead_link_is_a_disconnect(self):
        client = connected_client()
        transport = wrap(client)
        # The link went without the callback having arrived yet.
        client.is_connected = False
        with pytest.raises(errors.BleDisconnectedError, match="the lock disconnected: BleakError: Not connected"):
            run(transport.read_software_revision())


class TestStartNotify:
    def test_hands_on_each_notification_as_bytes(self):
        client = connected_client()
        transport = wrap(client)
        seen = []

        async def scenario():
            await transport.start_notify(seen.append, lambda: None)
            client.link.notify(b"\x01\x02")
            client.link.notify(b"\x03")
            await asyncio.sleep(0)

        run(scenario())
        assert seen == [b"\x01\x02", b"\x03"]
        assert all(type(data) is bytes for data in seen)
        assert client.notifying is client.communication

    def test_nothing_is_handed_on_after_close(self):
        client = connected_client()
        transport = wrap(client)
        seen = []

        async def scenario():
            await transport.start_notify(seen.append, lambda: None)
            # bleak can still have a notification queued when close() runs.
            transport._notified(client.communication, bytearray(b"\x01"))
            await transport.close()
            transport._notified(client.communication, bytearray(b"\x02"))

        run(scenario())
        assert seen == [b"\x01"]

    def test_a_lock_without_the_communication_characteristic(self):
        client = connected_client()
        client.services = FakeServices([FakeService(DEVICE_INFORMATION_SERVICE_UUID, [client.software_revision])])
        with pytest.raises(errors.BleError, match="no communication characteristic"):
            run(wrap(client).start_notify(lambda data: None, lambda: None))

    def test_services_not_discovered(self):
        client = connected_client()

        class Undiscovered:
            def get_characteristic(self, uuid):
                raise BleakError("Service Discovery has not been performed yet")

        client.services = Undiscovered()
        with pytest.raises(errors.BleError, match="GATT services are not known: BleakError: Service Discovery"):
            run(wrap(client).start_notify(lambda data: None, lambda: None))

    def test_a_characteristic_that_cannot_be_written(self):
        client = connected_client(properties=("notify",))
        with pytest.raises(errors.BleError, match=r"cannot be written \(properties: \['notify'\]\)"):
            run(wrap(client).start_notify(lambda data: None, lambda: None))

    @pytest.mark.parametrize(
        ("error", "expected"),
        [(TimeoutError(), errors.BleTimeoutError), (BleakError("Not permitted"), errors.BleError)],
    )
    def test_errors_are_translated(self, error, expected):
        client = connected_client()
        client.errors["start_notify"] = error
        transport = wrap(client)
        with pytest.raises(expected, match="Subscribing to the lock"):
            run(transport.start_notify(lambda data: None, lambda: None))
        # Not subscribed, so close() does not try to unsubscribe.
        run(transport.close())
        assert client.stop_notify_calls == 0


class TestWrite:
    def test_with_response_when_the_characteristic_allows_it(self, caplog):
        caplog.set_level(logging.DEBUG)
        client = connected_client(properties=("write-without-response", "write", "notify"))
        transport = wrap(client)
        run(transport.write(ACK))
        assert client.write_calls == [(ACK, True)]
        assert transport.write_with_response
        assert "writing with response" in caplog.text

    def test_without_response_when_that_is_all_it_allows(self, caplog):
        caplog.set_level(logging.DEBUG)
        client = connected_client(properties=("write-without-response", "notify"))
        transport = wrap(client)
        run(transport.write(ACK))
        run(transport.write(ACK_2))
        assert client.write_calls == [(ACK, False), (ACK_2, False)]
        assert not transport.write_with_response
        # Looked up once per connection, and logged once.
        assert caplog.text.count("writing without response") == 1

    @pytest.mark.parametrize(
        ("error", "expected", "message"),
        [
            (TimeoutError(), errors.BleTimeoutError, "Writing to the lock timed out"),
            (BleakError("Write failed"), errors.BleError, "Writing to the lock failed: BleakError: Write failed"),
            (ConnectionResetError(), errors.BleError, "Writing to the lock failed: ConnectionResetError"),
        ],
    )
    def test_errors_are_translated(self, error, expected, message):
        client = connected_client()
        client.errors["write_gatt_char"] = error
        with pytest.raises(expected, match=message):
            run(wrap(client).write(ACK))

    def test_a_write_after_the_link_dropped(self):
        client = connected_client()
        transport = wrap(client)
        client.drop_link()
        with pytest.raises(errors.BleDisconnectedError, match="The lock disconnected"):
            run(transport.write(ACK))
        assert client.write_calls == []

    def test_a_write_after_close(self):
        client = connected_client()
        transport = wrap(client)
        run(transport.close())
        with pytest.raises(errors.BleDisconnectedError, match="The transport is closed"):
            run(transport.write(ACK))


class TestDisconnect:
    def test_the_session_hears_about_a_dropped_link_once(self):
        client = connected_client()
        transport = wrap(client)
        dropped = []

        async def scenario():
            await transport.start_notify(lambda data: None, lambda: dropped.append(True))
            client.drop_link()
            transport.client_disconnected(client)

        run(scenario())
        assert dropped == [True]

    def test_a_drop_before_subscribing_refuses_the_subscription(self):
        client = connected_client()
        transport = wrap(client)
        client.drop_link()
        with pytest.raises(errors.BleDisconnectedError):
            run(transport.start_notify(lambda data: None, lambda: None))

    def test_our_own_close_is_not_reported_as_a_drop(self):
        client = connected_client()
        transport = wrap(client)
        dropped = []

        async def scenario():
            await transport.start_notify(lambda data: None, lambda: dropped.append(True))
            await transport.close()

        run(scenario())
        # FakeBleakClient calls the callback on disconnect(), as bleak does.
        assert client.disconnect_calls == 1
        assert dropped == []

    def test_a_command_in_flight_fails_when_the_link_drops(self):
        lock = FakeLock()

        async def scenario():
            transport = await BleakTransport.connect(lock, client_class=functools.partial(FakeBleakClient, require_login=False))
            client = transport._client
            async with new_session(transport) as session:
                client.link.silent.add(CommandId.BATT_INFO_GET)
                task = asyncio.create_task(session.send(commands.batt_info_get()))
                await asyncio.sleep(0.01)
                client.drop_link()
                await task

        with pytest.raises(errors.BleDisconnectedError, match="disconnected before it answered"):
            run(scenario())


class TestClose:
    def test_unsubscribes_then_disconnects_once(self):
        client = connected_client()
        transport = wrap(client)

        async def scenario():
            await transport.start_notify(lambda data: None, lambda: None)
            await transport.close()
            await transport.close()

        run(scenario())
        assert client.stop_notify_calls == 1
        assert client.disconnect_calls == 1
        assert not client.is_connected

    def test_without_a_subscription_it_only_disconnects(self):
        client = connected_client()
        run(wrap(client).close())
        assert client.stop_notify_calls == 0
        assert client.disconnect_calls == 1

    def test_a_link_that_is_already_gone_is_left_alone(self):
        client = connected_client()
        transport = wrap(client)
        client.drop_link()
        run(transport.close())
        assert client.disconnect_calls == 0

    @pytest.mark.parametrize("error", [TimeoutError(), BleakError("Not connected"), EOFError()])
    def test_never_raises(self, error, caplog):
        caplog.set_level(logging.DEBUG)
        client = connected_client()
        transport = wrap(client)

        async def scenario():
            await transport.start_notify(lambda data: None, lambda: None)
            client.errors["stop_notify"] = error
            client.errors["disconnect"] = error
            await transport.close()

        run(scenario())
        assert "Stopping notifications failed" in caplog.text
        assert "Disconnecting from the lock failed" in caplog.text


def test_mtu_size_is_the_clients():
    assert wrap(connected_client(mtu_size=185)).mtu_size == 185


def test_the_characteristic_is_passed_as_an_object_not_a_uuid():
    # bleak resolves a UUID string on every call; the object also avoids any
    # ambiguity if a lock ever lists the UUID twice.
    client = connected_client()
    seen = []
    original = client.write_gatt_char

    async def write(specifier, data, response=None):
        seen.append(specifier)
        await original(specifier, data, response=response)

    client.write_gatt_char = write
    run(wrap(client).write(ACK))
    assert seen == [client.communication]


def test_the_fake_gatt_table_has_the_shape_of_bleaks():
    """The fake's services, as far as it models them, answer to bleak's own names."""
    from bleak.backends.characteristic import BleakGATTCharacteristic
    from bleak.backends.service import BleakGATTService, BleakGATTServiceCollection

    client = connected_client()
    service = client.services.get_service(DEVICE_INFORMATION_SERVICE_UUID)
    shapes = [
        (client.services, BleakGATTServiceCollection, ("services", "characteristics", "get_service", "get_characteristic")),
        (service, BleakGATTService, ("uuid", "handle", "description", "characteristics", "get_characteristic")),
        (
            client.communication,
            BleakGATTCharacteristic,
            ("uuid", "handle", "properties", "description", "descriptors", "service_uuid", "service_handle"),
        ),
    ]
    for fake, real, names in shapes:
        for name in names:
            assert hasattr(real, name), f"bleak's {real.__name__} has no {name}; the fake models something bleak lacks"
            assert hasattr(fake, name), f"the fake {type(fake).__name__} lacks {name}"

    # Iterating gives the services, each with its characteristics, as in bleak.
    table = [(service.uuid, [c.uuid for c in service.characteristics]) for service in client.services]
    assert table == [
        (
            DEVICE_INFORMATION_SERVICE_UUID,
            [client_const.SOFTWARE_REVISION_CHARACTERISTIC_UUID, client.manufacturer_name.uuid],
        ),
        (client_const.SERVICE_UUID, [client_const.COMMUNICATION_CHARACTERISTIC_UUID]),
    ]
    assert client.services.characteristics[client.communication.handle] is client.communication
    assert client.services.services[client.communication.service_handle].uuid == client_const.SERVICE_UUID
    assert client.services.get_service("0000ffff-0000-1000-8000-00805f9b34fb") is None
    service = client.services.get_service(client_const.SERVICE_UUID.upper())
    assert service.get_characteristic(client_const.COMMUNICATION_CHARACTERISTIC_UUID) is client.communication
    assert service.get_characteristic(client_const.SOFTWARE_REVISION_CHARACTERISTIC_UUID) is None


def test_bleak_characteristic_not_found_is_a_ble_error():
    client = connected_client()
    client.software_revision.uuid = "00002a26-0000-1000-8000-00805f9b34fb"
    client.services = FakeServices(
        [
            FakeService(DEVICE_INFORMATION_SERVICE_UUID, [client.software_revision]),
            FakeService(client_const.SERVICE_UUID, [client.communication]),
        ]
    )
    with pytest.raises(errors.BleError, match="BleakCharacteristicNotFoundError") as caught:
        run(wrap(client).read_software_revision())
    assert isinstance(caught.value.__cause__, BleakCharacteristicNotFoundError)


# --- Only API that bleak 0.22.3 and 3.0.2 both have -----------------------------------

# Checked by hand against both releases' BleakClient. Home Assistant 2025.6
# runs 0.22.3; anything else here would work in the tests and on a Mac and
# fail there.
BOTH_RELEASES_CLIENT_API = {
    "connect",
    "disconnect",
    "is_connected",
    "mtu_size",
    "services",
    "read_gatt_char",
    "write_gatt_char",
    "start_notify",
    "stop_notify",
}
BOTH_RELEASES_CONSTRUCTOR_KEYWORDS = {"disconnected_callback", "timeout"}


def _client_uses(tree):
    """Every attribute the module reads off a BleakClient, and every call to the client class."""
    attributes = set()
    constructor_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            value = node.value
            on_client = (isinstance(value, ast.Attribute) and value.attr == "_client") or (
                isinstance(value, ast.Name) and value.id == "client"
            )
            if on_client:
                attributes.add(node.attr)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "client_class":
            constructor_calls.append(node)
    return attributes, constructor_calls


def test_uses_only_client_api_both_bleak_releases_have():
    tree = ast.parse(SOURCE.read_text())
    attributes, constructor_calls = _client_uses(tree)
    assert attributes, "the walk found no client use, so it checked nothing"
    assert attributes <= BOTH_RELEASES_CLIENT_API
    assert constructor_calls
    for call in constructor_calls:
        assert {kw.arg for kw in call.keywords} <= BOTH_RELEASES_CONSTRUCTOR_KEYWORDS


def test_every_write_says_which_kind():
    # bleak 3.0 deprecates leaving response out, and 0.22 and 3.0 guess it
    # differently from properties a lock may report wrong.
    writes = [
        node
        for node in ast.walk(ast.parse(SOURCE.read_text()))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "write_gatt_char"
    ]
    assert writes
    assert all("response" in {kw.arg for kw in call.keywords} for call in writes)

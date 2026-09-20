# The BLE protocol library

`custom_components/onesti_lock/ble/` is a Python implementation of the
Bluetooth protocol the Nimly/Onesti locks speak, written from the decompiled
Nimly BLE app. It frames and parses every packet, runs the key exchange and
the AES layer, logs in as owner, and takes over a factory-reset lock without
the vendor cloud. The protocol itself is in [ble-protocol.md](ble-protocol.md)
and [ble-auth-provisioning.md](ble-auth-provisioning.md). This document is
about the code.

Two things it is not, yet:

- **It has never talked to a lock.** The bleak transport has only run against
  a fake client, and no byte in the tests was captured from hardware. Every
  frame is checked against the app's code and the crypto against the app's
  own classes run on a JDK; whether the lock agrees is open. The table at the
  end separates the two.
- **The integration does not use it.** Nothing outside `ble/` imports it, the
  config flow has no BLE step, and Home Assistant never loads it. It is not in
  the release ZIP either: `ZIP_EXCLUDE` in `scripts/release_publish.py` leaves
  out `ble/` and `bluetooth.py`, so `ble/client/const.py` and
  `ble/client/auth.py`, which hold the credential a factory-reset lock accepts
  as its owner, are not installed on anyone's box for a feature that does not
  exist. The code stays in the repo and in the tag's source tree. Whatever
  first imports it drops the path from `ZIP_EXCLUDE` in the same change; the
  build refuses to pack a module that reaches for something it leaves out.

## Layers

Three layers and two shared modules. Each layer imports only what is below
it; `tests/ble/test_package.py` fails the build otherwise.

```
ble/__init__.py      public API: re-exports what a caller needs
ble/client/          one connection to one lock
  transport.py         Transport, the Protocol a Bluetooth stack implements
  bleak_transport.py   BleakTransport, the Transport over bleak (not re-exported)
  session.py           Session: key exchange, one command at a time, events
  tracing.py           Tracer, the hook that sees every frame a Session handles
  auth.py              OwnerCredential, authenticate_owner (challenge-response)
  enrollment.py        enroll, resume_enrollment, Enrollment, the save hook, BleEnrollmentError
  const.py             GATT UUIDs, timing, connect firmware floor, factory credential
ble/crypto.py        secp256r1 ECDH and AES-128-CBC, in the app's byte order
ble/protocol/        the wire format, no crypto and no I/O
  packet.py            Layer 1 packets, packetizing, PacketStream (reassembly)
  blob.py              blob header and reassembly of multi-packet payloads
  command.py           Layer 2 commands, CommandRef counter
  features.py          the app's firmware and model gates per command
  commands.py          one builder per command, with the app's argument checks
  response.py          Layer 3 responses, status, event ref
  responses.py         one parser per answer, typed dataclasses
  advertisement.py     the 0xFD00 service data, recognising an enrolled lock
  streams.py           little-endian field reader and writer
  const.py             ids, header layouts, lengths, slot ranges, enums
ble/errors.py        the exception tree, used by all three layers
```

`protocol/` knows nothing about encryption. `PacketStream` takes any object
with `encrypt` and `decrypt` (the `PayloadCipher` protocol), and the session
hands it the AES cipher from `crypto.py` after the key exchange. `errors.py`
imports only `protocol/const.py`, so protocol modules can raise library
errors without a cycle. The subpackage `__init__.py` files import nothing, so
loading one protocol module does not pull in the rest.

Every value in `protocol/const.py`, `client/const.py` and `crypto.py` names
the Java source it came from, relative to `com/nimly/ekey/ble/`, so it can be
checked rather than trusted.

## Using it

Inside the integration: `from .ble import ...`. Outside Home Assistant,
`custom_components.onesti_lock.ble` would run the component's `__init__.py`,
which imports Home Assistant. Put `custom_components/onesti_lock` on
`sys.path` and `import ble` instead; every import inside the package is
relative and stays within `ble/`. The only third-party dependency is
`cryptography`, plus `bleak` for `ble.client.bleak_transport`, which the
package does not import itself.

The examples assume a connected `transport` (see
[Plugging in a transport](#plugging-in-a-transport)) and `from ble import
...` of the names used.

### A session

A `Session` is one connection. Entering it reads the firmware revision,
refuses anything below 4.6.0, subscribes to notifications, runs the key
exchange in the clear and switches the packet stream to AES. On 4.7.90 and up
it also asks for the model, as the app does. Leaving it closes the transport.

```python
async with Session(transport) as session:
    print(session.firmware, session.model)   # (4, 8, 2), LockModelId.NIMLY_PRO
```

`send(command)` returns the `Response` once the status says success.
`request(command, parser)` also runs a parser from `protocol/responses.py`
on it. Commands go one at a time with the app's timing: 20 s to answer, then
320 ms before the next. A session connects once; after a disconnect, build a
new `Session` on a new transport.

Below 4.7.90 every command carries CommandRef 16, so an answer that turns up
after its command timed out looks like the answer to the next one. The app
lives with that. The session narrows it without changing the wire: after a
timeout under the static ref, the next command holds back for
`late_answer_grace` (20 s by default) and drops whatever arrives meanwhile,
and an answer under ref 16 whose id belongs to another command is ignored as
late. A late answer to a command with the same id, after the grace period,
still completes the next one; nothing on the wire tells them apart. Details
in the session docstring.

### Enrolling a factory-reset lock

`enroll` does what the app's `AddLockFragment.finishSetup` does, with local
values where the app fetches the cloud's: log in with the factory credential,
replace the owner key through `UserAuthUpdate`, then set a device id, the
clock, a server key and the name.

```python
def store(enrollment: Enrollment) -> None:
    write_atomically(enrollment.to_dict())   # durable when it returns

async with Session(transport) as session:
    enrollment = await enroll(session, name="Door", save=store)
```

The name is at most 8 ASCII characters. The device id defaults to a random 6
bytes from `new_device_id()`, never all zero, which is the factory id.

`save` is required. Once `UserAuthUpdate` has gone through, the factory key
presumably no longer opens the lock, and the new owner key exists only in the
running process. So `enroll` calls `save` as soon as the owner key is derived
and again after every step the lock confirms, each time before the next
command. Ctrl-C (which cancels the task under `asyncio.run`), a cancelled
task or a crash then leaves the last confirmed state stored. `save` is a
plain function, not a coroutine: there is no `await` between the lock's
answer and the save, so no cancellation can land in between. The one window
it cannot cover is `UserAuthUpdate` itself, since the owner key needs the
lock's answer (below).

If `save` raises, nothing more is sent and `BleEnrollmentNotSavedError` (a
`BleEnrollmentError`) carries the `Enrollment` that could not be stored, with
the save's exception as cause. It is the only copy of the key. A step that
fails raises `BleEnrollmentError` with `err.enrollment` equal to what `save`
last got. Either way, finish on a new connection from what was saved:

```python
async with Session(new_transport) as session:
    enrollment = await resume_enrollment(session, partial, save=store)
```

`resume_enrollment` logs in with the factory device id until the device id
step is confirmed. If `DeviceIdSet` reached the lock and only its answer was
lost, the lock refuses that id, so on `BleSecurityError` the login is tried
once more with the enrolled id, and if that works the step counts as done.
The retry runs on the same connection; whether the lock allows a second
`UserAuthBegin` after refusing one is not known. If it drops the link
instead, mark the step done by hand (`replace(partial,
completed=partial.completed | {EnrollmentStep.DEVICE_ID})`) and resume that.

The `Enrollment` also keeps what the owner key was derived from: the private
half of the `UserAuthUpdate` key pair and the lock's answer
(`update_private_key`, `lock_update_public_key`). Nothing reads them. The
derivation rests on three conventions no lock has confirmed, and if one is
wrong the lock holds an owner key that cannot be recomputed from the result
alone. With both halves stored, another reading of the same bytes can be
tried offline; without them the way back is a module reset, which takes the
Zigbee pairing with it. They are as secret as the owner key, since together
they are the owner key.

`err.enrollment` is `None` only when `UserAuthUpdate` itself failed. The lock
then usually still has its factory key; if it took the new key and only the
answer was lost, only a factory reset recovers it. A failed factory login
raises the session's own error and has changed nothing.

### Logging in with a stored enrollment

```python
enrollment = Enrollment.from_dict(load())
async with Session(transport) as session:
    await authenticate_owner(session, enrollment.owner_credential)
    ...
```

`owner_credential` sends the enrolled device id once `DeviceIdSet` has gone
through, and the factory id before that. A wrong key gets a failed status,
most likely `BleSecurityError`.

### PIN codes, RFID and fingerprints

The builders in `commands` check what the app checks before anything is
sent: the slot range, and a PIN of 4-8 digits. BLE numbers slots differently
from Zigbee ([slot-numbering.md](../slot-numbering.md)).

```python
await session.send(commands.pin_code_set(803, "8832"))    # PIN slots 800-899
await session.send(commands.pin_code_clear(803))
await session.send(commands.master_pin_code_set("123456"))  # slot 0, models with master_pin

scan = await session.request(commands.scan_rfid_code(900), responses.parse_scan_rfid_code)   # 900-999
await session.send(commands.rfid_code_clear(900))

scan = await session.request(commands.fingerprint_scan(150), responses.parse_fingerprint_scan)  # 150-199
await session.send(commands.fingerprint_clear(150))
```

A scan puts the lock in enrollment mode and answers with a `ScanResult`
(`slot`, and a `LockStatusId` or the raw byte). The timeout is the app's 20 s
for every command, which has to cover the tag or finger too.

`send` applies the app's firmware and model gates first. The app offers the
admin commands (PIN, RFID, fingerprint, keypad, auto-lock, volume, battery)
only from 4.7.90, and fingerprint, keypad enable and master PIN only on
models whose `LockModelId.features` say so. A command the app would not send
raises `BleFeatureUnavailableError`, whose `feature` is the app's own answer
(`DeviceFeature.UNAVAILABLE_VERSION`, `UNAVAILABLE_UNKNOWN` or
`UNAVAILABLE`). `session.availability(command)` asks without sending. The
rules are in `protocol/features.py`, one per `feature()` in the app.

To find out what a lock does with a command the app never sends it, pass
`skip_app_gates=True` to `send` or `request`; the log says it went past the
gate:

```python
await session.send(commands.pin_code_set(803, "8832"), skip_app_gates=True)
```

Lock and unlock, settings and readouts follow the same pattern:

```python
await session.send(commands.ekey_operate(EkeyOperationId.UNLOCK))
await session.send(commands.auto_lock_set(True))
battery = await session.request(commands.batt_info_get(), responses.parse_batt_info)
```

### Events

While a session is open the lock sends two unsolicited frames, `LockStatus`
(the bolt moved: slot, state, method) and `UserAdded` (a credential landed in
a slot), both under CommandRef 128. They never touch the command in flight.

```python
def on_event(event: LockEvent) -> None:
    if isinstance(event, LockStatus):
        print(event.slot, event.state, event.method)

remove = session.add_event_listener(on_event)
```

The listener runs on the event loop and must not block. The remover can be
called more than once. An exception from a listener is logged by type only,
since its message could quote anything. Events arrive only on a live
connection; the lock is not known to broadcast them otherwise.

## Plugging in a transport

`client/transport.py` is the seam. A `Transport` is one lock already
connected, and the session needs four calls:

| Method                                              | Does                                                                      |
| --------------------------------------------------- | ------------------------------------------------------------------------- |
| `read_software_revision()`                          | Raw value of characteristic 0x2A28, such as `b"4.8.2"`                    |
| `start_notify(on_notification, on_disconnect)`      | Subscribe to the communication characteristic                             |
| `write(data)`                                       | Write one packet to it and return once the write is done                  |
| `close()`                                           | Unsubscribe and disconnect; safe to call twice                            |

`on_notification` gets each notification's bytes, one Layer 1 packet per
call, in arrival order. `on_disconnect` is called when the link drops. Both
are plain functions on the session's event loop. Scanning, connecting,
service discovery and MTU stay with whoever builds the transport. Transport
errors should be `BleError` subclasses, `BleDisconnectedError` when the link
is gone; anything else passes through unchanged.

The UUIDs are exported: `SERVICE_UUID`, `COMMUNICATION_CHARACTERISTIC_UUID`,
`SOFTWARE_REVISION_CHARACTERISTIC_UUID` and `ADVERTISING_UUID`.

The session frames its writes for MTU 23 whatever the link negotiated,
because the app never asks for more and nothing says the lock takes more.
`Session(transport, mtu=...)` changes that; nobody has tried a larger MTU.

### bleak

`client/bleak_transport.py` has `BleakTransport`, the transport over
[bleak](https://github.com/hbldh/bleak). It is the only module in `ble/`
that imports bleak, and `ble/__init__.py` does not import it, so the rest
loads without bleak; import it as `ble.client.bleak_transport`.
`tests/ble/test_package.py` holds both rules.

`BleakTransport.connect` builds a `BleakClient`, connects it and wraps it:

```python
from ble.client.bleak_transport import BleakTransport

transport = await BleakTransport.connect(device)   # a BLEDevice from a scan, or an address
async with Session(transport) as session:
    ...
```

An already connected client is wrapped with `BleakTransport(client)`. bleak
takes its disconnect callback only when the client is built, before the
transport exists, so the caller routes it to `client_disconnected` once it
does. In Home Assistant:

```python
transport: BleakTransport | None = None

def disconnected(client: BleakClient) -> None:
    if transport is not None:
        transport.client_disconnected(client)

client = await establish_connection(
    bleak_retry_connector.BleakClientWithServiceCache, device, name, disconnected_callback=disconnected
)
transport = BleakTransport(client)
```

A client no longer connected is refused with `BleDisconnectedError`, so a
drop between connecting and wrapping is not lost.

On the link:

- **Write type.** The app never calls `setWriteType`, so Android picks:
  `BluetoothGattCharacteristic.initCharacteristic` sets
  `WRITE_TYPE_NO_RESPONSE` as soon as `PROPERTY_WRITE_NO_RESPONSE` is listed,
  whether or not `PROPERTY_WRITE` is too. `BleakTransport` makes the same
  choice through `transport.write_with_response()`: `response=False` when the
  characteristic lists `write-without-response`, `response=True` when only
  `write`, `BleError` when neither. bleak's default goes the other way, so the
  flag is always passed. The choice is logged at debug once per connection,
  and `info` prints it for the characteristic it found. Which properties the
  lock's characteristic has is not recorded.
- **Notifications.** bleak calls back with the characteristic first and a
  `bytearray`; the transport drops the first and hands on `bytes`. Nothing is
  handed on after `close()`.
- **Errors.** `TimeoutError` becomes `BleTimeoutError`. `BleakError`,
  `EOFError` and `OSError` (what BlueZ's D-Bus socket raises when the link or
  bluetoothd goes away) become `BleDisconnectedError` once the link is down,
  else `BleError`, with bleak's exception as cause. `BleakGATTProtocolError`
  exists only from bleak 3.0 and is caught through `BleakError`.
- **Close.** Stops notifications and disconnects, never raises, does nothing
  the second time. bleak calls the disconnect callback on our own disconnect
  too; the transport ignores it.
- **MTU.** `mtu_size` is the client's, for the log; the session frames for
  its own `mtu`, 23 by default. CoreBluetooth cannot be asked for an MTU, and
  bleak's BlueZ backend reports 23 whatever was negotiated.

Home Assistant 2025.6 runs bleak 0.22.3 and 2026.9 runs 3.0.2, so the module
uses only client API both have: the constructor's `disconnected_callback`
and `timeout`, `connect`, `disconnect`, `is_connected`, `mtu_size`,
`services` with `get_characteristic` and `properties`, `read_gatt_char`,
`write_gatt_char` with explicit `response`, `start_notify` and
`stop_notify`. A test parses the module and fails on anything else, and the
module type-checks and its tests pass on both. Both call the notification
callback with the characteristic first; the `int` handle went away in bleak
0.18.

In Home Assistant, look the lock up with
`bluetooth.async_ble_device_from_address(hass, address, connectable=True)`,
connect with `bleak_retry_connector.establish_connection`, then wrap the
client as above. An ESPHome Bluetooth proxy needs nothing extra: Home
Assistant routes through it when it is the closest adapter, as long as active
connections are enabled. A proxy has only a few connection slots, so close
the session as soon as the work is done. `tools/esphome/README.md` is the
proxy used here: an ESP32-C3 by the door with a debug build that logs the
lock's `0xFD00` advertisements and keeps counters across reboots, so "does
the lock advertise at all" can be answered before anything connects. That
glue imports Home Assistant, so it lives outside `ble/`, in the
integration's `bluetooth.py`
([technical.md](../technical.md#reaching-the-lock-over-bluetooth)). Read the
client class off `bleak_retry_connector` at call time rather than importing
it by name: habluetooth replaces it with the wrapper that routes through
adapters and proxies once Home Assistant's Bluetooth is set up.

### Tracing frames

A `Tracer` passed to `Session(transport, tracer=...)` sees every frame:
`command` for each command with its CommandRef, `packet_out` for each Layer 1
packet before it is written, `packet_in` for each notification, `response`
for each response or event that parsed, and `dropped` for one that did not,
with the failing bytes. It is a `Protocol`, so any object with those five
methods will do. `client/tracing.py` spells out the order and which bytes
`dropped` gets.

The library does not redact what it hands a tracer. `command` sees PinCodeSet
with the PIN and UserAuthFinalize with the challenge answer, `response` sees
the owner challenge; only the packets after the key exchange are ciphertext.
A tracer that writes anything down has to redact it first. A tracer that
raises is logged by exception type and does not break the session.

### The fake lock

Tests use `tests/ble/fake_lock.py`: `FakeLock` holds a lock's lasting state,
`FakeTransport` is one connection to it playing the lock side with the
`cryptography` package directly. `FakeBleakClient` puts the same lock behind
bleak's `BleakClient` shape and raises bleak's own exceptions, and
`tests/ble/client/test_bleak_transport.py` runs a full enrollment and a
PinCodeSet through `Session`, `BleakTransport` and that client. bleak comes
from the `ble` dependency group, which `unit` includes; without it those
tests skip.

## Finding the lock

The lock advertises 8 bytes of service data under the 16-bit UUID `0xFD00`,
read with `parse_advertisement`:

```python
ad = parse_advertisement(service_data[ADVERTISING_UUID])
ad.enrolled            # False while the seed is 00 00 (factory state)
ad.matches(device_id)  # True for the enrolled lock with this device id
```

A factory-reset lock shows seed `00 00` and an id of its own. An enrolled
lock shows a seed and the first 6 bytes of SHA-1(seed || device id), so it
never reveals its device id, and only someone who stored the device id can
tell which lock it is. That is why `Enrollment` keeps it. Nothing has been
captured over the air by this project, so the format is the app's reading,
and the one outside description of a real advertisement had 10 bytes and a
device name ([ble-protocol.md](ble-protocol.md#scan-identification)), most
likely the 2-byte UUID counted in, but nobody has seen the hex.
`parse_advertisement` accepts 8 bytes or more and reads the first 8, as both
vendor apps do; if the extra bytes sit anywhere but at the end, `matches()`
is silently wrong. Do not build device recognition on it before a capture.

## Storing an enrollment

`Enrollment.to_dict()` gives a JSON-safe dict with bytes as hex;
`Enrollment.from_dict()` reads it back and validates every field. Error
messages name a bad field, never its value. `format` is bumped when the shape
changes; `from_dict` still reads earlier formats, `to_dict` writes the
current one. Format 2 added the owner key material, so a format 1 file reads
back with those two fields `None`.

| Field                    | Secret | What it is                                                                     |
| ------------------------ | ------ | ------------------------------------------------------------------------------ |
| `owner_key`              | Yes    | The 16-byte AES key that answers the owner challenge. Whoever holds it owns the lock. |
| `update_private_key`     | Yes    | Private half of the `UserAuthUpdate` key pair. With the field below it gives the owner key again, under another reading of the derivation. |
| `lock_update_public_key` | Yes    | The lock's answer to `UserAuthUpdate`, the other half of that derivation       |
| `server_private_key`     | Yes    | Private half of the key pair sent in `ServerKeyUpdate`. Nothing uses it yet, but it would let its holder act as the server the lock trusts. |
| `device_id`              | No, but sensitive | Sent in every login, and the only way to recognise the lock's advertisement, so it lets someone track the lock. |
| `lock_server_public_key` | No     | The lock's answer to `ServerKeyUpdate`                                         |
| `user_id`, `name`, `completed`, `format` | No | Owner user id (0), the name written to the lock, the steps the lock confirmed |

Store the whole dict, as a secret. In Home Assistant that means the config
entry or its own storage, both plaintext on disk, and never diagnostics, logs
or entity attributes without redaction. `Enrollment`, `OwnerCredential`,
`KeyPair` and `LinkKeys` keep their keys out of `repr`, so printing one is
safe; printing `to_dict()` is not.

## Errors

Everything the library raises is a `BleError`, so one `except` catches it
all. `tests/ble/test_package.py` parses every module and fails on a `raise`
of anything else. Below `BleError` the class says whose fault it is:

| Class                    | Meaning                                                                                                              |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| `BleValidationError`     | An argument refused before anything is sent: slot range, PIN, key length, a frame too big for its length field. Also a `ValueError`. |
| `BleSessionStateError`   | A `Session` used out of order: connecting twice, sending before `connect()`. A bug in the caller. Also a `RuntimeError`. |
| `BleProtocolError`       | Bytes from the lock that do not parse, or an answer of the wrong kind                                               |
| `BleOperationError`      | The lock answered with a status other than success. One subclass per status: `BleFailedError`, `BleNotAvailableError`, `BleInternalError`, `BleParameterError`, `BleLengthError`, `BleNotFoundError`, `BleNoMatchError`, `BleNotSupportedError`, `BleNotValidError`, `BleSecurityError`. An unknown status byte gets the base class, with the byte in `status`. |
| `BleTimeoutError`        | No answer within the response timeout. Also a `TimeoutError`.                                                       |
| `BleDisconnectedError`   | The link dropped, or the session is closed                                                                          |
| `BleFirmwareTooOldError` | Firmware below 4.6.0 on connect; carries `firmware` and `required`                                                  |
| `BleFeatureUnavailableError` | A command the app would not send to this lock, refused before sending; carries `command`, `feature`, `firmware` and `model` |
| `BleEnrollmentError`     | Enrollment stopped partway; carries `step` and the partial `enrollment` (in `client/enrollment.py`)                 |
| `BleEnrollmentNotSavedError` | A `BleEnrollmentError`: the enrollment's `save` raised after `step` went through, so nothing more was sent; `enrollment` is the only copy |

A malformed notification is logged and dropped, as the app drops it. The
waiting command then times out, and the `BleTimeoutError` has the dropped
frame's `BleProtocolError` as cause.

## Rules the code keeps

- **No Home Assistant, no reaching out.** Nothing in `ble/` imports
  `homeassistant`, `zigpy` or `voluptuous`, and no relative import leaves
  `ble/`. That rules out the integration's `redact.py` too, which is why the
  library keeps secrets out of its messages at the source.
- **No PIN, key or challenge in a message, a repr or the log.** Errors are
  built from ids, statuses and lengths. Dataclasses holding payloads or keys
  mark those fields `repr=False`. The app's PinCodeSet error quotes the PIN;
  ours does not. `tests/test_no_pin_exposure.py` walks `ble/` too, and
  `tests/ble/client/test_session.py` checks that no `_LOGGER` call passes a
  value named like a key, PIN, challenge or payload. No log call carries a
  traceback.
- **`cryptography` and `bleak` come from Home Assistant.** `cryptography` is
  a core requirement and bleak comes with the bluetooth integration, so
  neither is in `manifest.json`, where a pin could fight the one Home
  Assistant sets. Tests get them from the `unit` group in `pyproject.toml`,
  bleak through the `ble` group it includes. `crypto.py` and
  `client/bleak_transport.py` use only API both ends of the supported Home
  Assistant range ship.
- **Protocol values come from the app.** A value nobody could read out of the
  decompiled code is marked as a guess where it is used, not filled in.

## Tests

`tests/ble/` mirrors the package: `protocol/`, `client/`, and
`test_crypto.py`, `test_errors.py` and `test_package.py` at the top. It runs
with the rest of `tests/` in CI's `unit` group:

```bash
just test-unit                                   # all of tests/, BLE included
UV_PROJECT_ENVIRONMENT=.venv-unit uv run --frozen --python 3.14 --group unit pytest tests/ble -q
```

Beyond each builder and parser:

- `protocol/test_const.py` and `client/test_const.py` are a second,
  independent transcription of the app's enums and constants. A typo in
  `const.py` has to be made twice to pass.
- `protocol/test_packet.py` runs a frame through every layer and back.
- `client/test_session.py` checks the wire bytes against framing and AES done
  with `cryptography` directly, so a session mistake cannot hide on both
  sides of an assertion.
- `client/test_enrollment.py` runs a full enrollment against the fake lock
  with fixed keys, compares every command with the app's sequence, then logs
  in again with the stored enrollment and checks that the factory key is
  refused.
- `test_package.py` holds the layering, the package boundary, the rule that
  only `BleError` is raised, that only `client/bleak_transport.py` imports
  bleak and the package loads without it, and that every name in `__all__`
  resolves.
- `client/test_bleak_transport.py` runs the bleak transport against
  `FakeBleakClient`, end to end included, and holds it to the client API that
  bleak 0.22.3 and 3.0.2 share.
- `client/test_tracing.py` compares what a tracer is handed with what the
  fake lock saw on its side.

The tests use `asyncio.run` rather than pytest-asyncio, which the `unit`
group does not have.

### Where the vectors come from

No test vector was captured from a lock. Each is labelled in a comment above
it:

| Label        | Where                     | Meaning                                                                                                     |
| ------------ | ------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `documented` | `tests/ble/vectors.py`    | An example written out in `ble-protocol.md`, itself read from the app. Only PinCodeSet `8832` in slot 803. |
| `derived`    | both vector files         | Assembled by hand from the app's serializer or call site for that frame, cited by class. Proves the builder does what the app's code does. |
| `kat`        | `tests/ble/crypto_vectors.py` | Published known answers: NIST CAVS ECC CDH P-256 COUNT 0, the P-256 generator, SP 800-38A F.1.1 and F.2.1. Independent of the app and of us. |
| `executed`   | `tests/ble/crypto_vectors.py` | Printed by the app's own decompiled crypto classes run on a desktop JDK. Proves the Python matches the app byte for byte. |

The `executed` vectors come from `tests/ble/java/CryptoVectors.java`, which
compiles the app's `Aes128CbcEncrypter`, `Secp256r1SecretExchanger` and byte
helpers with two stubs (`android.util.Base64`, `kotlin.UByte`) and prints
the results. The app sources are local only (`reversing/` is gitignored), so
the harness runs from the main checkout with any JDK 17 or newer:

```bash
S=reversing/nimly-ble-decompiled/sources
B=com/nimly/ekey/ble
W=$(mktemp -d)
(cd $S && for f in $B/crypto/encrypters/*.java $B/crypto/exchangers/*.java \
    $B/extensions/ByteExtensions.java $B/extensions/BigIntegerExtensions.java \
    $B/extensions/StringExtensions.java $B/models/Data.java $B/models/IData.java; do
  mkdir -p $W/$(dirname $f) && cp $f $W/$f; done)
cp -R tests/ble/java/stubs/. tests/ble/java/CryptoVectors.java $W
(cd $W && javac -nowarn -d out $(find . -name '*.java') && java -cp out CryptoVectors)
```

Its output should match the `executed` constants in `crypto_vectors.py` line
for line. Last run on OpenJDK 27. The app runs on Android, whose `Cipher`
comes from Conscrypt rather than SunJCE. Same contract, but only a lock can
settle it.

## Running it against a lock

`scripts/ble_cli.py` runs the library against a real lock from a computer,
over bleak, one step per command. It is the tool that settles the "Lock
only" rows in the table below. Run it through `just`, which uses the `unit`
environment, or with `uv run --group ble scripts/ble_cli.py`: the `ble`
group holds exactly what the library needs at runtime, bleak and
`cryptography`, and `unit` includes it. Options go before or after the
command:

```bash
just ble scan
just ble handshake <ADDR>
just ble pin set <ADDR> 805 --factory --yes
```

The commands, in the order to run them, safe to risky:

| Command                             | Sends                                                                    | Settles                                                                                                             |
| ----------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `scan [--watch S]`                  | Nothing                                                                  | Seed (`0000` is factory state), identifier, whether a stored lock matches, whether the lock advertises all the time |
| `info ADDR`                         | GATT reads only                                                          | Services, the communication characteristic's properties (write type), MTU, 0x2A28                                   |
| `handshake ADDR`                    | Key exchange, DeviceModelGet                                             | Public key byte order, CBC from the link IV, the CommandRef rule                                                    |
| `login ADDR`                        | UserAuthBegin, UserAuthFinalize                                          | The factory key, the challenge, which status a wrong key gets                                                       |
| `read ADDR`                         | DeviceModelGet, BattInfoGet, DeviceLogGet, DeviceNameGet, CurrentTimeGet | That the encrypted channel holds over several messages                                                              |
| `operate ADDR lock\|unlock`         | EkeyOperate; the bolt moves                                              | That the lock obeys; stand at the door                                                                              |
| `pin set\|clear ADDR SLOT`          | PinCodeSet / PinCodeClear, 800-899                                       | End-to-end PIN write; try the code on the keypad                                                                    |
| `rfid scan\|clear ADDR SLOT`        | ScanRfidCode / RfidCodeClear, 900-999                                    | Interactive tag enrollment, UserAdded before the answer                                                             |
| `fingerprint scan\|clear ADDR SLOT` | FingerprintScan / FingerprintClear, 150-199                              | The same for a finger                                                                                               |
| `enroll ADDR --name NAME`           | The whole `enroll()`                                                     | Enrollment order, ServerKeyUpdate, device id binding, the seed after                                                |
| `enroll ADDR --resume`              | `resume_enrollment()`                                                    | Finishing an enrollment that stopped partway                                                                        |

`login`, `read` and the writes log in with `--factory`, with `--state FILE`,
or by default with the stored enrollment last seen at that address.

Which slot first: nobody has shown that BLE 800-899 and the Zigbee slots are
separate storage, and `docs/slot-numbering.md` keeps two hypotheses alive,
BLE 800 as Zigbee 3 and BLE 800 as Zigbee 0. Pick a slot free under both:
slot `n` where `n - 797` and `n - 800` are both free Zigbee slots. That rules
out 800-804, which land on a master slot or a Zigbee slot that may hold a
working code; 805 and up is the safe end. No command reads a slot back, so
every write is blind: try the code on the keypad afterwards, and check that
the codes that worked before still do. `pin set` and `pin clear` below 805
refuse to run without `--i-know-the-slot-mapping-is-unverified`, and so do
`rfid clear` and `fingerprint clear` at any slot, since nobody has mapped
those numberings and a deleted fingerprint only comes back with the person
and the finger at the lock. `--yes` says the command may go out; the long
flag says the slot means what you think, which is a different thing to be
sure of. The `scan` variants are not behind it: they add rather than delete.

What it refuses:

- Anything that changes the lock or moves the bolt (`operate`, `pin`, `rfid`,
  `fingerprint`, `enroll`) prints the steps it would send and stops without
  `--yes`. Slots, the PIN and the name are validated before it connects.
- It has no FactoryResetModule command, and sends DeviceIdSet,
  UserAuthUpdate and ServerKeyUpdate only through `enroll()` and
  `resume_enrollment()`. Its own send path refuses those four ids, and a test
  fails if the script names their builders, the master PIN builder or
  `ignore_slot_check`.
- A PIN never goes on the command line, where shell history and the process
  list keep it. `pin set` asks twice at a prompt that does not echo, or reads
  one line from stdin with `--pin-stdin`.
- `enroll` listens for the advertisement first and refuses unless it sees
  seed `0000`, and refuses an address that already has a state file. The
  steps and their order are under
  [Enrolling a factory-reset lock](#enrolling-a-factory-reset-lock).
- Nobody knows whether the lock locks out after failed owner logins. Each
  login that went out and did not come back logged in is recorded in
  `<state-dir>/failed-logins.jsonl`, and past `FAILED_LOGIN_LIMIT` against
  one address inside `FAILED_LOGIN_WINDOW` (both in `scripts/ble_cli.py`,
  `--help` prints the limit) the CLI stops until `--force-login`. A timeout
  or a dropped link counts too: the lock may have counted it, and the CLI
  cannot tell. A resumed enrollment can spend two attempts in one run, when
  the lock refuses the factory device id and the library tries the enrolled
  one; both are recorded.
- A command the app would not send to this lock (`Session.availability`, the
  firmware and model gates) is refused right after the handshake, before a
  login is spent; `read` skips such a read and says so. The CLI has no way
  past the gates: `skip_app_gates` is for code, not for a session against
  the front door.

State lives in `--state-dir`, by default `~/.config/onesti-lock-ble/`,
outside the repository. The directory is 0700, every file 0600. Each
enrolled lock is one JSON file named by a hash of its device id, holding
`Enrollment.to_dict()` and the address it was last seen at. It holds the
owner key: back it up, never commit it. `enroll` and `enroll --resume` pass
the library a `save` that rewrites that file (temporary file, fsync, rename,
0600) after every confirmed step, before the next command, so Ctrl-C or a
crash anywhere after `UserAuthUpdate`'s answer leaves a file that
`enroll ADDR --resume --yes` finishes. On Ctrl-C the CLI says which steps
the file holds. If a save fails, the library stops, the CLI tries once more
and says plainly when the key could not be stored; the state directory is
checked for writing before the session starts, so that takes something like
a full disk mid-run.

### The trace

Every command writes a JSON-lines frame log, by default
`<state-dir>/traces/<UTC time>-<command>.jsonl`, or where `--trace FILE`
says; `--no-trace` turns it off. Each line has `t` (UTC), `dt` (seconds
since start) and `event`:

| Event                         | Holds                                                                                     |
| ----------------------------- | ----------------------------------------------------------------------------------------- |
| `packet`                      | `dir`, the raw Layer 1 bytes in `hex`, `type` and `seq` from the unencrypted header       |
| `command`, `response`         | `id` by name, `ref`, `status`, `len`, and `payload` in hex only for ids on the list below |
| `dropped`                     | A frame the session threw away: the error and the length                                  |
| `advertisement`               | Address, RSSI and the service data, all broadcast in the clear                            |
| `connected`, `session`, `login`, `enroll`, `error`, ... | What the CLI did around the frames: MTU, firmware, CommandRef mode, model, login outcome, enrollment step |

Packets are clear text during the key exchange and ciphertext after.
Payloads are written in hex for the key exchange, DeviceModelGet,
BattInfoGet, DeviceLogGet, name and clock, EkeyOperate, the slot-only clear
and scan commands, the LockStatus and UserAdded events, and answers that
carry only a status. Everything else is a length: PinCodeSet carries the
PIN, UserAuthBegin the device id and its answer the challenge,
UserAuthFinalize the challenge answer, UserAuthUpdate and ServerKeyUpdate
key material, DeviceIdSet/DeviceIdGet the device id that identifies the
advertisement. An unknown id is a length too.

`--trace-secrets` adds every payload, the dropped frames' bytes and the link
key and IV, with a warning on stderr. With it, a failed CBC chain or a
refused challenge can be recomputed offline from the ciphertext. Use it with
test PINs on test slots only and delete the file afterwards. The link keys
are written even when the handshake fails after the key exchange, which is
when they are most needed.

### On macOS

- **Bluetooth permission.** macOS asks once whether the terminal may use
  Bluetooth. If denied, scanning fails; allow the terminal under System
  Settings, Privacy & Security, Bluetooth, and open a new terminal.
- **Addresses are UUIDs.** CoreBluetooth hides the MAC and gives each Mac its
  own UUID for the lock. `scan` recognises a stored lock by its advertisement
  (`Advertisement.matches`) and records the address it saw, so a state file
  moves between Macs.
- **The MTU cannot be requested.** CoreBluetooth negotiates it and bleak only
  reports the result. `info` and every session print it; the session frames
  for 23 regardless, as the app does.
- **No connection priority.** Android's `requestConnectionPriority` has no
  counterpart, so answers may come slower than in the app.
- **Scanning is active.** macOS has no passive scan, so the Mac sends scan
  requests, which the lock answers with a scan response. That is discovery,
  not a connection; nothing is written to the lock.
- **Repeated advertisements are coalesced.** bleak starts the scan without
  CoreBluetooth's allow-duplicates option, so a device is reported again only
  when its advertisement changes. `scan --watch` therefore restarts the scan
  every `--window` seconds and reports per window whether the lock was heard
  (`--help` prints the default). That shows whether it advertises all the
  time or only inside the four-minute pairing window, not its advertising
  interval; measuring that needs Linux.

## What is verified, and what only a lock can settle

"App code" is read in the decompiled Java, or the smali where jadx failed.
"JDK run" means the app's own classes produced the same bytes.

| Claim                                                                                           | Status                                  |
| ----------------------------------------------------------------------------------------------- | --------------------------------------- |
| Layer 1-3 layouts, blob header, single/blob split at MTU 23, sequence numbers from 1            | App code                                |
| Every command payload and response layout the library builds or parses                          | App code                                |
| Slot ranges, PIN 4-8 digits, master PIN in slot 0 with the range check off                      | App code                                |
| CommandRef 16 below firmware 4.7.90, 1-127 counter from it; events under ref 128                 | App code                                |
| Timing: 20 s timeout, 320 ms between commands                                                   | App code                                |
| Firmware and model gates per command (`protocol/features.py`)                                   | App code                                |
| Public key X then Y little endian, private key little endian, ECDH secret reversed              | App code, JDK run                       |
| Link key and IV are [0:16] and [16:32] of the reversed secret; owner key [0:16] of its own exchange | App code, JDK run                   |
| One CBC run per message from the link IV, zero padding to whole blocks                          | App code, JDK run                       |
| Owner challenge answer: decrypt, invert, encrypt with owner key and link IV                     | App code, JDK run                       |
| Factory credential: user 0, device id 00 x 6, key 11 x 16; `0x22` x 16 never read               | App code                                |
| Enrollment order: UserAuthUpdate(0, 0), DeviceIdSet, CurrentTimeSet, ServerKeyUpdate, DeviceNameSet | App code (smali)                    |
| Clock in minutes since 2023-01-01 UTC                                                           | App code                                |
| Advertisement: seed, SHA-1(seed ‖ device id)[:6]                                                | App code                                |
| That the lock accepts the factory key on current firmware                                       | Lock only                               |
| That the lock encrypts the challenge the way the app decrypts it                                | Lock only                               |
| Whether the lock checks the device id in UserAuthBegin, and which one it expects mid-enrollment | Lock only                               |
| Which status a wrong key or device id gives (the fake lock assumes SecurityError)               | Lock only                               |
| Whether admin commands need an owner login first (the fake assumes they do)                     | Lock only                               |
| Whether setup counts as complete without ServerKeyUpdate or DeviceNameSet, and which step makes the seed non-zero | Lock only              |
| What the server key is used for, and the EkeyDeviceInfo blob format                             | Lock only                               |
| Meaning of the credentials byte in UserAuthUpdate and UserAuthFinalize                          | Not traced                              |
| Battery `level` unit, device log content, Ack/Nac/Error packets, blob RFU and other flag bits    | Not traced                              |
| That the lock's own ECDH pads the shared secret to 32 bytes, as ours does (Conscrypt's padding is the app's question, not ours) | Lock only              |
| MTU above 23, the characteristic's write type, the advertisement bytes themselves               | Lock only                               |
| That RFID and fingerprint scans send UserAdded before their answer (the fake assumes so)        | Lock only                               |

Not implemented: the guest path (`EkeyUserAuth` 0x17 with a cloud token),
the ekey user commands, `EkeyDeviceInfoGet`/`Set` and `FactoryResetModule`.
The guest path needs the vendor cloud, and the rest has no use without it.

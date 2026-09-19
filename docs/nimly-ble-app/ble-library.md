# The BLE protocol library

`custom_components/onesti_lock/ble/` is a Python implementation of the
Bluetooth protocol the Nimly/Onesti locks speak, written from the decompiled
Nimly BLE app. It frames and parses every packet, runs the key exchange and
the AES layer, logs in as the lock's owner, and takes over a factory-reset
lock without the vendor cloud. What the protocol is and how it was read out of
the app is in [ble-protocol.md](ble-protocol.md) and
[ble-auth-provisioning.md](ble-auth-provisioning.md). This document is about
the code.

Two things it is not, yet:

- **It has never talked to a lock.** There is no Bluetooth transport in the
  package, and no byte in the tests was captured from real hardware. Every
  frame is checked against the app's own code, and the crypto against the
  app's crypto classes run on a JDK, but whether the lock agrees is open until
  someone runs it against one. The table at the end separates the two.
- **The integration does not use it.** Nothing outside `ble/` imports it, the
  config flow offers no BLE setup, and Home Assistant never loads it. It ships
  in the release ZIP because it lives under the component directory, so that
  wiring it in later needs no packaging change.

## Layers

The package has three layers and two shared modules. Each layer imports only
the ones below it, and `tests/ble/test_package.py` fails the build otherwise.

```
ble/__init__.py      public API: re-exports what a caller needs
ble/client/          one connection to one lock
  transport.py         Transport, the Protocol a Bluetooth stack implements
  session.py           Session: key exchange, one command at a time, events
  auth.py              OwnerCredential, authenticate_owner (challenge-response)
  enrollment.py        enroll, resume_enrollment, Enrollment, BleEnrollmentError
  const.py             GATT UUIDs, timing, connect firmware floor, factory credential
ble/crypto.py        secp256r1 ECDH and AES-128-CBC, in the app's byte order
ble/protocol/        the wire format, no crypto and no I/O
  packet.py            Layer 1 packets, packetizing, PacketStream (reassembly)
  blob.py              blob header and reassembly of multi-packet payloads
  command.py           Layer 2 commands, CommandRef counter
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
hands it the AES cipher from `crypto.py` once the key exchange is done.
`errors.py` imports only `protocol/const.py`, so the protocol modules can raise
library errors without an import cycle. The subpackage `__init__.py` files
import nothing, so loading one protocol module does not pull in the rest.

Every value in `protocol/const.py`, `client/const.py` and `crypto.py` names the
Java source it came from, relative to `com/nimly/ekey/ble/` in the decompiled
app, so it can be checked again rather than trusted.

## Using it

Inside the integration the package is `from .ble import ...`. Outside Home
Assistant, importing it as `custom_components.onesti_lock.ble` would run the
component's own `__init__.py`, which imports Home Assistant. Put
`custom_components/onesti_lock` on `sys.path` and `import ble` instead; every
import inside the package is relative and stays within `ble/`, so it loads on
its own. The only third-party dependency is `cryptography`.

All examples assume a connected `transport` (see
[Plugging in a transport](#plugging-in-a-transport)) and `from ble import ...`
of the names they use.

### A session

A `Session` is one connection. Entering it reads the firmware revision,
refuses anything below 4.6.0, subscribes to notifications, runs the key
exchange in the clear and switches the packet stream to AES. On firmware
4.7.90 and up it also asks for the model, as the app does. Leaving it closes
the transport.

```python
async with Session(transport) as session:
    print(session.firmware, session.model)   # (4, 8, 2), LockModelId.NIMLY_PRO
```

`send(command)` returns the `Response` once the status says success.
`request(command, parser)` also runs one of the parsers in
`protocol/responses.py` on it. Commands go out one at a time with the app's
timing: 20 s to answer, then 320 ms before the next. A session connects once;
after a disconnect, build a new `Session` on a new transport.

Below firmware 4.7.90 every command carries CommandRef 16, so an answer that
turns up after its command timed out looks like the answer to the next one.
The app lives with that. The session narrows it without changing the wire:
after a timeout under the static ref, the next command holds back for
`late_answer_grace` (20 s by default) and drops whatever arrives meanwhile,
and an answer under ref 16 whose id belongs to another command is ignored as
late. A late answer to a command with the same id, after the grace period,
still completes the next one; nothing on the wire tells them apart. The
session docstring has the details.

### Enrolling a factory-reset lock

`enroll` does what the app's `AddLockFragment.finishSetup` does, with local
values where the app fetches the cloud's: log in with the factory credential,
replace the owner key through `UserAuthUpdate`, then set a device id, the
clock, a server key and the name.

```python
async with Session(transport) as session:
    try:
        enrollment = await enroll(session, name="Door")
    except BleEnrollmentError as err:
        if err.enrollment is not None:
            save(err.enrollment.to_dict())   # the lock already has the new key
        raise
save(enrollment.to_dict())
```

The name is at most 8 ASCII characters. The device id defaults to a random 6
bytes from `new_device_id()`, never all zero, which is the factory id.

Once `UserAuthUpdate` has gone through, the factory key presumably no longer
opens the lock, so a failure after that point raises `BleEnrollmentError`
carrying everything the lock has accepted. Store it, and finish on a new
connection:

```python
async with Session(new_transport) as session:
    enrollment = await resume_enrollment(session, partial)
```

`resume_enrollment` logs in with the factory device id until the device id
step is confirmed. If `DeviceIdSet` reached the lock and only its answer was
lost, the lock refuses that id, so on `BleSecurityError` the login is tried
once more with the enrolled id, and if that works the step counts as done. The
retry runs on the same connection, and whether the lock allows a second
`UserAuthBegin` after refusing one is not known. If it drops the link instead,
mark the step done by hand (`replace(partial, completed=partial.completed |
{EnrollmentStep.DEVICE_ID})`) and resume that.

`err.enrollment` is `None` only when `UserAuthUpdate` itself failed. The lock
then usually still has its factory key; if it took the new key and only its
answer was lost, only a factory reset recovers it. A failed factory login
raises the session's own error and has changed nothing: the lock is not
factory-reset.

### Logging in with a stored enrollment

Every later connection logs in with the credential the enrollment gives:

```python
enrollment = Enrollment.from_dict(load())
async with Session(transport) as session:
    await authenticate_owner(session, enrollment.owner_credential)
    ...
```

`owner_credential` sends the enrolled device id once `DeviceIdSet` has gone
through, and the factory id before that. The lock answers a wrong key with a
failed status, most likely `BleSecurityError`.

### PIN codes, RFID and fingerprints

The builders in `commands` check what the app checks before anything is sent:
the slot range, and a PIN of 4-8 digits 0-9. BLE numbers slots differently
from Zigbee (see [slot-numbering.md](../slot-numbering.md)).

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
(`slot`, and a `LockStatusId` or the raw byte). The timeout is the same 20 s
the app uses for every command, which has to cover the tag or finger too.

The library does not apply the app's feature gates. The app offers admin
commands (PIN, RFID, fingerprint, keypad, auto-lock, volume, battery) only
from firmware 4.7.90, and fingerprint, keypad enable and master PIN only on
models whose `LockModelId.features` say so. A caller that wants the same
behaviour checks `session.firmware` and `session.model.features` first.

Lock and unlock, settings and readouts follow the same pattern:

```python
await session.send(commands.ekey_operate(EkeyOperationId.UNLOCK))
await session.send(commands.auto_lock_set(True))
battery = await session.request(commands.batt_info_get(), responses.parse_batt_info)
```

### Events

While a session is open the lock sends two kinds of unsolicited frames,
`LockStatus` (the bolt moved: slot, state, method) and `UserAdded` (a
credential landed in a slot), both under CommandRef 128. They never touch the
command in flight.

```python
def on_event(event: LockEvent) -> None:
    if isinstance(event, LockStatus):
        print(event.slot, event.state, event.method)

remove = session.add_event_listener(on_event)
```

The listener runs on the event loop and must not block. The remover can be
called more than once. An exception from a listener is logged by its type
only, since its message is not ours and could quote anything. Events arrive
only on a live connection; the lock is not known to broadcast them otherwise.

## Plugging in a transport

`client/transport.py` defines the seam. A `Transport` is one lock that is
already connected, and the session needs four calls on it:

| Method                                              | Does                                                                      |
| --------------------------------------------------- | ------------------------------------------------------------------------- |
| `read_software_revision()`                          | Raw value of characteristic 0x2A28, such as `b"4.8.2"`                    |
| `start_notify(on_notification, on_disconnect)`      | Subscribe to the communication characteristic                             |
| `write(data)`                                       | Write one packet to it and return once the write is done                  |
| `close()`                                           | Unsubscribe and disconnect; safe to call twice                            |

`on_notification` gets each notification's bytes, one Layer 1 packet per call,
in arrival order. `on_disconnect` is called when the link drops. Both are
plain functions called on the session's event loop. Scanning, connecting,
service discovery and MTU negotiation stay with whoever builds the transport.
Errors from a transport should be `BleError` subclasses, `BleDisconnectedError`
when the link is gone; the session lets anything else through unchanged.

The UUIDs are exported: `SERVICE_UUID`, `COMMUNICATION_CHARACTERISTIC_UUID`,
`SOFTWARE_REVISION_CHARACTERISTIC_UUID` and `ADVERTISING_UUID`.

The session frames its writes for MTU 23, whatever the link negotiated,
because the app never asks for more and nothing says the lock takes more.
`Session(transport, mtu=...)` changes that, for trying a larger MTU against a
lock; nobody has yet. The
app writes with the characteristic's default write type, which on Android is
a write with response when the characteristic allows it. Which properties the
lock's characteristic has is not recorded, so a transport should use a write
with response and fall back if the characteristic refuses it.

A [bleak](https://github.com/hbldh/bleak) transport is a thin adapter. This
sketch has not run against a lock:

```python
class BleakTransport:
    def __init__(self, device: BLEDevice) -> None:
        self._on_disconnect: DisconnectCallback | None = None
        self._client = BleakClient(device, disconnected_callback=self._disconnected)

    async def connect(self) -> None:
        await self._client.connect()

    def _disconnected(self, _client: BleakClient) -> None:
        if self._on_disconnect is not None:
            self._on_disconnect()

    async def read_software_revision(self) -> bytes:
        return bytes(await self._client.read_gatt_char(SOFTWARE_REVISION_CHARACTERISTIC_UUID))

    async def start_notify(self, on_notification, on_disconnect) -> None:
        self._on_disconnect = on_disconnect
        await self._client.start_notify(
            COMMUNICATION_CHARACTERISTIC_UUID, lambda _char, data: on_notification(bytes(data))
        )

    async def write(self, data: bytes) -> None:
        await self._client.write_gatt_char(COMMUNICATION_CHARACTERISTIC_UUID, data, response=True)

    async def close(self) -> None:
        if self._client.is_connected:
            await self._client.disconnect()
```

bleak calls the disconnect callback on our own `close()` too, which is
harmless: the session ignores a disconnect after it has closed. bleak raises
its own errors, which a real adapter should turn into `BleDisconnectedError`
or `BleTimeoutError`.

In Home Assistant the same adapter works on the client its bluetooth
integration hands out: look the lock up with
`bluetooth.async_ble_device_from_address(hass, address, connectable=True)` and
connect with `bleak_retry_connector.establish_connection`, as other Bluetooth
integrations do. An ESPHome Bluetooth proxy needs nothing extra: Home
Assistant routes the connection through it when the proxy is the closest
adapter, as long as the proxy has active connections enabled. A proxy has only
a few connection slots, so the session should be closed as soon as the work is
done. Because `ble/` may not import Home Assistant, that adapter belongs
outside the package, in the integration. Where exactly is not decided.

Tests use `tests/ble/fake_lock.py`: `FakeLock` holds a lock's lasting state,
and `FakeTransport` is one connection to it that plays the lock side with the
`cryptography` package directly.

## Finding the lock

The lock advertises 8 bytes of service data under the 16-bit UUID `0xFD00`,
read with `parse_advertisement`:

```python
ad = parse_advertisement(service_data[ADVERTISING_UUID])
ad.enrolled            # False while the seed is 00 00 (factory state)
ad.matches(device_id)  # True for the enrolled lock with this device id
```

A factory-reset lock shows seed `00 00` and an id of its own. An enrolled lock
shows a seed and the first 6 bytes of SHA-1(seed || device id), so it never
reveals its device id, and only someone who stored the device id can tell
which lock it is. That is why `Enrollment` keeps it. Nothing has been
captured over the air, so the format is the app's reading of it.

## Storing an enrollment

`Enrollment.to_dict()` gives a JSON-safe dict with bytes as hex, and
`Enrollment.from_dict()` reads it back and validates every field. Error
messages name a bad field, never its value. The `format` field is bumped when
the shape changes.

| Field                    | Secret | What it is                                                                     |
| ------------------------ | ------ | ------------------------------------------------------------------------------ |
| `owner_key`              | Yes    | The 16-byte AES key that answers the owner challenge. Whoever holds it owns the lock. |
| `server_private_key`     | Yes    | Private half of the key pair sent in `ServerKeyUpdate`. Nothing uses it yet, but it would let its holder act as the server the lock trusts. |
| `device_id`              | No, but sensitive | Sent in every login, and the only way to recognise the lock's advertisement, so it lets someone track the lock. |
| `lock_server_public_key` | No     | The lock's answer to `ServerKeyUpdate`                                         |
| `user_id`, `name`, `completed`, `format` | No | Owner user id (0), the name written to the lock, the steps the lock confirmed |

Store the whole dict, and store it as a secret. In Home Assistant that means
the config entry or its own storage, both plaintext on disk, and never in
diagnostics, logs or entity attributes without redaction. `Enrollment`,
`OwnerCredential`, `KeyPair` and `LinkKeys` keep their keys out of `repr`, so
printing one is safe; printing `to_dict()` is not.

## Errors

Everything the library raises is a `BleError`, so one `except` clause catches
it all. `tests/ble/test_package.py` parses every module and fails on a `raise`
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
| `BleEnrollmentError`     | Enrollment stopped partway; carries `step` and the partial `enrollment` (in `client/enrollment.py`)                 |

A malformed notification is logged and dropped, as the app drops it. The
command waiting for an answer then times out, and the `BleTimeoutError` has the
dropped frame's `BleProtocolError` as its cause.

## Rules the code keeps

- **No Home Assistant, no reaching out.** Nothing in `ble/` imports
  `homeassistant`, `zigpy` or `voluptuous`, and no relative import leaves
  `ble/`. That rules out the integration's own `redact.py` too, which is why
  the library keeps secrets out of its messages at the source instead of
  redacting them afterwards.
- **No PIN, key or challenge in a message, a repr or the log.** Errors are
  built from ids, statuses and lengths. Dataclasses holding payloads or keys
  mark those fields `repr=False`. The app's own PinCodeSet error quotes the
  PIN; ours does not. `tests/test_no_pin_exposure.py` walks `ble/` too, and
  `tests/ble/client/test_session.py` checks that no `_LOGGER` call passes a
  value named like a key, PIN, challenge or payload. No log call carries a
  traceback.
- **`cryptography` comes from Home Assistant.** It is a core Home Assistant
  requirement, so it is not in `manifest.json`, where a pin could fight the
  one Home Assistant sets. The tests get it from the `unit` group in
  `pyproject.toml`. `crypto.py` uses only API that both ends of the supported
  Home Assistant range ship.
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

What the tests cover, beyond each builder and parser:

- `protocol/test_const.py` and `client/test_const.py` are a second,
  independent transcription of the app's enums and constants. A typo in
  `const.py` has to be made twice to pass.
- `protocol/test_packet.py` runs a frame through every layer and back.
- `client/test_session.py` checks the wire bytes against framing and AES done
  with `cryptography` directly, so a mistake in the session cannot hide on both
  sides of an assertion.
- `client/test_enrollment.py` runs a full enrollment against the fake lock with
  fixed keys and compares every command with the sequence the app sends, then
  logs in again with the stored enrollment and checks that the factory key is
  refused.
- `test_package.py` holds the layering, the package boundary, the rule that
  only `BleError` is raised, and that every name in `__all__` resolves.

The tests use `asyncio.run` rather than pytest-asyncio, which the `unit` group
does not have.

### Where the vectors come from

No test vector was captured from a lock. Each one is labelled with where it
came from, in a comment above it:

| Label        | Where                     | Meaning                                                                                                     |
| ------------ | ------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `documented` | `tests/ble/vectors.py`    | An example written out in `ble-protocol.md`, itself read from the app. Only PinCodeSet `8832` in slot 803. |
| `derived`    | both vector files         | Assembled by hand from the app's serializer or call site for that frame, cited by class. Proves the builder does what the app's code does. |
| `kat`        | `tests/ble/crypto_vectors.py` | Published known answers: NIST CAVS ECC CDH P-256 COUNT 0, the P-256 generator, SP 800-38A F.1.1 and F.2.1. Independent of the app and of us. |
| `executed`   | `tests/ble/crypto_vectors.py` | Printed by the app's own decompiled crypto classes run on a desktop JDK. Proves the Python matches the app byte for byte. |

The `executed` vectors come from `tests/ble/java/CryptoVectors.java`, which
compiles the app's `Aes128CbcEncrypter`, `Secp256r1SecretExchanger` and byte
helpers together with two stubs (`android.util.Base64`, `kotlin.UByte`) and
prints the results. The app sources are local only (`reversing/` is
gitignored), so the harness runs from the main checkout with any JDK 17 or
newer:

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
for line. It was last run on OpenJDK 27. The app runs on Android, whose
`Cipher` comes from Conscrypt rather than the JDK's SunJCE. Both follow the
same contract, but only a lock can settle it.

## What is verified, and what only a lock can settle

"App code" means read in the decompiled Java, or in the smali where jadx
failed. "JDK run" means the app's own classes produced the same bytes.

| Claim                                                                                           | Status                                  |
| ----------------------------------------------------------------------------------------------- | --------------------------------------- |
| Layer 1-3 layouts, blob header, single/blob split at MTU 23, sequence numbers from 1            | App code                                |
| Every command payload and response layout the library builds or parses                          | App code                                |
| Slot ranges, PIN 4-8 digits, master PIN in slot 0 with the range check off                      | App code                                |
| CommandRef 16 below firmware 4.7.90, 1-127 counter from it; events under ref 128                 | App code                                |
| Timing: 20 s timeout, 320 ms between commands                                                   | App code                                |
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
| That Conscrypt, like SunJCE, returns a full 32-byte ECDH secret                                 | Lock only                               |
| MTU above 23, the characteristic's write type, the advertisement bytes themselves               | Lock only                               |
| That RFID and fingerprint scans send UserAdded before their answer (the fake assumes so)        | Lock only                               |

The guest path (`EkeyUserAuth` 0x17 with a cloud token), the ekey user
commands, `EkeyDeviceInfoGet`/`Set` and `FactoryResetModule` are not
implemented. The guest path needs the vendor cloud, and the rest has no use
without it.

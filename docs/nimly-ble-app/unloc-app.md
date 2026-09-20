# The unloc app: the same BLE protocol, from the guest side

The 2026 Connect Module guide (`docs/manuals/EN-Connect-Module-Installation-Guide-231024-…`)
points the Bluetooth user at unloc: "Do you want to create and share digital
keys? No gateway required. Connect with the unloc-app (BLE)." The Code Pro
guide repeats it. This note is what that app turned out to be.

Short version: unloc ships the *same* `com.nimly.ekey.ble` SDK we already read
in the ekey app, at version 1.1.1 against the ekey app's 1.1.0, byte for byte
the same protocol. It uses the guest half of it. It never becomes the owner of
a lock, it holds no PIN, fingerprint or RFID command, and the key material it
authenticates with is handed to it by unloc's own cloud. "No gateway required"
means no Zigbee hub, not no cloud.

Labels as in [ble-protocol.md](ble-protocol.md): **(app code)** is read in the
decompiled source, **(inference)** is reasoning on top of it, **(vendor doc)**
is the vendor's own text.

## What was examined

| | |
| --- | --- |
| Package | `ai.unloc.unloc` |
| Version | 5.9.0 (versionCode 2318) |
| Source | APKPure via `apkeep`, 2026-09-20 |
| sha256 (xapk) | `c1ee02695d0cc4b8d2eacbab925f166157c4c670656f2211fe7213f54ca2ae98` |
| sha256 (base apk) | `0991df54ae5028968ad8a15d224cbd4e8e67cfab961261d7cc939703aba4301e` |
| Decompiled to | `reversing/unloc-decompiled/` with `jadx`, gitignored |
| Baseline | [app-versions.md](../nimly-connect-app/app-versions.md), with every other app in the family |

The app is Kotlin, obfuscated with R8, but the vendor SDKs inside it keep their
package names. Unloc is a hardware-agnostic key platform: Danalock, Master Lock,
Salto, dormakaba dKey, Gantner, ARX, Parqio and Nimly all sit side by side in
the same binary, each as its own vendor driver.

### Looking for source first

There is no public BLE SDK. `developer.unloc.app` documents a REST API for key
management only (access groups, keys, locks, lock connections, webhooks), and
its lock-connection endpoints cover Danalock, Master Lock, Parqio and virtual
locks; the guide text names ARX and Salto as onboarded by unloc staff. Nimly is
not in the public API surface at all, though unloc's own help centre documents
Nimly locks and their BLE errors. `github.com/UNLOC` holds forks of
`flutter_blue`, `flutter_secure_storage` and a permission handler, a Postman
collection and Ruby partner-API examples. Nothing protocol-level. **(vendor doc)**

## Same SDK, same protocol

`com/nimly/ekey/ble/` in the unloc APK has the same 166 files as the ekey app's
copy (175 files either way, one renamed `R` class aside), and the classes that matter are identical after decompiler noise:
`Constants` (same service UUID `ba4bfd00-…`, same characteristic `ba4bfd03-…`,
same 16-bit advertising UUID `0xFD00`, same `DefaultEncryptionKey` of sixteen
`0x11`, same IV of sixteen `0x22`, same firmware floors 4.6.0 and 4.7.90),
`CommandId`, `ResponseStatusId`, `LockModelId` (same fifteen models through
`NimlyTwist2(37)`), the framing, the secp256r1 exchanger and the AES-128-CBC
encrypter. **(app code)**

That is worth more than it sounds: two unrelated vendors ship the same
protocol, so the library in `custom_components/onesti_lock/ble/` is not built
on one app's quirk. It also means unloc gives us nothing new about PIN codes,
fingerprints, RFID or owner enrollment. Those commands exist in the SDK but the
unloc app links the `serviceprovider` variant, which does not expose them.

## What unloc can actually do to a lock

`com.nimly.ekey.serviceprovider.devices.INimlyEkeyDevice` is the whole surface:
`connect`, `disconnect`, `ekeyAuth`, `lock`, `unlock`, `invalidate`,
`getEkeyDeviceInfo`, `setEkeyDeviceInfo`. **(app code)**

`invalidate` is `EkeyOperate 0x18` with operation id 3, `InvalidateToken`,
next to `Unlock(1)` and `Lock(2)` — the revocation path for a guest key.
`EkeyDeviceInfoGet`/`Set` carry an opaque `serverInfo` blob the app reads out of
and writes back into the lock, tracked in the key's metadata as
`nimlyLastDeviceInfoUpdated`. What is in the blob is not visible from the app:
unloc treats it as bytes. **(app code)**

No `PinCodeSet`, no fingerprint, no RFID, no `UserAuthBegin`/`Update`, no
`DeviceIdSet`, no `FactoryResetModule`. Unloc is a key that opens a door, not an
administration tool.

## How unloc becomes able to open a lock

It does not become the owner. It authenticates as an ekey guest with material
it gets from its own backend, exactly the cloud-bound path
[ble-auth-provisioning.md](ble-auth-provisioning.md) describes and our
enrollment deliberately avoids.

The driver (`k8/a.java`, a five-state machine: scan → connect → authorize →
read device info → operate) reads four fields out of the unloc key's vendor
metadata JSON: `nimlyToken`, `nimlySessionPublicKey`, `nimlyUserId` and
`nimlyLastDeviceInfoUpdated`. Token and session public key are base64. Missing
any of them is error 14002, "Missing vendor key data". They go straight into
`ParamEkeyAuth(userId, deviceId, sessionPublicKey, token)`, and
`NimlyEkeyDevice.ekeyAuth` does what the ekey app does: generate an ephemeral
secp256r1 pair, ECDH against the session public key, take the first 16 bytes as
an AES-128-CBC key, encrypt the 32-byte token with the link IV, and send
`EkeyUserAuth 0x17`. **(app code)**

The lock's device id comes from the unloc lock identifier, base64 from
character 6 onwards. **(app code)**

So the chain is unloc cloud → unloc app → BLE, with the ekey cloud somewhere
upstream of unloc's backend, since only the lock owner can mint an ekey with
`EkeyUserAdd 0x1B`. **(inference)** The BLE hop is local and the Zigbee hub is
genuinely gone, which is what the guide's "no gateway required" claims; the
cloud is not.

For `hacs-onesti-101q6uq` this closes a question rather than opening one. The
guest path ends in someone else's app, and unloc is that app for a second time.
Nothing here suggests a way to hand a key to another person's phone from Home
Assistant.

## How the app scans, and what it expects in the advertisement

This is the part that touches our open advertisement questions.

`BleScanner.startScanning` calls `BluetoothLeScanner.startScan(ScanCallback)` —
the one-argument overload. No `ScanFilter`, no `ScanSettings`. **(app code)**
Android's defaults then apply: `SCAN_MODE_LOW_POWER` and legacy-only
advertising, since `ScanSettings.Builder` defaults `setLegacy(true)`.

Two consequences, both **(inference)** from that code:

- The official apps cannot see extended advertising either. If unloc finds a
  lock that our legacy-only ESP32 proxy cannot, extended advertising is not the
  reason. That removes hypothesis (e) from `hacs-onesti-2ctmf8w` and the
  extended-advertising branch of `hacs-onesti-3y0crhl`.
- Nothing in the scan path is special. There is no vendor scan mode, no
  connectable probe, no cloud or hub call before scanning in either variant of
  the SDK. Whatever made a lock appear when "Add device" was opened, it was not
  the BLE code.

Filtering happens in software, per result, against a list of device ids the
caller sets. `getNimlyEkeyScanResult` reads the service data for `0xFD00`,
takes 2 bytes of seed and 6 bytes of identifier, and either recognises the
all-zero seed (an un-enrolled lock, identifier is the device id byte-reversed)
or checks that the identifier equals `SHA-1(seed || deviceId)[:6]`. Anything
past those 8 bytes is never read. **(app code)** That is the same parse our
`ble/protocol/advertisement.py` implements, now confirmed from a second app.

### What this says about the 10-byte observation (`hacs-onesti-36iipsj`)

Nothing is settled without raw hex, but the field narrows:

- Two extra bytes *after* the 8 are harmless. Both apps would parse such an
  advertisement correctly, and unloc is a shipping product that finds Nimly
  locks in the field. Two extra bytes *before* or *inside* the fields would
  break unloc as surely as they would break us. **(inference)**
- The likeliest reading of "10 bytes of service data" is a tool reporting the
  whole AD structure, 2 bytes of 16-bit UUID plus 8 bytes of payload, rather
  than the payload Android's `getServiceData(uuid)` hands the app.
  **(inference)** Only the raw hex decides it.
- A name in the advertisement is expected, not an anomaly. The SDK reads
  `scanResult.getDevice().getName()` and special-cases the factory name
  `GlennI`, rewriting it to `Nimly`; `DeviceNameSet` lets an owner store a name
  of up to 9 ASCII characters in the lock. A lock called `Dør` is a lock
  somebody named. **(app code)**

### What it says about advertising at all

The ekey app's "Add device" screen scans for exactly 10 seconds with the device
id list set to the all-zero `DefaultDeviceId`, so it only surfaces locks that
are not enrolled. Its own help popup, reachable from that screen, says: install
the module, "To activate pairing mode, remove and reinsert the
batteries/power… The module will enter pairing mode for about four minutes
(indicated by blue LED blinking for bluetooth or orange blinking for Zigbee
3.0)." **(app code, quoting the app's own dialog)**

Unloc's side is the counterweight. Its scan state runs for 20 seconds and fails
with error 14010, "Lock Not Found", which is the error its public help centre
documents for a Nimly lock out of range. It scans for an *enrolled* lock, by
SHA-1 identifier, with no pairing window and no physical act by the user.
**(app code)** A product that opens doors this way requires an enrolled module
to advertise during ordinary use. **(inference)**

Read together: a module that nobody has enrolled over BLE may well advertise
only in the four-minute pairing window after a power cycle, while an enrolled
one advertises in normal operation. Fredrik's module has never been enrolled
over BLE. That is consistent with every measurement so far, including the empty
ESP32 proxy, and it makes the battery-pull pairing window
(`hacs-onesti-5fvt04o`) the measurement most likely to produce a first
advertisement — not the "open Add device and wait" attempt. **(inference)**
It also fits the vendor's own claim that Bluetooth is only present on newer
module revisions without settling it either way.

## What we do not know

- Whether unloc's backend talks to the ekey cloud, and with what. Not visible
  statically; it would take MITM of `api.unloc.app`, which is a different
  project from the ekey MITM already planned.
- What `serverInfo` in `EkeyDeviceInfoGet`/`Set` contains. Plausibly time and
  revocation state for offline validation, but the app treats it as opaque and
  so must we.
- Whether an enrolled module advertises continuously or only while awake. The
  20-second unloc scan window says "often enough for a person standing at the
  door" and nothing more precise.

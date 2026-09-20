# App versions: the 2026 baseline, and how to diff it later

Everything this repo knows about the BLE protocol and the iotiliti cloud was
read out of apps that were decompiled in the spring and autumn of 2026. Apps
ship again. This file is the record of exactly which builds those readings came
from, and of what the whole white-label family looked like on 2026-09-20, so a
later fetch can answer "what is new" without anyone reading three million lines
of decompiled JavaScript a second time.

The reason it is worth repeating: the brands do not update in step. On the day
this was written, Homely was on Android 1.28.61 and Tekam on 1.22.44, six minor
versions behind, from the same codebase. An app that is ahead carries the
command ids, API fields and feature flags the others have not shipped yet, and
one that is behind still carries what the newer ones removed. Reading the
leader is a cheap way to see where the product is going, and the lag is what
makes the comparison possible at all.

`scripts/fetch_manuals.py --only appstore --only android` refetches every row
below from the two stores and writes the new versions into the Living sources
table in `docs/manuals/README.md`. That run costs a minute and needs no APK.
Decompiling is the expensive step, and the store rows are what tells you
whether it is worth doing.

## What has actually been decompiled

Nothing from these builds is in git: the APKs, the decompiled trees and the
extracted secrets are all under `reversing/` or in `secrets.md`, both
gitignored.

| App | Package | Version | versionCode | Fetched | Artefact and sha256 | Local tree |
| --- | ------- | ------- | ----------- | ------- | ------------------- | ---------- |
| nimly BLE (ekey) | `easyaccess.ekey.app` | 1.5.2 | 13 | 2026-03-30 | `base.apk` `8589c7c0c8c448971f6ce540d1bdc04b32ca99cf1a111575db8ce900d9918c70` | `reversing/nimly-ble-decompiled/` (jadx, apktool smali where jadx failed) |
| nimly connect | `com.easyaccess.connect` | 1.27.84 | 278 | 2026-03-30 | `com.easyaccess.connect.xapk` `84cad04ad57c4b5a49ceaf02f48b0cf69e4bf9268cb9d3a2dd0d17cd91b60cba` | `reversing/nimly-connect-decompiled/` and `nimly-connect-decompiled.js` (jadx + hermes-dec, 3.2M lines) |
| unloc | `ai.unloc.unloc` | 5.9.0 | 2318 | 2026-09-20 | `ai.unloc.unloc.xapk` `c1ee02695d0cc4b8d2eacbab925f166157c4c670656f2211fe7213f54ca2ae98`, base apk `0991df54ae5028968ad8a15d224cbd4e8e67cfab961261d7cc939703aba4301e` | `reversing/unloc-decompiled/` (jadx) |

The hole this table used to have was the seven white-label builds decompiled on
2026-03-30 with `apkeep` + `hbc-decompiler`. The brand table in
[reversing-notes.md](reversing-notes.md#white-label-decompilation-2026-03-30)
was written from them and then none of them were kept, not even their version
numbers, so nothing in that table could be re-checked. That is closed now, not
by recovering the March builds (they are gone, and APKPure serves only the
current release of a package) but by keeping the September ones. The March
column in that table should be read as "from builds nobody can name"; the
September artefacts below are what a future diff runs against.

## The APKs kept, 2026-09-20

Thirteen packages pulled the same day with `apkeep -d apk-pure`, plus the BLE
app, which is still the March copy off Play because APKPure has stopped
listing `easyaccess.ekey.app` at all (`apkeep -l` returns an empty version
list, and a download writes no file). Version and versionCode are parsed out of
`AndroidManifest.xml` inside each file, not read off a store page, so they can
be checked again from the artefact alone. Every one of the thirteen matches
what the APKPure row in [the manuals index](../manuals/README.md#living-sources)
says, which is the first time those store rows have been verified against the
files they describe.

Paths are relative to `reversing/`. Two file kinds: `.apk` is a single
Play-style APK, `.xapk` is APKPure's zip of a split install, and the sha256 is
of the file as downloaded.

| Brand | Package | Version | versionCode | Size | Path | sha256 |
| ----- | ------- | ------- | ----------- | ---- | ---- | ------ |
| Nimly Connect | `com.easyaccess.connect` | 1.28.46 | 292 | 161.9 MB | `apks/nimly-connect/com.easyaccess.connect-1.28.46-292.xapk` | `f3eb582c62428873ceef2c46902215564afd504cf99780e6303b7eb53f9315c6` |
| nimly BLE | `easyaccess.ekey.app` | 1.5.2 | 13 | 15.4 MB | `nimly-ble-apks/easyaccess.ekey.app-1.5.2-13.apk` | `8589c7c0c8c448971f6ce540d1bdc04b32ca99cf1a111575db8ce900d9918c70` |
| unloc | `ai.unloc.unloc` | 5.9.0 | 2318 | 31.6 MB | `apks/unloc/ai.unloc.unloc-5.9.0-2318.xapk` | `c1ee02695d0cc4b8d2eacbab925f166157c4c670656f2211fe7213f54ca2ae98` |
| iotiliti | `io.iotiliti.home` | 1.28.46 | 906 | 161.3 MB | `apks/iotiliti/io.iotiliti.home-1.28.46-906.xapk` | `4d525adda6c2a59adf8691d4b760f22d20cab2c997c2a241c74cff2a71516b1f` |
| Copiax | `com.copiax.homesecurity` | 1.28.46 | 333 | 160.7 MB | `apks/copiax/com.copiax.homesecurity-1.28.46-333.xapk` | `0b03e569c73821a13e41c00442dc3f61bdb7652bcd5e00acef50e44176956c68` |
| Homely | `io.homely.home` | 1.28.61 | 627 | 131.3 MB | `apks/homely/io.homely.home-1.28.61-627.xapk` | `68f559b56a334c694fef9c30a0ff5b06b31bc93bf2411df4f218238fc2bd846a` |
| Keyfree | `com.safe4.keyfree` | 1.27.23 | 474 | 170.5 MB | `apks/keyfree/com.safe4.keyfree-1.27.23-474.apk` | `f995c603df9d02e098eaabfdfcba9a5244d80e03e8471e6fe9b07583e3467e09` |
| Salus Immunity | `com.salusprotekt.immunity` | 1.25.62 | 56 | 119.9 MB | `apks/salus/com.salusprotekt.immunity-1.25.62-56.xapk` | `63f7a11fc44253da25a4a5effd023d607f7eda8f3b0645b070750811074da7b2` |
| Förebygg | `se.forebygg.forebygg` | 1.24.78 | 121 | 80.7 MB | `apks/forebygg/se.forebygg.forebygg-1.24.78-121.apk` | `8d24ba287c72b8557afdd69f51cd3694eb6635ad7370d0346ed4408a8e26cf32` |
| Tekam Smarthus | `no.tekam.smarthus` | 1.22.44 | 192 | 83.9 MB | `apks/tekam/no.tekam.smarthus-1.22.44-192.apk` | `d7ee5e25e5f87b22576d6b6b32c72570ab67923f70f712907c1f3e0744f4bbf1` |
| Folklarm | `com.folklarm.appsolutsakerhet` | 1.25.49 | 183 | 82.2 MB | `apks/folklarm/com.folklarm.appsolutsakerhet-1.25.49-183.apk` | `d0d55ba93bd4bc2c8705d9420edba1bf50cfc48b2986e380c2ea3ca48e5a848a` |
| Tryg Smart | `com.tryg.smart` | 1.24.73 | 156 | 79.9 MB | `apks/tryg-smart/com.tryg.smart-1.24.73-156.apk` | `4ea1cb9d282b91ec4156cf383aae690cdaff8f2b127b97da80ec0f67ebc07dc9` |
| Confi.care | `com.safelyteam.safely` | 1.20.9 | 72 | 91.9 MB | `apks/confi-care/com.safelyteam.safely-1.20.9-72.apk` | `9f28cc24b7bb39d64e5efa8c88d9c0f2dff6d6c884004de748fda85b23029796` |
| Larmify | `se.larmify.larmify` | 1.27.84 | 43 | 170.9 MB | `apks/larmify/se.larmify.larmify-1.27.84-43.xapk` | `93468ebf0ea627cec95533957e725ff806e495b4e67ec1577f7489f7f4097338` |

The unloc file is byte for byte the one already recorded above, so that fetch
reproduced. `reversing/com.easyaccess.connect.xapk` is still the 1.27.84 build
the cloud readings came from; the 1.28.46 one beside it is newer and not yet
read.

### nimly home has no Android build

`com.nimly.nimly` is not on Google Play: the package page answers 404, and Easy
Access AS's developer listing shows two apps, nimly connect and nimly BLE.
APKPure has no versions for it either. Nothing in the family's Android packages
looks like a rename of it, so on 2026-09-20 the app is iOS only and cannot be
fetched with `apkeep`.

Getting the iOS build is a different job and was not done. The App Store serves
IPAs only to a signed-in Apple ID that has "bought" the app (free counts), so
every route needs an account: `ipatool` or a similar client logging in with an
Apple ID and downloading the entitled copy, a device backup of an installed
app, or a jailbroken device. There is no anonymous mirror worth trusting, and
the decrypted binary is what matters anyway, since the App Store copy is FairPlay
encrypted and a dump off a device is the only way past that. If the app ever
matters more than the guesswork, the cheapest honest route is a throwaway Apple
ID plus a device, and it is a decision for Fredrik, not something to do quietly.

## The store baseline, 2026-09-20

Every app in the family, on both stores, on the same day. The Android numbers
come from APKPure, which mirrors on its own schedule and can sit a release
behind Play: it had the BLE app on 1.5.1 while our own copy off Play is 1.5.2.
Every other Android row here has since been checked against the downloaded
file's own manifest and agrees exactly, so the mirror's numbers are trustworthy
even where its files are not current.
The iOS and Android version strings are not the same scheme, so compare each
column with itself over time, not the two against each other.

| Brand | Android package | Android version (versionCode) | Published | iOS app | iOS version | iOS released |
| ----- | --------------- | ----------------------------- | --------- | ------- | ----------- | ------------ |
| Nimly Connect | `com.easyaccess.connect` | 1.28.46 (292) | 2026-05-18 | `com.easyaccess.connect` | 1.28.0 | 2026-05-05 |
| nimly BLE | `easyaccess.ekey.app` | 1.5.1 (12) | 2025-11-15 | `com.easyaccess.EasyAccess-eKey` | 1.5.0 | 2025-06-08 |
| nimly home | not on Play | - | - | `com.nimly.nimly` | 1.0 | 2026-09-12 |
| unloc | `ai.unloc.unloc` | 5.9.0 (2318) | 2026-09-13 | `ai.unloc.Unloc` | 5.11.8 | 2026-09-14 |
| iotiliti | `io.iotiliti.home` | 1.28.46 (906) | 2026-09-07 | `io.iotiliti` | 1.28.0 | 2026-05-05 |
| Copiax | `com.copiax.homesecurity` | 1.28.46 (333) | 2026-07-29 | not found | - | - |
| Homely | `io.homely.home` | 1.28.61 (627) | 2026-06-11 | `io.homely.home` | 1.28.0 | 2026-06-09 |
| Keyfree | `com.safe4.keyfree` | 1.27.23 (474) | 2025-06-23 | `com.safe4.keyfree` | 1.27.0 | 2025-05-07 |
| Salus Immunity | `com.salusprotekt.immunity` | 1.25.62 (56) | 2025-02-26 | `com.salusprotekt.immunity` | 1.28.0 | 2026-05-30 |
| Förebygg | `se.forebygg.forebygg` | 1.24.78 (121) | 2024-11-06 | `se.forebygg.forebygg` | 1.27.45 | 2025-10-16 |
| Tekam Smarthus | `no.tekam.smarthus` | 1.22.44 (192) | 2026-05-05 | `no.tekam.tekamsmarthus` | 1.28.0 | 2026-05-07 |
| Folklarm | `com.folklarm.appsolutsakerhet` | 1.25.49 (183) | 2024-05-10 | not found | - | - |
| Tryg Smart | `com.tryg.smart` | 1.24.73 (156) | 2024-05-22 | `com.tryg.smart` | 1.24.1 | 2023-11-14 |
| Confi.care (Safe4 Care) | `com.safelyteam.safely` | 1.20.9 (72) | 2022-09-10 | `com.safelyteam.safely` | 1.28.1 | 2026-05-13 |
| Larmify | `se.larmify.larmify` | 1.27.84 (43) | 2026-05-05 | `se.larmify.larmify` | 1.28.0 | 2026-05-05 |
| LF (Länsförsäkringar) | none | - | - | none | - | - |

What that table says on the day it was made:

- **nimly home is new.** `com.nimly.nimly` 1.0, published 2026-09-12 by Easy
  Access AS, eight days before this was written, iOS only so far and not in any
  earlier note. Whether it replaces nimly connect, folds in the BLE app, or is
  something else entirely is unknown; nobody has opened it. It is the single
  most interesting thing to decompile next.
- **The leaders are Homely (1.28.61) and the neutral clone (1.28.46).** If a
  new cloud field or DoorlockType appears anywhere first, it appears there.
- **The laggards are Confi.care on Android (1.20.9, from 2022) and Tryg
  Smart.** Confi.care's own iOS build is on 1.28.1, so that brand is four years
  apart between its two platforms, which makes it the best pair for seeing what
  was removed from the codebase rather than added. The Android build is branded
  Safely, not Confi.care, and probably predates a rename; see the tenant roster
  in [app-architecture.md](app-architecture.md#the-tenant-roster).
- **Larmify Android is on 1.27.84**, the same build string as our decompiled
  nimly connect. Whatever we read there holds for it.
- **LF has no app of its own.** It only exists as a brand block inside the
  iotiliti build, as do Safe4 Care's server config and Tryg's.
- **Copiax has two products.** `com.copiax.homesecurity` on Android is the
  iotiliti white-label; the CopiApp on the App Store (`se.copiax.copiapp.ios`,
  1.3.11) has different numbering and is probably a different product. Not
  verified either way.

## What to compare

These are the values the integration actually rests on. A re-decompilation is
worth the effort if it moves one of them, and the point of listing them with
their current values is that the check is a grep, not a read.

### BLE, from `easyaccess.ekey.app` 1.5.2 and `ai.unloc.unloc` 5.9.0

Both ship the same `com/nimly/ekey/ble/` SDK, at 1.1.0 in the ekey app and
1.1.1 in unloc, byte for byte the same protocol. Full detail in
[ble-protocol.md](../nimly-ble-app/ble-protocol.md).

| What | Baseline value | Where in the SDK |
| ---- | -------------- | ---------------- |
| Service UUID | `ba4bfd00-c447-19bf-f38d-4890b3a824c8` | `settings/Constants` |
| Characteristic | `ba4bfd03-c447-19bf-f38d-4890b3a824c8` | same |
| Advertising UUID | `0xFD00` | same |
| Default encryption key | `0x11` x 16 | same |
| Default IV | `0x22` x 16 | same |
| Firmware floor, connect | 4.6.0 | same |
| Firmware floor, admin commands | 4.7.90 | `NimlyEkeyDevice.feature()` |
| Command ids | 35 values, `ExchangeKeyPubM` 0x01 through `FactoryResetModule` 0x70 | `communication/commands/CommandId` |
| Frame types | 7 values, `Single` 0x01 through `Nac` 0x07 | framing |
| Lock models | 14 values, `EasyFingerTouch` 8 through `NimlyTwist2` 37, three feature flags each | `responses/shared/LockModelId` |
| Slot ranges | fingerprint 150-199, RFID 900-999, ekey/BLE 800-899 | the command classes' own range checks |

A new command id, a new model id or a raised firmware floor are the three
changes that would matter most: the first two say the lock got a feature, the
third says our floor is wrong.

### Cloud, from `com.easyaccess.connect` 1.27.84

Detail in [reversing-notes.md](reversing-notes.md) and the OpenAPI spec beside
it.

| What | Baseline value |
| ---- | -------------- |
| Prod API (Nimly) | `api-neutralclone.iotiliti.cloud`, migrating to `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` |
| Per-brand API hosts | 12 hosts, the table in reversing-notes |
| Internal test API | `test-api-neurosys.iotiliti.cloud` |
| Auth | OAuth2 `POST /oauth/v2/token`, client_id `account`; AWS Cognito eu-central-1 as the alternative |
| Door lock endpoints | 19 paths under `/devices/{id}/…` |
| Keybox endpoints | 3 paths under `/keybox/…` |
| Company ids | one GUID per brand, header `companyId` |
| Access types | `DeviceAccessMethodType` |
| Cert pinning | none observed |

The brand config block is the cheap win here: it is one object in the bundle,
it names every brand the platform runs, and a brand appearing or disappearing
in it is a fact about the business, not just the app.

## Homely 1.28.61 against Tekam 1.22.44, 2026-09-20

The first check the version spread was collected for: take the leader and a
laggard on the same afternoon and see whether the lag actually shows. It does.

Both apps are React Native. The whole app is one Hermes bytecode file,
`assets/index.android.bundle`, 15.7 MB in Homely and 11.3 MB in Tekam, and the
two were built with different Hermes versions (bytecode 96 against 84), which is
itself six minor versions of toolchain drift. Neither was decompiled: the
comparison is over the string literals in the bundle, read either as a window of
printable bytes around a needle or out of the small string table. That is enough
for names and hosts and not enough for numbers, so the command ids and the model
ids in the BLE table below were not checkable this way at all.

**Same codebase, confirmed.** Both carry the same enum and model names
(`DoorlockType`, `DoorlockModelId`, `DoorlockVolumeValues`,
`DeviceAccessMethodType`, `NimlyPRO`, `NimlyTouch`, `NimlyCode`,
`YaleDoormanV2`, `YaleDoormanL3`), the same `POST /oauth/v2/token`, the same
`companyId` header, and, more telling than any of that, each build ships the
brand host block for brands it has nothing to do with. The Tekam app knows
Keyfree's, Förebygg's and Tryg's API hosts; the Homely app knows LF's,
Salus's and Safe4 Care's. One build per brand, one source tree.

**Neither app carries the BLE SDK.** The service UUID `ba4bfd00-…`, the
`CommandId` names and `LockModelId` are absent from both bundles. The BLE rows
of the baseline can only be rechecked against the ekey app and unloc, never
against a cloud app, so the firmware floors and the 35 command ids stand
unchanged and unchallenged by this round.

**What the leader has that the laggard does not.** All of these appear once in
Homely 1.28.61 and zero times in Tekam 1.22.44:

| Kind | In Homely only |
| ---- | -------------- |
| Model ids | `NimlyCodePRO`, `NimlyIn`, `NimlyShared`, `NimlyKeybox`, `NimlyGatewayWifiPro` |
| Event types | `DoorlockAccessScanRequested`, `DoorlockLockedByPinchGesture`, `DoorlockTampered`, `DoorlockUnintegrated`, `DoorlockWithKeypadLink` |
| Endpoints | the whole `/keybox/…` family, eight literals against none |

So the hypothesis holds: reading the brand that is ahead does show product the
others have not shipped. `NimlyCodePRO` is the model this integration already
special-cases, and it simply does not exist in the Tekam build. The caveat is
that absence in one bundle is absence from that build, not from the platform:
dead code is stripped, and a brand that sells no keyboxes gets no keybox screens.
A name present in the leader is evidence; a name missing from the laggard is
only a hint.

**The API host scheme differs between the two, in the direction nobody
expected.** For brands both builds know:

| Brand | Homely 1.28.61 (newer) | Tekam 1.22.44 (older) |
| ----- | ---------------------- | --------------------- |
| Keyfree | `api-keyfree.iotiliti.cloud` | `api.customer.keyfree.iotiliti.cloud` |
| Förebygg | `api-forebygg.iotiliti.cloud` | `api.customer.forebygg.iotiliti.cloud` |
| neutralclone | `api-neutralclone.iotiliti.cloud` | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` |

The `onesti.aws.neurosys.pro` migration the baseline records from nimly connect
1.27.84 is in the older Tekam build (five hosts) and completely absent from the
newer Homely one (zero). Either the migration was rolled back, or the two
builds were cut from branches that disagree, or the app version string does not
order these builds the way it looks like it does. This is unresolved and should
not be written down anywhere as "they moved to AWS".

**One brand nobody had on the list.** Tekam's host block names `waoo`
(`api.customer.waoo.iotiliti.cloud` and its test host), eight literals, and
Homely's does not. Waoo is a Danish ISP with no app of its own, the way LF is.
Following that up over all twelve builds turned up six more brands nobody had
written down and a tenant roster that shrinks from build to build; the table is
under "The tenant roster" in
[app-architecture.md](app-architecture.md#the-tenant-roster).

One loose end worth noting for the next round: the Homely build has no
production host for its own brand in the bundle, only `stage-api-homely` and
`test-api-homely`, and the Tekam build has no Tekam host at all. Their own
brand's endpoint is presumably in the native config rather than the JS, which
means a brand's own prod host is the one thing you cannot read out of its own
bundle.

## Diffing a new decompilation

The tree is not comparable. jadx and hermes-dec both rename classes, fields and
locals on every run, and a diff of two full decompilations is tens of thousands
of lines of noise with the real change buried somewhere in it. Compare values,
not files.

1. **Check the stores first.** `python3 scripts/fetch_manuals.py --only
   appstore --only android`, then `git diff docs/manuals/README.md`. If
   nothing moved, stop. If something moved, note which brand is furthest ahead
   and pull that one, not necessarily Nimly's.
2. **Pull the APK.** `apkeep -a <package> -d apk-pure <dir>` (APKPure mirrors
   Play but can lag a release, and it drops packages entirely: it no longer
   serves the BLE app at all. For the current build, pull from a device with
   `adb shell pm path <package>` + `adb pull`). Read version and versionCode out
   of the file's own `AndroidManifest.xml` rather than off the store page, take
   its sha256, and add it to the APK table above. Keep the file: APKPure serves
   only the current release, so a build nobody kept is a build nobody can go
   back to.
3. **Decompile into `reversing/`.** jadx for the Kotlin apps, jadx +
   hermes-dec for the React Native ones. Never into the repo: `.gitignore`
   covers `reversing/`, `*.apk`, `*.xapk` and `jadx-out/`, and it is meant to.
4. **Diff the values, one grep per row of "What to compare" above.** For the
   BLE apps the files that matter are `com/nimly/ekey/ble/`: `settings/
   Constants`, `communication/commands/CommandId`, the `Command*` classes'
   `serializeCommand` and range checks, `responses/shared/LockModelId`,
   `ResponseStatusId`, the framing, the secp256r1 exchanger and the AES
   encrypter. For the Hermes apps it is the brand config object, the API URL
   constants, the endpoint string literals and the `DeviceAccessMethodType` /
   `DoorlockType` enums. Everything else is UI.
5. **Compare enums as sorted lists, not as source.** Pull the names and values
   out of each version into a text file and `diff` those two files. That turns
   "did a command id appear" into one line of output.
6. **Cross-check the brands against each other, not only against last time.**
   The same grep run over the leader and the laggard in the same afternoon
   shows what is on its way in and what is on its way out. That is the whole
   reason for keeping the version table above.
7. **Write the result here**, as a new row in the decompiled table and a change
   to the baseline values, and in `ble-protocol.md` or `reversing-notes.md`
   where the detail lives. If nothing moved, say so with a date: "checked
   1.29.x, no change" is worth as much as a finding and saves the next round.

No app code, no decompiled source and no extracted secret goes into the repo.
Values, version numbers and hashes do.

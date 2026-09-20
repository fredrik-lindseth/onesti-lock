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

Four builds. Nothing from them is in git: the APKs, the decompiled trees and
the extracted secrets are all under `reversing/` or in `secrets.md`, both
gitignored.

| App | Package | Version | versionCode | Fetched | Artefact and sha256 | Local tree |
| --- | ------- | ------- | ----------- | ------- | ------------------- | ---------- |
| nimly BLE (ekey) | `easyaccess.ekey.app` | 1.5.2 | 13 | 2026-03-30 | `base.apk` `8589c7c0c8c448971f6ce540d1bdc04b32ca99cf1a111575db8ce900d9918c70` | `reversing/nimly-ble-decompiled/` (jadx, apktool smali where jadx failed) |
| nimly connect | `com.easyaccess.connect` | 1.27.84 | 278 | 2026-03-30 | `com.easyaccess.connect.xapk` `84cad04ad57c4b5a49ceaf02f48b0cf69e4bf9268cb9d3a2dd0d17cd91b60cba` | `reversing/nimly-connect-decompiled/` and `nimly-connect-decompiled.js` (jadx + hermes-dec, 3.2M lines) |
| unloc | `ai.unloc.unloc` | 5.9.0 | 2318 | 2026-09-20 | `ai.unloc.unloc.xapk` `c1ee02695d0cc4b8d2eacbab925f166157c4c670656f2211fe7213f54ca2ae98`, base apk `0991df54ae5028968ad8a15d224cbd4e8e67cfab961261d7cc939703aba4301e` | `reversing/unloc-decompiled/` (jadx) |
| Keyfree, Salus, Forebygg, Homely, Copiax, Tekam, iotiliti | see below | unknown | unknown | 2026-03-30 | not kept | gone |

That last row is the hole in the record. Seven white-label builds were
decompiled on 2026-03-30 with `apkeep` + `hbc-decompiler`, the brand table in
[reversing-notes.md](reversing-notes.md#white-label-decompilation-2026-03-30)
was written from them, and then none of them were kept, not even their version
numbers. Nothing in that table can be re-checked locally, and the next round
should keep at least the config block and the version of each.

## The store baseline, 2026-09-20

Every app in the family, on both stores, on the same day. The Android numbers
come from APKPure, which mirrors on its own schedule and can sit a release
behind Play: it had the BLE app on 1.5.1 while our own copy off Play is 1.5.2.
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
  was removed from the codebase rather than added.
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
   Play but can lag a release; for the current build, pull from a device with
   `adb shell pm path <package>` + `adb pull`). Record version, versionCode and
   the sha256 of what you got, and add it to the first table here.
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

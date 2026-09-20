# Manufacturer manuals and source material

Manufacturer PDFs, kept here so the slot-numbering rules can be checked offline, plus the other primary sources that belong next to them: Zigbee sniffs, logs, a device diagnostics dump and one code snapshot. The `.txt` files next to a PDF are `pdftotext -layout` extracts. Everything in this folder is gitignored; only this README is tracked.

Run `python3 scripts/fetch_manuals.py` to download it all. Each row in the Sources table carries a type, and the script acts on it: a PDF gets a text extract, a zip or a repo snapshot is unpacked into a folder beside the archive, a `.txt` or `.json` is just stored.

The same script keeps a second table, [Living sources](#living-sources): every forum thread, GitHub issue and code file anyone has written about these locks, dated, with what it looked like when it was last read. That is the one to run when the question is "has anything happened since last time".

The manuals were retrieved 2026-09-19 from the manufacturer's own domains (nimly.se, easyaccess.no); the rest was added 2026-09-20 from the sources named in the table. Date is the date encoded in the manufacturer's filename (DDMMYY), unless marked `*`, which means it is the file's creation date because no date is printed in the document itself.

## Documents

| Brand      | Model(s)                        | Document                            | Language | Date        |
| ---------- | ------------------------------- | ----------------------------------- | -------- | ----------- |
| Nimly      | NimlyCode                       | Installation guide                  | EN       | 2022-09-13  |
| Nimly      | NimlyCodePRO                    | Product guide                       | EN       | 2026-01-12  |
| Nimly      | NimlyPRO, NimlyPRO24            | Installation manual                 | EN       | 2024-03-15  |
| Nimly      | NimlyPRO, NimlyPRO24            | Installation manual, 2025 edition   | EN       | 2025-09-15  |
| Nimly      | NimlyTouch                      | Installation manual                 | EN       | 2025-09-15  |
| Nimly      | NimlyIn                         | Installation guide                  | EN       | 2022-10-05  |
| Nimly      | Connect Module (ZMNC010)        | Installation guide                  | EN       | 2024-10-23  |
| Nimly      | Connect Gateway / Bridge        | Installation guide                  | EN       | 2023-06-20  |
| EasyAccess | easyCodeTouch_v1, EasyCodeTouch | Installation and programming manual | NO/SV    | 2020-10-21* |
| EasyAccess | EasyFingerTouch                 | Installation and programming manual | NO/SV    | 2020-07-09* |
| EasyAccess | E-Life Zigbee module            | Zigbee protocol spec, v2.0          | EN       | 2021-01-25  |
| Nimly      | Connect Module (ZMNC010)        | Installation guide, 2026 edition    | NO       | 2026-02-11* |
| Copiax     | Connect Module (ZMNC010)        | Installation guide, reseller edition | EN      | 2022-08-18* |
| EasyAccess | Zigbee module (e-Life)          | Module mounting, three photos       | NO       | 2021-04-26* |
| Nimly      | NimlyCode                       | Installation manual, new firmware   | NO       | 2025-09-15  |
| Nimly      | Keybox Black                    | Installation and programming guide  | EN       | 2024-11-29  |
| Nimly      | Keybox Black                    | Product sheet                       | NO       | 2025-04-25  |
| Develco    | Squid.link 2B/2X (MGW211)       | FCC exhibits: internal photos, three test reports, users manual | EN | 2020-12-21 |

Notes on specific rows:

- `docs/slot-numbering.md` quotes the 2024 Touch Pro manual, so that stays the reference edition. The 2025 edition was added because it is the current download on nimly.se; the slot rules are identical (user slot 000 reserved for the first master code, 001-002 for more master codes, 003-199 for user fingerprints, 003-999 for user codes and key tags). Only the page layout changed between the two.
- The Connect Module guide's `.txt` extract is lossy. `pdftotext -layout` drops the footnote printed under the green "Works with unloc" badge, which reads, verbatim from the rendered page: "*Bluetooth is only available on the newer versions of the module." Read the PDF itself, not the extract, before concluding anything about which modules speak Bluetooth.
- `EN-Connect-Gateway-Installation-Guide-200623-frontpage.pdf` has no extractable text: it is a one-page vector cover graphic, not a text manual, so `pdftotext -layout` produces an empty `.txt`. Kept for completeness; it carries no slot information.
- `E-life-Zigbee-Modul-User-Manual-v2.0-260121.pdf` is not from a vendor site at all. A customer attached it to the public issue [Koenkk/zigbee2mqtt#6379](https://github.com/Koenkk/zigbee2mqtt/issues/6379) in February 2021 and GitHub still serves it from that attachment URL, which is what the Sources table points at. It is a Word export, author Andrea Birkheim, created 26.01.2021, title page dated 25.01.2021 (the date used in the table above); the v2.0 comes from the attachment filename, not from anything printed in the document. The `.txt` extract is complete: the only images in the PDF are the e-Life header logo repeated on every page, and `pdftotext -layout` picks up every heading and table. `docs/zigbee-protocol/elife-module-spec.md` summarises what it says. The same PDF circulated under a second name: `user.manual.pdf`, attached to [Koenkk/zigbee2mqtt#5884](https://github.com/Koenkk/zigbee2mqtt/issues/5884) and mirrored in deCONZ #4253. It was downloaded and hashes identically (`7f7be794…`), so it is the same file and is not kept twice.
- `NO-Connect-Module-Installation-Guide-online.pdf` is the February 2026 edition of the Connect Module guide, Norwegian, one square page. It keeps the 2024 footnote word for word ("*Bluetooth er kun tilgjengelig på nyere versjoner av modulen") and still gives no revision marking, part number or date that would let an owner tell which module is in the lock. What is new: pairing mode is described as four minutes of blinking orange (zigbee) **and** blue (bluetooth), the Bluetooth path is now the third-party Unloc app rather than a Nimly one, and the reset is hold until the orange indicator blinks fast (about 15 seconds), on some modules only after the four minutes are up. Unlike the 2024 edition, `pdftotext -layout` does pick the footnote up here.
- `50461903_ins.pdf` is Copiax's own, older edition of the same guide (PDF created 2022-08-18, English). It is the source for the "either ... or" reading: pairing is slow flashing on both LEDs, and "successful pairing is indicated by solid light on either the blue (BLE) or orange (Zigbee) LED". It also says a gateway is "not required for BLE-application". That is one radio in use at a time after pairing, which is not the same claim as one radio existing.
- `ZigBee-modul-montering.pdf` is a one-page EasyAccess Word export with three photographs: the empty module connector, the module seated in it, and the module lit blue in pairing mode. It is the only public picture of the PCB, and it shows the metal RF shield with the `e-Life` silkscreen and the mainboard marking `PL943_Back05 2020.06.02`.
- `fcc-MGW211/` holds five exhibits from FCC ID **2AHNM-MGW211** (Develco Products, granted 2020-12-21): internal photos (SGS report, five pages, PCB and shield close-ups), three test reports, and the users manual, which turns out to be the Squid.link 2B/2X installation manual v1.5 for MGW211 and MGW221. Block diagram, schematics and operational description exist in the filing but are marked permanently confidential and are not served. Note for anyone chasing this again: the FCC ID is MGW211 for the 2020-12-21 grants and MGW221 for a separate set granted 2020-12-15; both are the same gateway family, and only MGW211 matches the hub in `docs/connect-bridge/hardware-gateway.md`.
- `NO-Code-Installation-Manual-new-firmware-150925.pdf` and `EN-Keybox-Installation-Guide-291124.pdf` have no text layer: the type is outlined, so `pdftotext -layout` returns a few stray labels and nothing else. Read them with OCR (`pdftoppm -png` then `tesseract -l nor`, `-l eng` for the Keybox) or in a viewer. Both were read that way for `docs/slot-numbering.md` and `docs/hardware-generations.md`, against the rendered pages.
- The Keybox product sheet does extract cleanly and is where the EAN 5704571195077 and the "Kode (x 999)" line come from. It lists codes only, while the installation guide's own text mentions tags as well; nothing settles whether a Keybox reads RFID.
- No manual exists for `NimlyShared` or `NimlyTwist`. Both report the same hardware and firmware as the models above rather than being distinct physical products (see the model table in the repo's `README.md` and `docs/slot-numbering.md`).

## Captures, logs and code

Not manuals, but primary material of the same kind: what the locks actually put on the air, and what other people's tools make of it. All of it came from public GitHub issues, so it is someone else's upload and stays local like the PDFs.

| Local item                                 | From                                        | Date       | What it is                                                                                          |
| ------------------------------------------ | ------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------- |
| `Doorlock.sniff/`                          | deCONZ #4253                                | 2021-03-07 | Zigbee sniff of an EasyCodeTouch: a 148 KB Wireshark capture plus the same traffic exported as 7 MB JSON and 2 MB text |
| `lock.command.ONCE/`                       | Zigbee2MQTT #5884                           | 2021-02-07 | One lock command captured three ways (pcapng, JSON, text), same lock and period as the sniff above  |
| `log1.txt`                                 | Zigbee2MQTT #6551                           | 2021-02-26 | 962 lines of Zigbee2MQTT 1.17.1 log from an EasyFinger lock, the only log we have seen from the fingerprint variant |
| `zha-NimlyCodePRO-diagnostics.json`        | zha-device-handlers #5235                   | 2026-08-07 | ZHA device diagnostics for a NimlyCodePRO nobody here owns: node descriptor, endpoints, cluster and attribute cache, quirk class, with IEEE and NWK redacted by ZHA |
| `NimlyCodePro.debug.2026-08-07.224453.txt` | zha-device-handlers #5235                   | 2026-08-07 | zigpy debug log from the same lock, showing the raw ZCL frames of its attribute reports             |
| `nimly-manager-b47b09d/`                   | github.com/aridder/nimly-manager (MIT)      | 2026-08-10 | Snapshot of the whole repo at commit `b47b09d`, for `docs/protocol-current-state.md`, `docs/fingerprint-enrollment.md` and `docs/zigbee-door-lock.md` |

Notes on specific rows:

- The two zips are the most fragile things in this folder: legacy GitHub attachments on issues from 2021, unmirrored anywhere.
- `zha-NimlyCodePRO-diagnostics.json` is missing its opening `{`; the uploader pasted a fragment. Add the brace before parsing it.
- The debug log was read for PIN material before being written down here. It contains none: the only digit runs in it are cluster and attribute ids.
- The nimly-manager tarball is GitHub's `codeload` tarball for one commit, and two downloads of it are byte-identical, so the SHA-256 below is stable. MIT licensed, so quoting it with credit is fine, but the snapshot still stays out of git.

## Sources

| Local file                                                                      | Source URL                                                                                                                                              | Type          | SHA-256                                                          |
| ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- | ---------------------------------------------------------------- |
| EN-Code-Installation-Guide-130922.pdf                                           | https://nimly.se/wp-content/uploads/2023/11/EN-Code-Installation-Guide-130922.pdf                                                                       | pdf           | bb95c8aea97ec6276ec47eaa24a20117571ab5e31d56f8ad336085d3f06375f6 |
| EN-Code-Pro-Product-Guide-120126.pdf                                            | https://nimly.se/wp-content/uploads/2026/04/EN-Code-Pro-Product-Guide-120126.pdf                                                                        | pdf           | 3383b9d7b6f7114e1b216984135e591736b089ed179be410f402bcffa32d430c |
| EN-Touch-Pro-Installation-Manual-150324.pdf                                     | https://nimly.se/wp-content/uploads/2024/09/EN-Touch-Pro-Installation-Manual-150324.pdf                                                                 | pdf           | cb114b58c65dd613e9f22cacc96acb9e5a9483bd40efc06f19fb88d43dd501e7 |
| EN-Touch-Pro-Installation-Manual-150925.pdf                                     | https://nimly.se/wp-content/uploads/2025/09/EN-Touch-Pro-Installation-Manual-150925.pdf                                                                 | pdf           | 1ea5e1b094e2b4c3e6f397b38f8ff346ebf4180a2c3eb9bb5060215d54987e08 |
| EN-Touch-Installation-Manual-150925.pdf                                         | https://nimly.se/wp-content/uploads/2025/09/EN-Touch-Installation-Manual-150925.pdf                                                                     | pdf           | b71fa47db4ddb62ab94b02ab0a704535a9f845b65d2029e5dbb3de3f522f3caa |
| EN-Nimly-Indoor-Installation-Guide-051022.pdf                                   | https://nimly.se/wp-content/uploads/2023/11/EN-Nimly-Indoor-Installation-Guide-051022.pdf                                                               | pdf           | 22d91eed48f0096c40301841ee0e9029e0cc4fa65f43315f78a11ad5e496f068 |
| EN-Connect-Module-Installation-Guide-231024-bluetooth-app-and-nimly-connect.pdf | https://nimly.se/wp-content/uploads/2024/10/EN-Connect-Module-Installation-Guide-231024-bluetooth-app-and-nimly-connect.pdf                             | pdf           | 9310ad939a9e68021a2a6ba9bf7a88e8beea7d36eb82d61903d3fb8023a0dfef |
| EN-Connect-Gateway-Installation-Guide-200623-frontpage.pdf                      | https://nimly.se/wp-content/uploads/2023/08/EN-Connect-Gateway-Installation-Guide-200623-frontpage.pdf                                                  | pdf           | 110c6181420580e31535df98d6c4418d898dbcd91e5024498e4cf1af46213651 |
| EasyCodeT_Manual.pdf                                                            | https://easyaccess.no/wp-content/uploads/2021/02/EasyCodeT_Manual.pdf                                                                                   | pdf           | 3040484f95aafedd4fd291620a932a75b695e8c834fe9ac7ef17dca6a761371e |
| A5_EasyFingerT_Manual-2.pdf                                                     | https://easyaccess.no/wp-content/uploads/2020/08/A5_EasyFingerT_Manual-2.pdf                                                                            | pdf           | 350f3775cdfe9010e3ff168907afb1fd62de4ecc15fd3f74667064350b88e1e8 |
| E-life-Zigbee-Modul-User-Manual-v2.0-260121.pdf                                 | https://github.com/Koenkk/zigbee2mqtt/files/6015013/E-life.Zigbee.Modul.User.Manual.v2.0.pdf                                                            | pdf           | 7f7be7949d77fd43c553ac2d79b0892f9793ae0efa751cde990b53373cce9116 |
| Doorlock.sniff.zip                                                              | https://github.com/dresden-elektronik/deconz-rest-plugin/files/6097782/Doorlock.sniff.zip                                                               | zip           | d800b33ec37ee22e45668b656493dd3ae88af1508c2c72e25bbef24e75cd254e |
| lock.command.ONCE.zip                                                           | https://github.com/Koenkk/zigbee2mqtt/files/5939265/lock.command.ONCE.zip                                                                               | zip           | 3ab926753af6652f240a33ec2d891d92e9e91735d569adcbada4ff5925f618cc |
| log1.txt                                                                        | https://github.com/Koenkk/zigbee2mqtt/files/6076886/log1.txt                                                                                            | txt           | 67867ca8302e8c0908852905a445fff2981ffc122c40db76b7977845b9c71ed6 |
| zha-NimlyCodePRO-diagnostics.json                                               | https://github.com/user-attachments/files/30861966/zha-01JQHBGED93DQJK9JH78ZCNKTH-Onesti.Products.AS.NimlyCodePRO-4df67ba4874745fb002114642bbb1216.json | json          | 6b496fd1d0f1ecb8e946bbfe6222a0e610cd3f1e8f94311cc7d89522d20c727c |
| NimlyCodePro.debug.2026-08-07.224453.txt                                        | https://github.com/user-attachments/files/30862242/NimlyCodePro.debug.2026-08-07.224453.txt                                                             | txt           | bd69208f57a682fe0bb98bb3d9f438ffaa15e5d83ac4581152d809a39319dd56 |
| NO-Connect-Module-Installation-Guide-online.pdf                                 | https://nimly.se/wp-content/uploads/2026/02/NO-Connect-Module-Installation-Guide-online.pdf                                                             | pdf           | c55c11eb3e30c5c8674f6c546b8b79e44cdbaecb2de504a1acf4f46fcb8859d0 |
| 50461903_ins.pdf                                                                | https://www.copiax.se/images/doc/50461903_ins.pdf                                                                                                       | pdf           | e2b4789bd6b53a918dd610c4f25477a5cc60d7a5832688588977ae07578850af |
| ZigBee-modul-montering.pdf                                                      | https://easyaccess.no/wp-content/uploads/2021/04/ZigBee-modul-montering.pdf                                                                             | pdf           | 20cde3974c1ca93a6421a3930230afc7c8d822ec5eef4b067f9c89e5f7c0eaab |
| NO-Code-Installation-Manual-new-firmware-150925.pdf                             | https://nimly.se/wp-content/uploads/2025/09/NO-Code-Installation-Manual-new-firmware-150925.pdf                                                         | pdf           | 00ca4e8e9c85b8c58cd9ca1abbe40739b1f7aff7fe4e3e373f481b5fdba3f626 |
| EN-Keybox-Installation-Guide-291124.pdf                                         | https://nimly.se/wp-content/uploads/2025/04/EN-Keybox-Installation-Guide-291124.pdf                                                                     | pdf           | dd97b151bfa4b16c2665e3b85d65836724442e1f140115acb0ccecb0507bb875 |
| Keybox-produktoversikt-250425.pdf                                               | https://nimly.se/wp-content/uploads/2025/04/Keybox-produktoversikt-250425.pdf                                                                           | pdf           | 0bce3a4963d30b0afa5713eb7b191e70dad9c9d76236f033f55d8bbeb4ba878e |
| fcc-MGW211/MGW211-Internal-Photos.pdf                                           | https://apps.fcc.gov/eas/GetApplicationAttachment.html?id=5051090                                                                                       | pdf           | 1c23d07c7fda55dba85dcfc6e277971a9f636636c92972382cde8a76137144bb |
| fcc-MGW211/MGW211-Test-Report-1.pdf                                             | https://apps.fcc.gov/eas/GetApplicationAttachment.html?id=5051093                                                                                       | pdf           | 21d0f5dda6c19193eb9c73ce1f12fc95b05706031522c596c929b244ea9f9716 |
| fcc-MGW211/MGW211-Test-Report-2.pdf                                             | https://apps.fcc.gov/eas/GetApplicationAttachment.html?id=5051094                                                                                       | pdf           | a344c57a40e5e0d01af6e218cda61a7bca7fe1a3ce8d182bfaba27bc6f2949be |
| fcc-MGW211/MGW211-Test-Report-3.pdf                                             | https://apps.fcc.gov/eas/GetApplicationAttachment.html?id=5051095                                                                                       | pdf           | 245848fc3e09e81340b2e07089397d17603e800fa98f5813638a1628aeea7a12 |
| fcc-MGW211/MGW211-Users-Manual.pdf                                              | https://apps.fcc.gov/eas/GetApplicationAttachment.html?id=5051086                                                                                       | pdf           | d9cd4fd9a3c4da4c7c630df1febbe8971aab93cb2c21b9636ac4b22875d0477d |
| nimly-manager-b47b09d.tar.gz                                                    | https://codeload.github.com/aridder/nimly-manager/tar.gz/b47b09d4cdac4e8c3ecacf8cab80f553dcad9678                                                       | repo-snapshot | 42c335c8b7a5ff0d65298c0bba10fef8a17ff0c5a422545e64432c95bd02d5c5 |

`scripts/fetch_manuals.py` reads this table, not the ones above: it matches rows by a 64-character SHA-256 in the last column, downloads anything missing or changed into `docs/manuals/`, verifies the hash, and then follows the type, extracting text from a PDF and unpacking a zip or a repo snapshot into a folder beside the archive. Safe to run repeatedly.

```
python3 scripts/fetch_manuals.py
```

The five `fcc-MGW211/` rows are the exception: apps.fcc.gov answers 403 to curl and to urllib whatever headers they send, so the script will report DEAD LINK for them on a fresh checkout and they have to be fetched with a real browser. The route, since the FCC's own search is just as unfriendly to a constructed URL: open `https://apps.fcc.gov/oetcf/eas/reports/GenericSearch.cfm`, type grantee code `2AHNM` (leave the product code empty, a filled one matches nothing), submit the form, and in the result table follow "Summary" on one of the three 12/21/2020 MGW211 rows. That lands on `ViewExhibitReport.cfm` with an `application_id` in the URL; swap `mode=Sum` for `mode=Exhibits` and the attachment links appear. The mirrors that would be easier, fcc.report, fccid.io and electric.garden, all answer 403 or 429.

## Living sources

Everything above is a file that will never change again, pinned by its hash. This table is the opposite: forum threads, GitHub issues and the code other people keep writing about these locks. The point of archiving them is to not do the search a second time, and to see in December what was already read in September.

So the row carries a date and a marker instead of a hash: `Fetched` is the last time the script got it, `Size then` is how big it was at that moment. `python3 scripts/fetch_manuals.py --living` refetches everything, prints `same` or `CHANGED 241 -> 248` per row, and writes the new date and marker back here, so `git diff` on this file is the list of what moved. `--check` does the same without writing.

| Type | What it fetches | Marker |
| ---- | --------------- | ------ |
| `discourse` | A whole Discourse topic, every post, as JSON plus a readable `.txt` | posts in the topic |
| `invision` | A hjemmeautomasjon.no topic, page by page, as `.txt` (no JSON API exists) | posts found |
| `gh-issue` | One issue or PR with every comment, as JSON plus a `.txt` | comments, `17c` |
| `gh-file` | One file at the head of a branch | the commit that last touched it |
| `gh-repo` | A whole repository, unpacked | the head commit |
| `web` | A vendor page: raw `.html` beside a stripped `.txt` | SHA-256 of the text |
| `appstore` | Apple's lookup API for one app: version, release date, release notes | the version |
| `android` | APKPure's package page for one app: version, versionCode, publication date | `version (versionCode)` |
| `manual` | Nothing. The row says the source exists and cannot be scripted | why not |

The marker for `web` is the hash of the text and not of the HTML on purpose. nimly.se serves a fresh nonce on every request, so the raw bytes differ between two fetches a second apart and every run would claim the page had changed.

`vendor/nimly-produktinformasjon.txt` is the document index on nimly.no, and the row to reread when a manual seems to be missing here: the 2025 Code manual for new firmware and both Keybox documents are linked from it and from no product page on nimly.se. Its `.txt` is nearly empty, since the page is a wall of links and nothing else; the PDF URLs are in the `.html` beside it. `vendor/nimly-forhandlere.txt` is the retailer list behind [buying-a-lock.md](../buying-a-lock.md), and the Elektroimportøren and EasyAccess rows are the two shop pages that carry prices and article numbers for the range.

The `appstore` and `android` rows cover every app in the white-label family, one row per store, and they are the trigger for the work described in [app-versions.md](../nimly-connect-app/app-versions.md): the rows say which app moved, that file says what was in it last time we looked. An `appstore` key is the numeric track id, with `@se` appended when the app is sold in Sweden and not in Norway. An `android` key is the package name, read off APKPure because Google's own listing no longer prints a version anywhere in its HTML; APKPure mirrors on its own schedule and can sit one release behind Play, so the row dates the mirror, not the store. On 2026-09-20 every `android` row except the BLE app was checked against the downloaded APK's own `AndroidManifest.xml` and agreed on both version and versionCode; the artefacts are listed in [app-versions.md](../nimly-connect-app/app-versions.md). The BLE app is the exception twice over: its package page still answers, but the download list behind it is empty, so `apkeep` gets no file and the local copy stays the March one off Play.

Two Swedish forums are in the table as `manual` rows. byggahus.se and sweclockers.com both answer 403 to anything that is not a browser: the block is a Cloudflare challenge served before any HTML, so there is no fallback to parse. hemautomation.se is not in the table at all: the domain is parked at Loopia and the forum no longer exists.

Two of those rows were read by hand on 2026-09-20 and their text now lies in `forums/`, so the script still fetches nothing but the content is local. What worked, and what did not:

- sweclockers serves the public `r.jina.ai` text reader, so thread 1713551 came out as text in one request. byggahus does not: the reader gets the same "Just a moment..." interstitial curl gets.
- byggahus renders normally in the Firefox the devtools MCP drives, but that is a picture and not a text route. `take_snapshot` returns the page chrome only on this site, with the whole thread body missing, and the MCP has no scroll command, so only what an anchor URL (`/forum/posts/<id>/`) puts on screen can be captured. That is why `byggahus-543716` is 5 of 7 posts and why the two long threads, 497166 with 37+ pages and 573457, are still unread.
- Neither site has a wayback snapshot of any of these threads, checked through the CDX API.
- The remaining route is the cookie one: lend a Cloudflare clearance from a Firefox profile and send it with curl, with the User-Agent the clearance was issued to. `verktøy/hentkilde.py` in the nettselskap repo already does exactly that (`--jar`, `--profil`, `--ua`). It needs a permission grant to read the cookie store, which this session did not have.

| Local item | Source | Type | Key | Fetched | Size then |
| ---------- | ------ | ---- | --- | ------- | --------- |
| forums/ha-523634.json | https://community.home-assistant.io | discourse | 523634 | 2026-09-20 | 241 |
| forums/ha-930415.json | https://community.home-assistant.io | discourse | 930415 | 2026-09-20 | 5 |
| forums/ha-796362.json | https://community.home-assistant.io | discourse | 796362 | 2026-09-20 | 2 |
| forums/ha-1010146.json | https://community.home-assistant.io | discourse | 1010146 | 2026-09-20 | 1 |
| forums/homey-78867.json | https://community.homey.app | discourse | 78867 | 2026-09-20 | 19 |
| forums/homey-143578.json | https://community.homey.app | discourse | 143578 | 2026-09-20 | 22 |
| forums/homey-104305.json | https://community.homey.app | discourse | 104305 | 2026-09-20 | 9 |
| forums/homey-99133.json | https://community.homey.app | discourse | 99133 | 2026-09-20 | 11 |
| forums/homey-147580.json | https://community.homey.app | discourse | 147580 | 2026-09-20 | 8 |
| forums/homey-117371.json | https://community.homey.app | discourse | 117371 | 2026-09-20 | 5 |
| forums/homey-141138.json | https://community.homey.app | discourse | 141138 | 2026-09-20 | 2 |
| forums/homey-139743.json | https://community.homey.app | discourse | 139743 | 2026-09-20 | 2 |
| forums/homey-137354.json | https://community.homey.app | discourse | 137354 | 2026-09-20 | 2 |
| forums/homey-35333.json | https://community.homey.app | discourse | 35333 | 2026-09-20 | 8 |
| forums/openhab-125747.json | https://community.openhab.org | discourse | 125747 | 2026-09-20 | 4 |
| forums/smartthings-86418.json | https://community.smartthings.com | discourse | 86418 | 2026-09-20 | 25 |
| forums/hja-3791.txt | https://www.hjemmeautomasjon.no/forums/topic/3791-easyaccess-easycode-pinout | invision | 3791 | 2026-09-20 | 72 |
| forums/hja-6786.txt | https://www.hjemmeautomasjon.no/forums/topic/6786-easy-access-easycodetouch | invision | 6786 | 2026-09-20 | 45 |
| forums/hja-5766.txt | https://www.hjemmeautomasjon.no/forums/topic/5766-easy-access-easycode-v2-kodel | invision | 5766 | 2026-09-20 | 4 |
| forums/hja-13667.txt | https://www.hjemmeautomasjon.no/forums/topic/13667-nimly-id-lock-eller-nuki | invision | 13667 | 2026-09-20 | 2 |
| forums/hja-2869.txt | https://www.hjemmeautomasjon.no/forums/topic/2869-bytte-ut-easyaccess-lås-med-id-lock | invision | 2869 | 2026-09-20 | 4 |
| forums/hja-10418.txt | https://www.hjemmeautomasjon.no/forums/topic/10418-hvordan-reset-av-easyaccess-dørlås | invision | 10418 | 2026-09-20 | 1 |
| github/z2m-5884.json | https://github.com/Koenkk/zigbee2mqtt/issues/5884 | gh-issue | Koenkk/zigbee2mqtt#5884 | 2026-09-20 | 17c |
| github/z2m-6379.json | https://github.com/Koenkk/zigbee2mqtt/issues/6379 | gh-issue | Koenkk/zigbee2mqtt#6379 | 2026-09-20 | 4c |
| github/z2m-6551.json | https://github.com/Koenkk/zigbee2mqtt/issues/6551 | gh-issue | Koenkk/zigbee2mqtt#6551 | 2026-09-20 | 123c |
| github/z2m-13768.json | https://github.com/Koenkk/zigbee2mqtt/issues/13768 | gh-issue | Koenkk/zigbee2mqtt#13768 | 2026-09-20 | 2c |
| github/z2m-14726.json | https://github.com/Koenkk/zigbee2mqtt/issues/14726 | gh-issue | Koenkk/zigbee2mqtt#14726 | 2026-09-20 | 6c |
| github/z2m-17205.json | https://github.com/Koenkk/zigbee2mqtt/issues/17205 | gh-issue | Koenkk/zigbee2mqtt#17205 | 2026-09-20 | 88c |
| github/z2m-17546.json | https://github.com/Koenkk/zigbee2mqtt/issues/17546 | gh-issue | Koenkk/zigbee2mqtt#17546 | 2026-09-20 | 1c |
| github/z2m-18508.json | https://github.com/Koenkk/zigbee2mqtt/issues/18508 | gh-issue | Koenkk/zigbee2mqtt#18508 | 2026-09-20 | 3c |
| github/z2m-19299.json | https://github.com/Koenkk/zigbee2mqtt/issues/19299 | gh-issue | Koenkk/zigbee2mqtt#19299 | 2026-09-20 | 7c |
| github/z2m-19627.json | https://github.com/Koenkk/zigbee2mqtt/issues/19627 | gh-issue | Koenkk/zigbee2mqtt#19627 | 2026-09-20 | 5c |
| github/z2m-19738.json | https://github.com/Koenkk/zigbee2mqtt/issues/19738 | gh-issue | Koenkk/zigbee2mqtt#19738 | 2026-09-20 | 1c |
| github/z2m-21182.json | https://github.com/Koenkk/zigbee2mqtt/issues/21182 | gh-issue | Koenkk/zigbee2mqtt#21182 | 2026-09-20 | 0c |
| github/z2m-22319.json | https://github.com/Koenkk/zigbee2mqtt/issues/22319 | gh-issue | Koenkk/zigbee2mqtt#22319 | 2026-09-20 | 13c |
| github/z2m-23551.json | https://github.com/Koenkk/zigbee2mqtt/issues/23551 | gh-issue | Koenkk/zigbee2mqtt#23551 | 2026-09-20 | 3c |
| github/z2m-23691.json | https://github.com/Koenkk/zigbee2mqtt/issues/23691 | gh-issue | Koenkk/zigbee2mqtt#23691 | 2026-09-20 | 8c |
| github/z2m-24503.json | https://github.com/Koenkk/zigbee2mqtt/issues/24503 | gh-issue | Koenkk/zigbee2mqtt#24503 | 2026-09-20 | 2c |
| github/z2m-26649.json | https://github.com/Koenkk/zigbee2mqtt/issues/26649 | gh-issue | Koenkk/zigbee2mqtt#26649 | 2026-09-20 | 1c |
| github/z2m-26651.json | https://github.com/Koenkk/zigbee2mqtt/issues/26651 | gh-issue | Koenkk/zigbee2mqtt#26651 | 2026-09-20 | 3c |
| github/z2m-30704.json | https://github.com/Koenkk/zigbee2mqtt/issues/30704 | gh-issue | Koenkk/zigbee2mqtt#30704 | 2026-09-20 | 1c |
| github/z2m-31385.json | https://github.com/Koenkk/zigbee2mqtt/issues/31385 | gh-issue | Koenkk/zigbee2mqtt#31385 | 2026-09-20 | 3c |
| github/z2m-32469.json | https://github.com/Koenkk/zigbee2mqtt/issues/32469 | gh-issue | Koenkk/zigbee2mqtt#32469 | 2026-09-20 | 1c |
| github/z2m-32772.json | https://github.com/Koenkk/zigbee2mqtt/issues/32772 | gh-issue | Koenkk/zigbee2mqtt#32772 | 2026-09-20 | 0c |
| github/zhc-4892.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/4892 | gh-issue | Koenkk/zigbee-herdsman-converters#4892 | 2026-09-20 | 2c |
| github/zhc-6009.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/6009 | gh-issue | Koenkk/zigbee-herdsman-converters#6009 | 2026-09-20 | 1c |
| github/zhc-6010.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/6010 | gh-issue | Koenkk/zigbee-herdsman-converters#6010 | 2026-09-20 | 4c |
| github/zhc-6024.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/6024 | gh-issue | Koenkk/zigbee-herdsman-converters#6024 | 2026-09-20 | 1c |
| github/zhc-6043.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/6043 | gh-issue | Koenkk/zigbee-herdsman-converters#6043 | 2026-09-20 | 1c |
| github/zhc-6096.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/6096 | gh-issue | Koenkk/zigbee-herdsman-converters#6096 | 2026-09-20 | 1c |
| github/zhc-6249.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/6249 | gh-issue | Koenkk/zigbee-herdsman-converters#6249 | 2026-09-20 | 2c |
| github/zhc-6940.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/6940 | gh-issue | Koenkk/zigbee-herdsman-converters#6940 | 2026-09-20 | 6c |
| github/zhc-7237.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/7237 | gh-issue | Koenkk/zigbee-herdsman-converters#7237 | 2026-09-20 | 3c |
| github/zhc-7247.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/7247 | gh-issue | Koenkk/zigbee-herdsman-converters#7247 | 2026-09-20 | 1c |
| github/zhc-8994.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/8994 | gh-issue | Koenkk/zigbee-herdsman-converters#8994 | 2026-09-20 | 4c |
| github/zhc-9018.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/9018 | gh-issue | Koenkk/zigbee-herdsman-converters#9018 | 2026-09-20 | 6c |
| github/zhc-9527.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/9527 | gh-issue | Koenkk/zigbee-herdsman-converters#9527 | 2026-09-20 | 3c |
| github/zhc-11332.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/11332 | gh-issue | Koenkk/zigbee-herdsman-converters#11332 | 2026-09-20 | 8c |
| github/zhc-11874.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/11874 | gh-issue | Koenkk/zigbee-herdsman-converters#11874 | 2026-09-20 | 1c |
| github/zhc-13080.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/13080 | gh-issue | Koenkk/zigbee-herdsman-converters#13080 | 2026-09-20 | 0c |
| github/zhc-13233.json | https://github.com/Koenkk/zigbee-herdsman-converters/issues/13233 | gh-issue | Koenkk/zigbee-herdsman-converters#13233 | 2026-09-20 | 1c |
| github/zha-2354.json | https://github.com/zigpy/zha-device-handlers/issues/2354 | gh-issue | zigpy/zha-device-handlers#2354 | 2026-09-20 | 8c |
| github/zha-2376.json | https://github.com/zigpy/zha-device-handlers/issues/2376 | gh-issue | zigpy/zha-device-handlers#2376 | 2026-09-20 | 10c |
| github/zha-3095.json | https://github.com/zigpy/zha-device-handlers/issues/3095 | gh-issue | zigpy/zha-device-handlers#3095 | 2026-09-20 | 16c |
| github/zha-3457.json | https://github.com/zigpy/zha-device-handlers/issues/3457 | gh-issue | zigpy/zha-device-handlers#3457 | 2026-09-20 | 13c |
| github/zha-3465.json | https://github.com/zigpy/zha-device-handlers/issues/3465 | gh-issue | zigpy/zha-device-handlers#3465 | 2026-09-20 | 16c |
| github/zha-3580.json | https://github.com/zigpy/zha-device-handlers/issues/3580 | gh-issue | zigpy/zha-device-handlers#3580 | 2026-09-20 | 1c |
| github/zha-4138.json | https://github.com/zigpy/zha-device-handlers/issues/4138 | gh-issue | zigpy/zha-device-handlers#4138 | 2026-09-20 | 18c |
| github/zha-4147.json | https://github.com/zigpy/zha-device-handlers/issues/4147 | gh-issue | zigpy/zha-device-handlers#4147 | 2026-09-20 | 1c |
| github/zha-4244.json | https://github.com/zigpy/zha-device-handlers/issues/4244 | gh-issue | zigpy/zha-device-handlers#4244 | 2026-09-20 | 1c |
| github/zha-4881.json | https://github.com/zigpy/zha-device-handlers/issues/4881 | gh-issue | zigpy/zha-device-handlers#4881 | 2026-09-20 | 8c |
| github/zha-5235.json | https://github.com/zigpy/zha-device-handlers/issues/5235 | gh-issue | zigpy/zha-device-handlers#5235 | 2026-09-20 | 3c |
| github/zha-5345.json | https://github.com/zigpy/zha-device-handlers/issues/5345 | gh-issue | zigpy/zha-device-handlers#5345 | 2026-09-20 | 2c |
| github/deconz-4252.json | https://github.com/dresden-elektronik/deconz-rest-plugin/issues/4252 | gh-issue | dresden-elektronik/deconz-rest-plugin#4252 | 2026-09-20 | 1c |
| github/deconz-4253.json | https://github.com/dresden-elektronik/deconz-rest-plugin/issues/4253 | gh-issue | dresden-elektronik/deconz-rest-plugin#4253 | 2026-09-20 | 126c |
| github/deconz-4540.json | https://github.com/dresden-elektronik/deconz-rest-plugin/issues/4540 | gh-issue | dresden-elektronik/deconz-rest-plugin#4540 | 2026-09-20 | 36c |
| github/deconz-5042.json | https://github.com/dresden-elektronik/deconz-rest-plugin/issues/5042 | gh-issue | dresden-elektronik/deconz-rest-plugin#5042 | 2026-09-20 | 3c |
| github/deconz-5870.json | https://github.com/dresden-elektronik/deconz-rest-plugin/issues/5870 | gh-issue | dresden-elektronik/deconz-rest-plugin#5870 | 2026-09-20 | 54c |
| github/deconz-6334.json | https://github.com/dresden-elektronik/deconz-rest-plugin/issues/6334 | gh-issue | dresden-elektronik/deconz-rest-plugin#6334 | 2026-09-20 | 8c |
| github/deconz-7125.json | https://github.com/dresden-elektronik/deconz-rest-plugin/issues/7125 | gh-issue | dresden-elektronik/deconz-rest-plugin#7125 | 2026-09-20 | 4c |
| github/deconz-7525.json | https://github.com/dresden-elektronik/deconz-rest-plugin/issues/7525 | gh-issue | dresden-elektronik/deconz-rest-plugin#7525 | 2026-09-20 | 7c |
| github/deconz-7534.json | https://github.com/dresden-elektronik/deconz-rest-plugin/issues/7534 | gh-issue | dresden-elektronik/deconz-rest-plugin#7534 | 2026-09-20 | 2c |
| github/deconz-8514.json | https://github.com/dresden-elektronik/deconz-rest-plugin/issues/8514 | gh-issue | dresden-elektronik/deconz-rest-plugin#8514 | 2026-09-20 | 8c |
| github/deconz-8515.json | https://github.com/dresden-elektronik/deconz-rest-plugin/issues/8515 | gh-issue | dresden-elektronik/deconz-rest-plugin#8515 | 2026-09-20 | 8c |
| code/onesti.ts | https://github.com/Koenkk/zigbee-herdsman-converters | gh-file | Koenkk/zigbee-herdsman-converters:src/devices/onesti.ts@master | 2026-09-20 | 61b0b4c77d3e |
| code/zhaquirks-nimly-lock.py | https://github.com/zigpy/zha-device-handlers | gh-file | zigpy/zha-device-handlers:zhaquirks/nimly/lock.py@dev | 2026-09-20 | e5c7b242efe0 |
| code/zhaquirks-nimly-init.py | https://github.com/zigpy/zha-device-handlers | gh-file | zigpy/zha-device-handlers:zhaquirks/nimly/__init__.py@dev | 2026-09-20 | 263e68c48778 |
| vendor/nimly-touch-pro-black.txt | https://nimly.se/product/touch-pro-black/ | web | - | 2026-09-20 | 7638e0ac758e |
| vendor/nimly-touch-pro-ultimate-black.txt | https://nimly.se/product/touch-pro-ultimate-black/ | web | - | 2026-09-20 | 247400e8f121 |
| vendor/nimly-touch.txt | https://nimly.se/product/touch/ | web | - | 2026-09-20 | 9e9a2d013d48 |
| vendor/nimly-code-pro.txt | https://nimly.se/product/code-pro/ | web | - | 2026-09-20 | ffacbb715775 |
| vendor/nimly-code-swe.txt | https://nimly.se/product/code-swe/ | web | - | 2026-09-20 | 41188dd5dfb9 |
| vendor/nimly-indoor.txt | https://nimly.se/product/nimly-indoor/ | web | - | 2026-09-20 | 24ee365015b7 |
| vendor/nimly-connect-module.txt | https://nimly.se/product/connect-module/ | web | - | 2026-09-20 | 27588e0d792b |
| vendor/nimly-connect-bridge.txt | https://nimly.se/product/connect-bridge/ | web | - | 2026-09-20 | 303bc7273255 |
| vendor/nimly-connect-gateway.txt | https://nimly.se/product/connect-gateway/ | web | - | 2026-09-20 | 4be67749a207 |
| vendor/nimly-connect-app.txt | https://nimly.se/product/connect-app/ | web | - | 2026-09-20 | 8dfb6377f860 |
| vendor/nimly-support.txt | https://nimly.se/support/ | web | - | 2026-09-20 | 01c4c320567e |
| vendor/nimly-vulnerability-reporting.txt | https://nimly.se/rapportering-av-sarbarheter/ | web | - | 2026-09-20 | fa11b0a60362 |
| vendor/unloc-install-nimly.txt | https://help.unloc.app/en/article/how-to-install-nimly-touch-protouchcodeindoor-aesdl5 | web | - | 2026-09-20 | 250e48fb5383 |
| vendor/nimly-produktinformasjon.txt | https://nimly.no/produktinformasjon/ | web | - | 2026-09-20 | aa3a0be2439f |
| vendor/nimly-forhandlere.txt | https://nimly.no/forhandlere/ | web | - | 2026-09-20 | 66800fcfac10 |
| vendor/elektroimportoren-nimly.txt | https://www.elektroimportoren.no/nimly/ | web | - | 2026-09-20 | a6fb77b57637 |
| vendor/easyaccess-easyring-lock-module.txt | https://easyaccess.no/product/easyring-lock-module/ | web | - | 2026-09-20 | af312610bdd3 |
| vendor/app-nimly-ble.json | https://apps.apple.com/no/app/nimly-ble/id6451232924 | appstore | 6451232924 | 2026-09-20 | 1.5.0 |
| vendor/app-nimly-connect.json | https://apps.apple.com/no/app/nimly-connect/id1577797927 | appstore | 1577797927 | 2026-09-20 | 1.28.0 |
| vendor/app-nimly-home.json | https://apps.apple.com/no/app/nimly-home/id6760764003 | appstore | 6760764003 | 2026-09-20 | 1.0 |
| vendor/app-unloc.json | https://apps.apple.com/no/app/unloc/id1361534440 | appstore | 1361534440 | 2026-09-20 | 5.11.8 |
| vendor/app-keyfree.json | https://apps.apple.com/no/app/keyfree/id1537398768 | appstore | 1537398768 | 2026-09-20 | 1.27.0 |
| vendor/app-salus-immunity.json | https://apps.apple.com/no/app/salus-immunity/id6449595598 | appstore | 6449595598 | 2026-09-20 | 1.28.0 |
| vendor/app-forebygg.json | https://apps.apple.com/se/app/forebygg/id1543671043 | appstore | 1543671043@se | 2026-09-20 | 1.27.45 |
| vendor/app-tekam.json | https://apps.apple.com/no/app/tekam-smarthus/id1465331491 | appstore | 1465331491 | 2026-09-20 | 1.28.0 |
| vendor/app-iotiliti.json | https://apps.apple.com/no/app/iotiliti/id1465138939 | appstore | 1465138939 | 2026-09-20 | 1.28.0 |
| vendor/app-homely.json | https://apps.apple.com/no/app/homely/id1447485754 | appstore | 1447485754 | 2026-09-20 | 1.28.0 |
| vendor/app-tryg-smart.json | https://apps.apple.com/no/app/tryg-smart/id1495994587 | appstore | 1495994587 | 2026-09-20 | 1.24.1 |
| vendor/app-confi-care.json | https://apps.apple.com/no/app/confi-care/id1525530018 | appstore | 1525530018 | 2026-09-20 | 1.28.1 |
| vendor/app-copiapp.json | https://apps.apple.com/se/app/copiapp/id6467866084 | appstore | 6467866084@se | 2026-09-20 | 1.3.11 |
| vendor/app-larmify.json | https://apps.apple.com/se/app/larmify/id6748140535 | appstore | 6748140535@se | 2026-09-20 | 1.28.0 |
| vendor/apk-nimly-connect.json | https://apkpure.com/x/com.easyaccess.connect | android | com.easyaccess.connect | 2026-09-20 | 1.28.46 (292) |
| vendor/apk-nimly-ble.json | https://apkpure.com/x/easyaccess.ekey.app | android | easyaccess.ekey.app | 2026-09-20 | 1.5.1 (12) |
| vendor/apk-unloc.json | https://apkpure.com/x/ai.unloc.unloc | android | ai.unloc.unloc | 2026-09-20 | 5.9.0 (2318) |
| vendor/apk-iotiliti.json | https://apkpure.com/x/io.iotiliti.home | android | io.iotiliti.home | 2026-09-20 | 1.28.46 (906) |
| vendor/apk-copiax.json | https://apkpure.com/x/com.copiax.homesecurity | android | com.copiax.homesecurity | 2026-09-20 | 1.28.46 (333) |
| vendor/apk-tekam.json | https://apkpure.com/x/no.tekam.smarthus | android | no.tekam.smarthus | 2026-09-20 | 1.22.44 (192) |
| vendor/apk-folklarm.json | https://apkpure.com/x/com.folklarm.appsolutsakerhet | android | com.folklarm.appsolutsakerhet | 2026-09-20 | 1.25.49 (183) |
| vendor/apk-keyfree.json | https://apkpure.com/x/com.safe4.keyfree | android | com.safe4.keyfree | 2026-09-20 | 1.27.23 (474) |
| vendor/apk-forebygg.json | https://apkpure.com/x/se.forebygg.forebygg | android | se.forebygg.forebygg | 2026-09-20 | 1.24.78 (121) |
| vendor/apk-homely.json | https://apkpure.com/x/io.homely.home | android | io.homely.home | 2026-09-20 | 1.28.61 (627) |
| vendor/apk-salus.json | https://apkpure.com/x/com.salusprotekt.immunity | android | com.salusprotekt.immunity | 2026-09-20 | 1.25.62 (56) |
| vendor/apk-tryg-smart.json | https://apkpure.com/x/com.tryg.smart | android | com.tryg.smart | 2026-09-20 | 1.24.73 (156) |
| vendor/apk-confi-care.json | https://apkpure.com/x/com.safelyteam.safely | android | com.safelyteam.safely | 2026-09-20 | 1.20.9 (72) |
| vendor/apk-larmify.json | https://apkpure.com/x/se.larmify.larmify | android | se.larmify.larmify | 2026-09-20 | 1.27.84 (43) |
| byggahus-497166 | https://www.byggahus.se/forum/threads/497166 | manual | 497166 | 2026-09-20 | Cloudflare 403, 37+ pages unread |
| byggahus-573457 | https://www.byggahus.se/forum/threads/573457 | manual | 573457 | 2026-09-20 | Cloudflare 403, unread |
| forums/byggahus-543716.txt | https://www.byggahus.se/forum/threads/543716 | manual | 543716 | 2026-09-20 | 5 of 7 posts, read in the browser |
| forums/sweclockers-1713551.txt | https://www.sweclockers.com/forum/trad/1713551 | manual | 1713551 | 2026-09-20 | 2 posts, whole thread, via r.jina.ai |
| code/nimly-manager/ | https://github.com/aridder/nimly-manager | gh-repo | aridder/nimly-manager@main | 2026-09-20 | b47b09d4cdac |

## White-label brands

All locks are the same Onesti Products AS hardware, resold under multiple brands (see `AGENTS.md`). Each brand's own site was checked for a lock manual PDF.

| Brand                         | Own manual? | Notes                                                                                         |
| ----------------------------- | ----------- | --------------------------------------------------------------------------------------------- |
| Nimly                         | Yes         | See tables above.                                                                             |
| EasyAccess                    | Yes         | See tables above.                                                                             |
| Keyfree (keyfree.no)          | Alias       | Own-hosted NO copies of the Code and Touch manuals; slot rules match Nimly's. Not downloaded. |
| Copiax (copiax.se)            | Own edition | An older Connect Module guide than Nimly publishes, downloaded; see the tables above.         |
| Salus (salus-protect.com)     | Not found   | Checked product pages, /support/, /immunity/. Support is web pages, no PDF.                   |
| Homely (homely.no)            | Not found   | App integrates Nimly locks, refers users to the Nimly manual.                                 |
| Forebygg (forebygg.se)        | Not found   | Only marketing and social pages turned up.                                                    |
| Tekam Smarthus (tekam.no)     | Not found   | App supports Nimly locks, no Tekam-branded manual.                                            |
| Folklarm / Appsolut Sakerhet  | Not found   | Alarm service around Nimly locks, no own manual.                                              |
| Tryg Smart                    | Not found   | App-only integration, no Tryg-branded manual.                                                 |
| Safe4 Care / Confi.care       | Not found   | No product page or manual reference found at all.                                             |
| LF (Lansforsakringar, alf.se) | Not found   | Device page inside the Alf app, no downloadable manual.                                       |
| Larmify (larmify.se)          | Not found   | States outright they refer customers to the lock supplier for manuals.                        |

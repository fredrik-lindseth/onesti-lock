# Manufacturer manuals and source material

Manufacturer PDFs, kept here so the slot-numbering rules can be checked offline, plus the other primary sources that belong next to them: Zigbee sniffs, logs, a device diagnostics dump and one code snapshot. The `.txt` files next to a PDF are `pdftotext -layout` extracts. Everything in this folder is gitignored; only this README is tracked.

Run `python3 scripts/fetch_manuals.py` to download it all. Each row in the Sources table carries a type, and the script acts on it: a PDF gets a text extract, a zip or a repo snapshot is unpacked into a folder beside the archive, a `.txt` or `.json` is just stored.

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

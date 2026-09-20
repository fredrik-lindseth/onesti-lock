# Manufacturer manuals

Manufacturer PDFs, kept here so the slot-numbering rules can be checked offline. The `.txt` files are `pdftotext -layout` extracts. PDFs and `.txt` files are gitignored; only this README is tracked.

Run `python3 scripts/fetch_manuals.py` to download every manual and its text extract.

Retrieved 2026-09-19 from the manufacturer's own domains (nimly.se, easyaccess.no), except the E-Life Zigbee module spec, which the manufacturer never published and which is downloaded from a public Zigbee2MQTT issue instead. Date is the date encoded in the manufacturer's filename (DDMMYY), unless marked `*`, which means it is the PDF's creation date because no date is printed in the document itself.

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

Notes on specific rows:

- `docs/slot-numbering.md` quotes the 2024 Touch Pro manual, so that stays the reference edition. The 2025 edition was added because it is the current download on nimly.se; the slot rules are identical (user slot 000 reserved for the first master code, 001-002 for more master codes, 003-199 for user fingerprints, 003-999 for user codes and key tags). Only the page layout changed between the two.
- The Connect Module guide's `.txt` extract is lossy. `pdftotext -layout` drops the footnote printed under the green "Works with unloc" badge, which reads, verbatim from the rendered page: "*Bluetooth is only available on the newer versions of the module." Read the PDF itself, not the extract, before concluding anything about which modules speak Bluetooth.
- `EN-Connect-Gateway-Installation-Guide-200623-frontpage.pdf` has no extractable text: it is a one-page vector cover graphic, not a text manual, so `pdftotext -layout` produces an empty `.txt`. Kept for completeness; it carries no slot information.
- `E-life-Zigbee-Modul-User-Manual-v2.0-260121.pdf` is not from a vendor site at all. A customer attached it to the public issue [Koenkk/zigbee2mqtt#6379](https://github.com/Koenkk/zigbee2mqtt/issues/6379) in February 2021 and GitHub still serves it from that attachment URL, which is what the Sources table points at. It is a Word export, author Andrea Birkheim, created 26.01.2021, title page dated 25.01.2021 (the date used in the table above); the v2.0 comes from the attachment filename, not from anything printed in the document. The `.txt` extract is complete: the only images in the PDF are the e-Life header logo repeated on every page, and `pdftotext -layout` picks up every heading and table. `docs/zigbee-protocol/elife-module-spec.md` summarises what it says.
- No manual exists for `NimlyShared` or `NimlyTwist`. Both report the same hardware and firmware as the models above rather than being distinct physical products (see the model table in the repo's `README.md` and `docs/slot-numbering.md`).

## Sources

| Local file                                                                      | Source URL                                                                                                                  | SHA-256 (PDF)                                                    |
| ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| EN-Code-Installation-Guide-130922.pdf                                           | https://nimly.se/wp-content/uploads/2023/11/EN-Code-Installation-Guide-130922.pdf                                           | bb95c8aea97ec6276ec47eaa24a20117571ab5e31d56f8ad336085d3f06375f6 |
| EN-Code-Pro-Product-Guide-120126.pdf                                            | https://nimly.se/wp-content/uploads/2026/04/EN-Code-Pro-Product-Guide-120126.pdf                                            | 3383b9d7b6f7114e1b216984135e591736b089ed179be410f402bcffa32d430c |
| EN-Touch-Pro-Installation-Manual-150324.pdf                                     | https://nimly.se/wp-content/uploads/2024/09/EN-Touch-Pro-Installation-Manual-150324.pdf                                     | cb114b58c65dd613e9f22cacc96acb9e5a9483bd40efc06f19fb88d43dd501e7 |
| EN-Touch-Pro-Installation-Manual-150925.pdf                                     | https://nimly.se/wp-content/uploads/2025/09/EN-Touch-Pro-Installation-Manual-150925.pdf                                     | 1ea5e1b094e2b4c3e6f397b38f8ff346ebf4180a2c3eb9bb5060215d54987e08 |
| EN-Touch-Installation-Manual-150925.pdf                                         | https://nimly.se/wp-content/uploads/2025/09/EN-Touch-Installation-Manual-150925.pdf                                         | b71fa47db4ddb62ab94b02ab0a704535a9f845b65d2029e5dbb3de3f522f3caa |
| EN-Nimly-Indoor-Installation-Guide-051022.pdf                                   | https://nimly.se/wp-content/uploads/2023/11/EN-Nimly-Indoor-Installation-Guide-051022.pdf                                   | 22d91eed48f0096c40301841ee0e9029e0cc4fa65f43315f78a11ad5e496f068 |
| EN-Connect-Module-Installation-Guide-231024-bluetooth-app-and-nimly-connect.pdf | https://nimly.se/wp-content/uploads/2024/10/EN-Connect-Module-Installation-Guide-231024-bluetooth-app-and-nimly-connect.pdf | 9310ad939a9e68021a2a6ba9bf7a88e8beea7d36eb82d61903d3fb8023a0dfef |
| EN-Connect-Gateway-Installation-Guide-200623-frontpage.pdf                      | https://nimly.se/wp-content/uploads/2023/08/EN-Connect-Gateway-Installation-Guide-200623-frontpage.pdf                      | 110c6181420580e31535df98d6c4418d898dbcd91e5024498e4cf1af46213651 |
| EasyCodeT_Manual.pdf                                                            | https://easyaccess.no/wp-content/uploads/2021/02/EasyCodeT_Manual.pdf                                                       | 3040484f95aafedd4fd291620a932a75b695e8c834fe9ac7ef17dca6a761371e |
| A5_EasyFingerT_Manual-2.pdf                                                     | https://easyaccess.no/wp-content/uploads/2020/08/A5_EasyFingerT_Manual-2.pdf                                                | 350f3775cdfe9010e3ff168907afb1fd62de4ecc15fd3f74667064350b88e1e8 |
| E-life-Zigbee-Modul-User-Manual-v2.0-260121.pdf                                 | https://github.com/Koenkk/zigbee2mqtt/files/6015013/E-life.Zigbee.Modul.User.Manual.v2.0.pdf                                | 7f7be7949d77fd43c553ac2d79b0892f9793ae0efa751cde990b53373cce9116 |

`scripts/fetch_manuals.py` reads this table, not the one above: it matches rows by a 64-character SHA-256 in the last column, downloads anything missing or changed into `docs/manuals/`, verifies the hash, and runs `pdftotext -layout` for any PDF missing its `.txt`. Safe to run repeatedly.

```
python3 scripts/fetch_manuals.py
```

## White-label brands

All locks are the same Onesti Products AS hardware, resold under multiple brands (see `AGENTS.md`). Each brand's own site was checked for a lock manual PDF.

| Brand                         | Own manual? | Notes                                                                                         |
| ----------------------------- | ----------- | --------------------------------------------------------------------------------------------- |
| Nimly                         | Yes         | See tables above.                                                                             |
| EasyAccess                    | Yes         | See tables above.                                                                             |
| Keyfree (keyfree.no)          | Alias       | Own-hosted NO copies of the Code and Touch manuals; slot rules match Nimly's. Not downloaded. |
| Copiax (copiax.se)            | Alias       | Own-hosted, undated mirror of the Connect Module guide. Not downloaded.                       |
| Salus (salus-protect.com)     | Not found   | Checked product pages, /support/, /immunity/. Support is web pages, no PDF.                   |
| Homely (homely.no)            | Not found   | App integrates Nimly locks, refers users to the Nimly manual.                                 |
| Forebygg (forebygg.se)        | Not found   | Only marketing and social pages turned up.                                                    |
| Tekam Smarthus (tekam.no)     | Not found   | App supports Nimly locks, no Tekam-branded manual.                                            |
| Folklarm / Appsolut Sakerhet  | Not found   | Alarm service around Nimly locks, no own manual.                                              |
| Tryg Smart                    | Not found   | App-only integration, no Tryg-branded manual.                                                 |
| Safe4 Care / Confi.care       | Not found   | No product page or manual reference found at all.                                             |
| LF (Lansforsakringar, alf.se) | Not found   | Device page inside the Alf app, no downloadable manual.                                       |
| Larmify (larmify.se)          | Not found   | States outright they refer customers to the lock supplier for manuals.                        |

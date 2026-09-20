# If you're buying a new lock

The list we measure against: a lock on a Scandinavian door[^scandi] that Home Assistant can run completely. Lock state, who unlocked and how (code, tag, fingerprint), PIN management, no cloud, no vendor app, no extra hub, setup included. Against that list the Onesti/Nimly locks do one rare thing: with this integration they are, as of September 2026, the only lock we know of that attributes all three credential types per user into Home Assistant, fully locally.

The rest of the design speaks against them, and none of it is ZHA's doing:

- The firmware reports the last used PIN in plaintext on a Zigbee attribute, so a diagnostics dump or debug log contains real door codes.
- The only wake mechanism that works is physically throwing the bolt. Setting a PIN can lock your door.
- A battery change can silently stop all event reporting until you re-pair.
- Pairing takes keypad choreography and sometimes many attempts.
- The Zigbee module is a separate purchase and sometimes reports the wrong model string.
- No firmware updates over Zigbee, and no documentation of the event protocol. The only vendor Zigbee spec anyone has found is from 2021 and does not mention the event attribute.
- The lock does not know whether the door is open, only where the bolt is.
- The module has a Bluetooth radio too, which the vendor's app uses for fingerprint and tag enrollment, but whether a given module advertises is undocumented ("newer versions" only, says the guide), and nothing local can use it yet.

All of that is firmware. Onesti could report a credential id instead of the PIN, answer reads without moving the bolt, keep reporting configured across battery changes, publish the attribute documentation and ship OTA over Zigbee without new hardware: the radio is a Nordic part with Zigbee and Bluetooth on one die, and the module already asks for OTA images nobody publishes.

One thing is not firmware and cannot be fixed. The radio sits inside a metal lock body at the outermost point of the house, with no antenna sticking out. The signal is weak, the lock cannot relay for anything, and it lives off whatever mains-powered device is nearest. Budget for one of those near the door on the inside, and for an afternoon of moving things around. Without it the lock is unreliable or will not pair at all, and a battery-powered repeater does not count. [debugging.md](debugging.md#signal-issues) has the measurements and what to do, [community-reports.md](community-reports.md#range-and-coverage) what other owners went through.

No alternative passes the same list. Matter over Thread comes closest on paper, and Home Assistant manages users, PINs and RFID on Matter locks since 2026.4 (the Aqara U200 works with it), but Matter tells you how the door was operated, not by whom, and per-user attribution is still an open feature discussion. The Nuki Ultra Nordics reports user IDs over local MQTT, but its keypad and fingerprint users can only be managed in Nuki's app with an account. The ID Lock 202 Multi is fully local with per-user attribution for code and RFID over Z-Wave, but has no fingerprint reader. Tedee, Yale Doorman L3, Danalock and SwitchBot fail earlier: bridge required, cloud app, no reader to attribute, or users managed in an app.

If you already own a Nimly/Onesti lock, keep it. This integration is the most complete way to run it, fully local on stable ZHA, and a cheap Zigbee door contact covers the one thing the lock cannot tell you.

## Skip the vendor's hub

The lock is run either through Home Assistant or through Nimly's own hub and app. It talks to one system at a time, and this integration exists for the first. If you are buying for Home Assistant, you do not need the hub.

It only does locks. The box is a general-purpose smart home hub built by someone else, with radios for far more, but Nimly's software on it is set up for their own locks: the newest version is capped at two locks and three smart plugs and shows nothing from another brand.

Home Assistant cannot talk to it. There is no local connection of any kind, no setting, no address, no port that answers. Everything goes out to Nimly's servers and back, so with the hub you get their app and nothing else. Two people asked on the Home Assistant forum whether it could be integrated, in 2023 and in 2024, and nobody answered.

There is no "pro" version to wait for. What exists is two hubs: an older one that could do more, now discontinued, and the plug-in one that replaced it and does less. If somebody told you the better one is out there, that is probably the old one, and you cannot buy it. The app calls it "PRO Gateway" and says time-limited access needs it, which is where the name comes from.

Owners who do use the hub complain about the same thing as everyone else, range, and several moved their locks onto Home Assistant for that reason alone.

## The field, checked September 2026

Every lock we evaluated, so the next round does not start over. "Who in HA" means per-user attribution reaching Home Assistant events, fully locally.

| Lock                              | Local without cloud/app/hub  | Who in HA                       | Code / tag / finger         | Fails the list on                                                            |
| --------------------------------- | ---------------------------- | ------------------------------- | --------------------------- | ---------------------------------------------------------------------------- |
| Nimly (this integration)          | Yes                          | Yes, all three credential types | All three                   | Its own firmware (list above), no door-open state                            |
| Aqara U200                        | Thread, but setup needs app  | No, only how (Matter)           | Code, finger                | Who-attribution, setup app, "select Scandi cylinders"                        |
| Nuki Ultra Nordics                | Matter or built-in MQTT      | User IDs over MQTT [^nuki]      | Keypad/finger = accessories | Users only manageable in app with account                                    |
| ID Lock 202 Multi                 | Yes (no app or cloud exists) | Code and tag, via Z-Wave [^idl] | Code, tag, no finger        | No fingerprint, 25 slots, needs a Z-Wave radio, module battery-drain history |
| Tedee GO2/PRO                     | No, bridge required          | No, activity log not local      | Code via keypad accessory   | Bridge, no attribution                                                        |
| Yale Doorman L3                   | No                           | No                              | Code, tag                   | Cloud app is the HA route, codes managed in app                              |
| Danalock V3                       | Z-Wave/Zigbee local          | Nothing to attribute            | None built in               | No keypad or reader at all                                                    |
| SwitchBot Lock Ultra              | Bluetooth or Matter hub      | Unproven                        | Code, finger                | Users managed in app, Nordic mount unverified                                |
| Ultraloq U-Bolt Pro Z-Wave        | Yes, Z-Wave                  | Codes yes, finger unproven      | Code, finger                | No RFID, US deadbolt doors only                                              |
| Yale Assure Lock 2 Touch (Z-Wave) | Yes, Z-Wave                  | Codes yes, finger unproven      | Code, finger                | No RFID, US deadbolt doors only                                              |

Matter in general: Home Assistant manages users, PINs and RFID on Matter locks since 2026.4 and shows how the door was operated since 2025.9, but not by whom. Per-user attribution over Matter is an open feature discussion with one rejected PR as of early 2026.

What owners report, on the Norwegian home-automation forum and in the long Home Assistant thread: the pain is in the radio add-on modules, not the locks. Nimly's Connect Module has a battery-drain history that ended with Nimly shipping a revised module, and modules that drop off the network until re-paired match this repo's debugging guide. ID Lock's Z-Wave module has years of battery-drain threads of its own, some ended by a firmware update. Nimly on ZHA is reported working by several owners, and the angriest reviews are about the vendor's gateway and app, which this integration does not touch.

[^scandi]: Scandinavian front doors take a modular mortise lock case (Norwegian: modullåskasse) cut to the Scandinavian standard, with the Scandinavian oval cylinder where a key cylinder is used, not the continental euro profile (DIN) cylinder. The Nimly locks replace the whole lock: their own mortise case goes into the existing recess, which the manuals require to follow SS 817375:2018 with a 225 x 22 mm faceplate, plus an outside keypad unit and an inside unit bolted through the door. So check the lock case in your door, not the cylinder; a Nimly has no cylinder beyond the emergency keyhole on some models. Retrofit locks like Nuki, Tedee and Aqara grip a cylinder instead, which is why they need Nordics variants or adapters here. Off the Scandinavian profile the answer does not improve: US Z-Wave deadbolts attribute keypad codes per user locally, but the two with a fingerprint reader (Ultraloq U-Bolt Pro Z-Wave, Yale Assure Lock 2 Touch) have no RFID, and owners have not confirmed fingerprint attribution in Home Assistant. Tuya and Aqara Zigbee locks for Asian markets carry all three credential types but hang off a vendor hub and app. No lock passes the full list on any door profile.

[^nuki]: Verified for the Ultra's MQTT API; assumed identical on the Nordics variant, same electronics.

[^idl]: The Z-Wave manual documents user indices in the unlock notifications for both keypad and RFID. We have not seen an event dump from a live 202 in Home Assistant.

## Where to buy, checked 2026-09-20

Norway only. Nimly's [own retailer page](https://nimly.no/forhandlere/) names eighteen
shops (OBS Bygg, OBS Byggmix, Megaflis, Power, Elektroimportøren, Gausdal
Landhandleri, Maxbo, Mekk, Byggmakker, Elkjøp, Byggern, Eldirekte, Gla Pris,
Modern Home, R. Bergersen, Jernia, Clas Ohlson, Komplett) and twenty locksmiths
as installers, among them Tekam, which also rents the same cloud platform under
its own app. Kjell & Company sells the range too without being on that list.
Dustin, Ahlsell, Staypro and Copiax blocked or returned nothing for the search,
so we do not know either way. Sweden and Denmark have vendor sites
([nimly.se](https://nimly.se/), [nimly.dk](https://nimly.dk/)) but no retailer
we could confirm. Nothing in the UK: `keyfree.co.uk`, the Safe4 brand in the
tenant roster, is a parked domain for sale.

Prices are what the shop showed on the day. The module you need for Home
Assistant is the Connect Module, and it fits every lock in the range.

| What | Elektroimportøren | Kjell & Company | EAN |
| --- | --- | --- | --- |
| Connect Module (Zigbee + BLE) | 579 (art. 5800460, EL 58 004 60) | 539 (art. 52187) | 5704571842582 |
| Connect Bridge (vendor hub) | 1499 (art. 5803074) | 1349 (art. 52109) | 5704571197033 |
| Connect Gateway (older hub) | not listed | 1849 (art. 52188) | not seen |
| Code | 2799 | 2990 | 5704571195053 |
| Code Pro | 4490 | 4490 | not seen |
| Touch | 3499 | 3290 | not seen |
| Touch Pro | 3999 | 3990 | not seen |
| Indoor | 2590 | not listed | not seen |
| Keybox | not listed | not listed | 5704571195077 |
| RFID tags, 3-pack | 249,90 | 199 | not seen |
| Rechargeable battery | 349,90 | 399 | not seen |
| Spacer 1 mm / 2 mm | 199,90 | not listed | not seen |

Every EAN we found starts `5704571`, a GS1 Denmark prefix, whatever the brand
on the box. Elektroimportøren also prints the vendor's own article number: 74
for the module, 86 for the bridge.

Going out of the range: the Connect Gateway, the older hub, is gone from
nimly.no, from Elektroimportøren and from Megaflis, and only Kjell still lists
it. Vendor manuals printed in 2025 still tell you to buy one. If a shop offers
it, you are buying the discontinued hub, and neither hub matters for Home
Assistant anyway.

Not in a shop at all: the **Keybox**, a wall-mounted key safe with the same
keypad and the same Connect Module socket as the locks. The vendor publishes a
[product guide](https://nimly.se/wp-content/uploads/2025/04/Keybox-produktoversikt-250425.pdf)
and an [installation guide](https://nimly.se/wp-content/uploads/2025/04/EN-Keybox-Installation-Guide-291124.pdf)
with an EAN, so it exists, but no retailer we checked carries it. Whether this
integration can drive one is untested; see
[hardware-generations.md](hardware-generations.md#the-keybox-takes-the-same-module).

EasyAccess, the same hardware under the other Norwegian brand, sells its
[Zigbee/BLE module](https://easyaccess.no/product/easyring-lock-module/) at 899
for the EasyFingerTouch and EasyCodeTouch locks. Its page carries a warning
Nimly's does not: with the module fitted and not joined to a smart home system,
it stays in search mode and drains the lock's battery.

## Sources

[Elektroimportøren's Nimly range](https://www.elektroimportoren.no/nimly/), [Kjell's Nimly range](https://www.kjell.com/no/varemerker/nimly), [Nimly's retailer list](https://nimly.no/forhandlere/), [Nimly product documents](https://nimly.no/produktinformasjon/), [EasyAccess Zigbee/BLE module](https://easyaccess.no/product/easyring-lock-module/), [Connect Bridge at nimly.se](https://nimly.se/product/connect-bridge/), [Nimly Code at OBS Bygg](https://www.obsbygg.no/sikkerhet/elektroniske-laser-og-tilbehor/2632777), all read 2026-09-20.

[HA 2026.4 Matter lock management](https://www.home-assistant.io/blog/2026/04/01/release-20264/), [HA 2025.9 changed_by](https://www.home-assistant.io/changelogs/core-2025.9/), [per-user attribution discussion](https://github.com/orgs/home-assistant/discussions/2611), [Nuki MQTT API](https://developer.nuki.io/t/mqtt-api-specification-v1-4/19223), [Nuki on Matter PIN management](https://developer.nuki.io/t/allow-keypad-pin-code-management-through-matter/39676), [ID Lock 202 Z-Wave manual](https://idlock.no/wp-content/uploads/2023/07/User-Manual-Z-Wave-202-EN.pdf), [Aqara U200](https://eu.aqara.com/products/aqara-smart-lock-u200), [U200 attribution thread](https://community.home-assistant.io/t/aqara-u200-matter-integration/748813), [Tedee integration docs](https://www.home-assistant.io/integrations/tedee/), [SwitchBot HA support](https://blog.switch-bot.com/switchbot-lock-ultra-is-now-compatible-with-home-assistant/), [Nimly Touch Pro manual (SS 817375:2018)](https://nimly.se/wp-content/uploads/2024/09/EN-Touch-Pro-Installation-Manual-150324.pdf), [Danalock on Euro vs Scandi cylinders](https://danalock.com/how-to-choose-model), [Ultraloq U-Bolt Pro Z-Wave](https://u-tec.com/blogs/news/ultraloq-u-bolt-pro-z-wave-smart-lock-now-works-with-home-assistant), [Yale Assure Lock 2 Touch Z-Wave](https://shopyalehome.com/products/yale-assure-lock-2-touch-with-z-wave), [fingerprint attribution unconfirmed](https://community.home-assistant.io/t/ultralq-u-bolt-pro-z-wave-vs-yale-assure-lock-2-touch-with-z-wave-and-automation-based-on-code-fingerprint/870216), [Nimly owners thread](https://community.home-assistant.io/t/nimly-lock-with-zigbee-module/523634), [ID Lock battery threads](https://www.hjemmeautomasjon.no/forums/topic/11218-id-lock-150-sluker-batteri-g%C3%A5r-ikke-i-dvale/).

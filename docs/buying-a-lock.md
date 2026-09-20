# If you're buying a new lock

The measuring stick: a lock on a Scandinavian door[^scandi] that Home Assistant can run completely. Lock state, who unlocked and how (code, tag, fingerprint), PIN management, no cloud, no vendor app, no extra hub, setup included. Against that list the Onesti/Nimly locks do one rare thing: with this integration they are, as of September 2026, the only lock we know of with per-user attribution for all three credential types into Home Assistant, fully locally.

The rest of the design speaks against them, and none of it is ZHA's doing:

- The firmware reports the last used PIN in plaintext on a Zigbee attribute, so a diagnostics dump or debug log contains real door codes.
- The only wake mechanism that works is physically throwing the bolt. Setting a PIN can lock your door.
- A battery change can silently stop all event reporting until you re-pair.
- Pairing takes keypad choreography and sometimes many attempts.
- The Zigbee module is a separate purchase and sometimes reports the wrong model string.
- No firmware updates over Zigbee, and no documentation of the event protocol. The only vendor-written Zigbee spec anyone has found dates from 2021 and does not mention the event attribute at all.
- The lock does not know whether the door is open, only where the bolt is.
- The module has a Bluetooth radio too, which the vendor's own app uses for fingerprint and tag enrollment, but whether a given module actually advertises is undocumented ("newer versions" only, says the guide), and nothing local can use it yet.

Everything on that list is firmware, and Onesti could fix all of it if they cared to: report a credential id instead of the PIN, answer reads without moving the bolt, keep reporting configured across battery changes, publish the attribute documentation, ship OTA over Zigbee. Nothing here needs new hardware: the radio is a Nordic part with Zigbee and Bluetooth on one die, and the module already asks for OTA images nobody publishes.

Real alternatives, measured against the same list: none pass. Matter over Thread comes closest on paper, and Home Assistant manages users, PINs and RFID on Matter locks since 2026.4 (the Aqara U200 works with it), but Matter tells you how the door was operated, not by whom, and per-user attribution is still an open feature discussion. The Nuki Ultra Nordics reports user IDs over local MQTT, but its keypad and fingerprint users can only be managed in Nuki's app with an account. The ID Lock 202 Multi is fully local with per-user attribution for code and RFID over Z-Wave, but has no fingerprint reader. Tedee, Yale Doorman L3, Danalock and SwitchBot fall faster: bridge required, cloud app, no reader to attribute, or users managed in an app.

If you already own a Nimly/Onesti lock, keep it. This integration is the most complete way to run it, fully local on stable ZHA, and a cheap Zigbee door contact covers the one thing the lock cannot tell you.

## The field, checked September 2026

Every lock we evaluated, so the next round does not start from scratch. "Who in HA" means per-user attribution reaching Home Assistant events, fully locally.

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

Matter in general: Home Assistant manages users, PINs and RFID on Matter locks since 2026.4, and shows how the door was operated since 2025.9, but not by whom. Per-user attribution over Matter is an open feature discussion with one rejected PR as of early 2026.

What owners report, on the Norwegian home-automation forum and in the long Home Assistant thread on these locks: the pain sits in the radio add-on modules, not the locks. Nimly's Connect Module has a battery-drain history that ended in Nimly shipping a revised module, and modules that drop off the network until re-paired match this repo's debugging guide. ID Lock's Z-Wave module has years of battery-drain threads of its own, some ended by a firmware update. Nimly on ZHA is reported working by several owners, and the angriest reviews are about the vendor's own gateway and app, which this integration does not touch.

[^scandi]: Scandinavian front doors take a modular mortise lock case (Norwegian: modullåskasse) cut to the Scandinavian standard, with the Scandinavian oval cylinder where a key cylinder is used, not the continental euro profile (DIN) cylinder. The Nimly locks replace the whole lock, not just the fittings: their own mortise case goes into the existing recess, which the manuals require to follow SS 817375:2018 with a 225 x 22 mm faceplate, plus an outside keypad unit and an inside unit bolted through the door. So check the lock case in your door, not the cylinder; a Nimly has no cylinder beyond the emergency keyhole on some models. Retrofit locks like Nuki, Tedee and Aqara grip a cylinder instead, which is why they need Nordics variants or adapters here. And off the Scandinavian profile the answer does not improve: US Z-Wave deadbolts attribute keypad codes per user locally, but the two with a fingerprint reader (Ultraloq U-Bolt Pro Z-Wave, Yale Assure Lock 2 Touch) have no RFID, and owners have not confirmed fingerprint attribution in Home Assistant. Tuya and Aqara Zigbee locks for Asian markets carry all three credential types but hang off a vendor hub and app. No lock passes the full list on any door profile.

[^nuki]: Verified for the Ultra's MQTT API; assumed identical on the Nordics variant, same electronics.

[^idl]: The Z-Wave manual documents user indices in the unlock notifications for both keypad and RFID. We have not seen an event dump from a live 202 in Home Assistant.

## Sources

[HA 2026.4 Matter lock management](https://www.home-assistant.io/blog/2026/04/01/release-20264/), [HA 2025.9 changed_by](https://www.home-assistant.io/changelogs/core-2025.9/), [per-user attribution discussion](https://github.com/orgs/home-assistant/discussions/2611), [Nuki MQTT API](https://developer.nuki.io/t/mqtt-api-specification-v1-4/19223), [Nuki on Matter PIN management](https://developer.nuki.io/t/allow-keypad-pin-code-management-through-matter/39676), [ID Lock 202 Z-Wave manual](https://idlock.no/wp-content/uploads/2023/07/User-Manual-Z-Wave-202-EN.pdf), [Aqara U200](https://eu.aqara.com/products/aqara-smart-lock-u200), [U200 attribution thread](https://community.home-assistant.io/t/aqara-u200-matter-integration/748813), [Tedee integration docs](https://www.home-assistant.io/integrations/tedee/), [SwitchBot HA support](https://blog.switch-bot.com/switchbot-lock-ultra-is-now-compatible-with-home-assistant/), [Nimly Touch Pro manual (SS 817375:2018)](https://nimly.se/wp-content/uploads/2024/09/EN-Touch-Pro-Installation-Manual-150324.pdf), [Danalock on Euro vs Scandi cylinders](https://danalock.com/how-to-choose-model), [Ultraloq U-Bolt Pro Z-Wave](https://u-tec.com/blogs/news/ultraloq-u-bolt-pro-z-wave-smart-lock-now-works-with-home-assistant), [Yale Assure Lock 2 Touch Z-Wave](https://shopyalehome.com/products/yale-assure-lock-2-touch-with-z-wave), [fingerprint attribution unconfirmed](https://community.home-assistant.io/t/ultralq-u-bolt-pro-z-wave-vs-yale-assure-lock-2-touch-with-z-wave-and-automation-based-on-code-fingerprint/870216), [Nimly owners thread](https://community.home-assistant.io/t/nimly-lock-with-zigbee-module/523634), [ID Lock battery threads](https://www.hjemmeautomasjon.no/forums/topic/11218-id-lock-150-sluker-batteri-g%C3%A5r-ikke-i-dvale/).

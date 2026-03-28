# Session Notes — 28. mars 2026

## Nøkkelfunn: Onesti operation event decoding

**Attributt 0x0100 på DoorLock cluster (0x0101) inneholder komplett event-data!**

Nimly/Onesti sender et `Report_Attributes` med `attrid=0x0100` som bitmap32 for hver lås/opplåsings-hendelse. Formatet er little-endian:

```
Byte 0: user_slot (0 = system/auto, 3+ = brukerslot)
Byte 1: reservert (alltid 0)
Byte 2: action (1 = lock, 2 = unlock)
Byte 3: source (2 = keypad, 10 = auto/system, 1 = RF, 3 = manual)
```

Eksempler fra live-data:
- `0x02020003` → slot 3, unlock, keypad = "Fredrik låste opp med kode"
- `0x0A010000` → slot 0, lock, auto = auto-lock etter timeout

**Attributt 0x0101** inneholder PIN-koden i BCD: `0x09 0x27` = "0927"

### Verifisert med Zigbee debug-logging

Alle tre hendelsestyper bekreftet:
1. PIN-opplåsing → `attrid=0x0100` med user_slot + keypad source
2. Auto-lock → `attrid=0x0100` med slot 0 + auto source
3. Lock state → `attrid=0x0000` med enum8 (1=locked, 2=unlocked)

## Hva som ikke fungerte

### 1. ZHA `last_action_user` / `last_action_source` sensorer
- Oppdateres IKKE ved keypad/fysisk bruk
- Beholder stale verdier fra siste HA-kommando
- Kjent community-problem (HA forum-tråd med 12+ sider)

### 2. `zha_event` bus events
- `operation_event_notification` (ZCL 0x0020) mottas aldri
- Nimly sender data via attribute reports, ikke cluster commands

### 3. `EVENT_STATE_CHANGED` på `lock.dorlasen`
- Fanger locked↔unlocked, men uten brukerinfo
- `last_action_user` er stale

### 4. zigpy cluster `add_listener` + `attribute_updated`
- Registrert listener på CustomDeviceV2 cluster (depth 2)
- `attribute_updated` callback trigges IKKE for `Report_Attributes`
- Grunn: zigpy cacher attribute-verdier og skipper callback hvis verdien er lik
- Løsning: bruk `handle_cluster_request` i stedet (kalles for ALLE ZCL-kommandoer)

### 5. ZHA device chain
- `ZHADeviceProxy` → `Device` (in_clusters tom!) → `CustomDeviceV2` (in_clusters her)
- Må walke 3 nivåer for å finne clusteret
- Koden gjør dette automatisk i `coordinator._get_cluster()`

## Gjeldende tilstand (utestet)

`handle_cluster_request` er implementert men **ikke testet ennå** med en faktisk opplåsing.

Listener er registrert på CustomDeviceV2 NimlyDoorLock cluster.

**Neste steg:**
1. Test opplåsing med PIN — sjekk om `handle_cluster_request` trigger
2. Hvis ikke: problemet er at quirk-clusteret ikke er det som mottar Report_Attributes. Da må vi registrere på Device-nivå (depth 1) eller bruke zigpy application-level callback
3. Alternativ: lytte på zigpy event bus direkte (`zigpy.event` Emitting event `attribute_report`)

## Integrasjon renamed: nimly_pro → onesti_lock

- Directory: `custom_components/onesti_lock/`
- Domain: `onesti_lock`
- Supported models: NimlyPRO, NimlyPRO24, easyCodeTouch_v1, EasyCodeTouch, EasyFingerTouch
- Manufacturer: Onesti Products AS
- Config entry migrert direkte i `.storage/core.config_entries`

## Brukere på låsen

| Slot | Navn | PIN |
|------|------|-----|
| 1 | Fredrik | (gammel, pre-slot-fix) |
| 3 | Fredrik | 0927 |
| 4 | Frode | 3293 |
| 5 | Anna | ? |
| 6 | Annicken | ? |

## HA Leirnes status

- SSH: `ssh ha-leirnes-local` (root, nøkkelbasert)
- Custom domain: `https://ha.leirnes.no`
- Debug logging: `zigpy.zcl: debug` + `custom_components.onesti_lock: debug`
- Frigate: installert, kjører, ingen kameraer (trenger Reolink-passord)
- HACS: installert
- Gammel configuration.yaml er ryddet (ingen input_helpers, scripts, dashboards igjen)

## Gotchas

- HA Green har 32 GB eMMC — debug logging fyller fort. Husk å skru av zigpy debug etter testing
- SSH addon sin sshd_config overskrives ved restart — nøkler må ligge i addon-config
- Beads pre-commit hook var fjernet men satt igjen i gammel config
- Factory master code er `123` — MÅ byttes

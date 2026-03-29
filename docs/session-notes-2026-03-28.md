# Session Notes — 28-29. mars 2026

## Gjennombrudd: "Kari låste opp med kode"

Aktivitetssensoren identifiserer nå **hvem** som låste opp og **hvordan**. Verifisert med live data:

```
Lock event: unlock by Kari via keypad (raw: 0x02020004)
Lock event: lock by system via auto (raw: 0x0a010000)
```

Ingen andre HA-integrasjoner har fått dette til med Nimly/Onesti over ZHA.

---

## Nøkkelfunn: Onesti operation event decoding

**Attributt 0x0100 på DoorLock cluster (0x0101) inneholder komplett event-data.**

Nimly/Onesti sender `Report_Attributes` med `attrid=0x0100` som bitmap32 for hver hendelse. Little-endian:

```
Byte 0: user_slot (0 = system/auto, 3+ = brukerslot)
Byte 1: reservert (alltid 0)
Byte 2: action (1 = lock, 2 = unlock)
Byte 3: source (1 = RF, 2 = keypad, 3 = manual, 10 = auto/system)
```

Verifiserte eksempler:
- `0x02020003` → slot 3, unlock, keypad = "Ola låste opp med kode"
- `0x02020004` → slot 4, unlock, keypad = "Kari låste opp med kode"
- `0x0A010000` → slot 0, lock, auto = auto-lock etter timeout

**Attributt 0x0101** inneholder PIN-koden i BCD: `0x09 0x27` = "5478"

**Attributt 0x0000** inneholder lock state: enum8 (1=locked, 2=unlocked)

---

## Hva som IKKE fungerte (og hvorfor)

### 1. ZHA `last_action_user` / `last_action_source` sensorer
- Oppdateres IKKE ved keypad/fysisk bruk
- Beholder stale verdier fra siste HA-kommando
- Kjent community-problem (HA forum-tråd med 12+ sider)

### 2. `zha_event` bus events
- `operation_event_notification` (ZCL 0x0020) mottas aldri fra Nimly
- Nimly sender data via attribute reports, ikke cluster commands

### 3. `EVENT_STATE_CHANGED` på `lock.dorlasen`
- Fanger locked↔unlocked, men uten brukerinfo
- `last_action_user` er stale — viser alltid siste HA-kommando

### 4. `add_listener` + `attribute_updated` callback
- Registrert på CustomDeviceV2 cluster (depth 2 i ZHA-kjeden)
- `attribute_updated` trigges IKKE for attrid 0x0100
- **Grunn:** zigpy wrapper `_update_attribute` i `_suppress_attribute_update_event` for ukjente attributter (0x0100 er ikke definert i ZCL Door Lock spec)
- Selv uten suppress: zigpy cacher verdien og skipper callback hvis verdien er lik forrige

### 5. `add_listener` + `handle_cluster_request` callback
- `Report_Attributes` er en **general** ZCL-kommando, ikke en cluster-kommando
- `handle_cluster_request` kalles bare for cluster-spesifikke kommandoer
- zigpy dispatcher general commands via `listener_event("general_command", ...)` men det trigget heller ikke listenere pålitelig

### 6. `add_listener` + `general_command` callback
- Viste seg at `listener_event("general_command", ...)` ikke dispatches til `add_listener`-baserte listeners for Report_Attributes
- zigpy sin handle_cluster_general_request håndterer Report_Attributes internt og emitter events via `cluster.emit()`, ikke `listener_event()`

### Løsningen: `cluster.on_event("attribute_report", callback)`

zigpy sin `EventBase.emit()` fyrer for **alle** attribute reports via `cluster.emit("attribute_report", event)`. Dette er den eneste pålitelige måten å fange Onesti sin custom attributt.

```python
unsub = cluster.on_event("attribute_report", _on_attribute_report)
```

Eventen inneholder `event.attribute_id`, `event.raw_value`, `event.device_ieee` etc.

### ZHA device chain (viktig for cluster-tilgang)

```
ZHADeviceProxy (depth 0) — has_endpoints=False
  → Device (depth 1) — has_endpoints=True, in_clusters=EMPTY
    → CustomDeviceV2 (depth 2) — has_endpoints=True, in_clusters=POPULATED
```

Clusteret med faktisk data lever på depth 2. `coordinator._get_cluster()` walker kjeden automatisk.

---

## Integrasjon: onesti_lock

- Directory: `custom_components/onesti_lock/`
- Domain: `onesti_lock`
- Renamed fra `nimly_pro` (config entry migrert i `.storage/core.config_entries`)
- Supported models: NimlyPRO, NimlyPRO24, easyCodeTouch_v1, EasyCodeTouch, EasyFingerTouch
- Manufacturer: Onesti Products AS

### Features som fungerer
- PIN-kode sett/fjern via UI (Settings → Configure) og services
- Slot→navn mapping, persistert i config entry options
- Aktivitetssensor: "Kari låste opp med kode" ✅
- 10 slot-sensorer (slot 3-12) med has_pin/has_rfid attributter
- Options flow med norsk/engelsk UI

### Brukere på låsen

| Slot | Navn | PIN | Verifisert |
|------|------|-----|-----------|
| 1 | Ola | (gammel, pre-slot-fix) | ? |
| 3 | Ola | 5478 | ✅ keypad |
| 4 | Kari | 3293 | ✅ keypad |
| 5 | Anna | ? | satt via UI |
| 6 | Annicken | ? | ✅ keypad |

---

## HA Leirnes status

- SSH: `ssh ha-leirnes-local` (root@192.168.80.125, nøkkel ~/.ssh/hytte_ha)
- Custom domain: `https://ha.leirnes.no`
- Nabu Casa: `https://6g1lby1pzdj4yibzlr4splfrelwg41ei.ui.nabu.casa`
- Debug logging: `zigpy.zcl: debug` + `custom_components.onesti_lock: debug` — **HUSK Å SKRU AV** (fyller 32 GB eMMC)

### Installerte integrasjoner
- HACS ✅
- Nord Pool (NO5) ✅
- Strømkalkulator ✅
- Onesti Lock ✅
- Frigate (addon, uten kameraer — trenger Reolink-passord)
- Template sensor: `sensor.pappa` (Kari lokasjon: På hytten/Hjemme/Borte)

### Oppryddet
- Fjernet: input_helpers, scripts, automations, dashboards for dørlås (erstattet av integrasjon)
- Fjernet: lock_code_manager, zigbee_lock_manager (fungerte ikke)
- Fjernet: beads hooks og filer fra integrasjons-repoet

---

## Gotchas

- HA Green har 32 GB eMMC — debug logging fyller fort
- SSH addon sshd_config overskrives ved restart — nøkler må ligge i addon-config via web UI
- Beads pre-commit hook er fjernet fra git repo
- **Factory master code er `123` — MÅ byttes** (`*000 123* <ny kode>* <ny kode>*` på keypad)
- PIN-koder avsluttes med `#` på keypadet
- Slots 0-2 er reservert for master codes, brukerkoder starter på slot 3
- Nimly ZCL response quirk: `IndexError: tuple index out of range` ved PIN-kommandoer — kommandoen når låsen, feilen er i respons-parsing. Integrasjonen catcher dette.

---

## Neste steg

- [ ] Bytte masterkode fra factory default
- [ ] Skru av debug logging (zigpy.zcl)
- [ ] Teste med flere opplåsingsmetoder (nøkkel, RFID, fingeravtrykk, remote)
- [ ] Rydde warning-level logging i integrasjonen (bytte til info/debug)
- [ ] Vurdere å bidra Onesti event-decoding upstream til zha-device-handlers
- [ ] Publisere integrasjonen på GitHub for andre Onesti-brukere

# Session Notes — 28-30. mars 2026

## Gjennombrudd: "Kari låste opp med kode"

Aktivitetssensoren identifiserer nå **hvem** som låste opp og **hvordan**. Verifisert med live data på hytta:

```
Lock event: unlock by Kari via keypad (raw: 0x02020004)
Lock event: lock by system via auto (raw: 0x0a010000)
```

Ingen andre ZHA-integrasjoner har fått dette til. Z2M fikk det i [PR #11332](https://github.com/Koenkk/zigbee-herdsman-converters/pull/11332) — vi fant det uavhengig.

---

## Onesti operation event — komplett dekodings-referanse

### Attributt 0x0100 — operation event (bitmap32, little-endian)

```
Byte 0: user_slot (0 = system/auto, 3+ = brukerslot)
Byte 1: reservert (alltid 0)
Byte 2: action (1 = lock, 2 = unlock)
Byte 3: source (1 = RF, 2 = keypad, 3 = manual, 10 = auto/system)
```

Verifiserte eksempler:
| Raw | Bytes (LE) | Betydning |
|-----|-----------|-----------|
| `0x02020003` | [03, 00, 02, 02] | Slot 3 (Ola), unlock, keypad |
| `0x02020004` | [04, 00, 02, 02] | Slot 4 (Kari), unlock, keypad |
| `0x0A010000` | [00, 00, 01, 0A] | System, lock, auto |
| `0x02020000` | [00, 00, 02, 02] | Slot 0 (master), unlock, keypad |

### Attributt 0x0101 — PIN-kode (LVBytes, BCD)

`0x09 0x27` = "5478" (hver byte er to BCD-siffer)

### Attributt 0x0000 — lock state (enum8)

- `1` = locked
- `2` = unlocked

---

## Hvorfor zigpy listener-metoder ikke fungerer

Vi testet **6 forskjellige tilnærminger** for å fange events. Bare én fungerte:

| # | Metode | Resultat | Årsak |
|---|--------|----------|-------|
| 1 | ZHA `last_action_user` sensor | ❌ Stale | ZHA-sensor oppdateres ikke på keypad-events |
| 2 | `zha_event` bus | ❌ Ingen events | Nimly sender ikke `operation_event_notification` (0x0020) |
| 3 | `lock.entity` state change | ⚠️ Delvis | Fanger lock↔unlock, men uten bruker/source |
| 4 | `add_listener` + `attribute_updated` | ❌ Aldri kalt | zigpy wrapper `_update_attribute` i `_suppress_attribute_update_event` for ukjente attributter (0x0100 er ikke i ZCL spec) |
| 5 | `add_listener` + `general_command` | ❌ Aldri kalt | `listener_event("general_command")` dispatches ikke til add_listener for Report_Attributes |
| 6 | **`cluster.on_event("attribute_report")`** | ✅ Fungerer | zigpy sin EventBase emitter for ALLE rapporter via `cluster.emit()` |

### Nøkkel-innsikt fra zigpy kildekode

```python
# handle_message() dispatcher:
if hdr.frame_control.is_cluster:
    self.handle_cluster_request(hdr, args)           # → cluster commands
    self.listener_event("cluster_command", ...)       # → add_listener callbacks
else:
    self.listener_event("general_command", hdr, args) # → IKKE dispatched videre
    self.handle_cluster_general_request(hdr, args)    # → intern håndtering

# handle_cluster_general_request for Report_Attributes:
# - Ukjente attributter: _suppress_attribute_update_event → attribute_updated BLOKKERT
# - Emitter: cluster.emit("attribute_report", event) → DETTE FUNGERER
```

### ZHA device chain

```
ZHADeviceProxy (depth 0) — has_endpoints=False
  → Device (depth 1) — has_endpoints=True, in_clusters=EMPTY
    → CustomDeviceV2 (depth 2) — has_endpoints=True, in_clusters=POPULATED
```

`coordinator._get_cluster()` walker kjeden automatisk ned til depth 2.

---

## Sleepy device og PIN-setting timeout

### Problemet

Nimly/Onesti er batteribaserte Zigbee EndDevices som sover. Meldinger til sovende enheter bufres hos parent-router med **TTL 7.68 sekunder**. Etter det kastes meldingen.

### Hva fungerer og hva som ikke fungerer

| Kommando | Fungerer? | Grunn |
|----------|-----------|-------|
| `lock/unlock` | ✅ Ja | ZHA bruker extended timeout + retry |
| `set_pin_code` (direkte cluster) | ❌ Timeout | Standard zigpy timeout for kort |
| `zha.issue_zigbee_cluster_command` | ❌ Timeout | Marginalt bedre, men fortsatt for kort etter batteribytte |
| Manuell keypad → event | ✅ Ja | Låsen sender aktivt, trenger ikke motta |

### Hva vekker Zigbee-radioen?

- **Keypad-berøring** vekker keypadet, men ikke nødvendigvis Zigbee-radioen
- **Komplett kode + # / fysisk lås/opplås** vekker radioen (trigger state report)
- **Lock/unlock fra HA** vekker radioen (ZHA har spesiell håndtering)
- **Ute-panel = inne-panel** — ingen forskjell for Zigbee

### Etter batteribytte

Låsen re-joiner Zigbee-nettverket men:
- Poll-intervall kan være langt
- Bindings kan ha blitt reset
- Reconfigure feiler (binding + reporting mislykkes)
- Battery-rapportering stopper
- Lock/unlock fungerer fortsatt (enklere kommandoer)
- set_pin timeouter konsekvent

**Løsning:** Vent timer/dager til bindinger re-etableres, eller fjern og re-par låsen i ZHA.

### Forsøk på å omgå timeout

1. Lock → sleep 0.5s → set_pin: **Timeout** — for treg
2. Lock + set_pin simultant via API: **Timeout** — lock OK, set_pin for sent
3. Loop med 20 forsøk hvert 3. sek: **Timeout** — `ha service call` finnes ikke, API auth feilet
4. ZHA `issue_zigbee_cluster_command` service: **Implementert men utestet** (siste forsøk)

---

## Relatert arbeid i community

### Z2M PR #11332 — PIN code parsing og user tracking

[PR #11332](https://github.com/Koenkk/zigbee-herdsman-converters/pull/11332) fikser nøyaktig det samme som oss for Zigbee2MQTT:
- PIN-koder ble vist som hex (`313131`) → nå ASCII (`111`)
- `last_unlock_user` var tom → nå slot-nummer
- Nye attributter: voltage, auto_relock_time, PIN limits

Vi fant bitmap32-formatet uavhengig fra rå Zigbee-fangst.

### Kjente Onesti-modeller

Alle er samme hardware med ulikt merke:

| Zigbee-modell | Merkenavn | Produsent |
|---------------|-----------|-----------|
| NimlyPRO | Nimly Touch Pro | Onesti Products AS |
| NimlyPRO24 | Nimly Touch Pro 24 | Onesti Products AS |
| easyCodeTouch_v1 | EasyAccess EasyCodeTouch | Onesti Products AS |
| EasyCodeTouch | EasyAccess | Onesti Products AS |
| EasyFingerTouch | EasyAccess (fingeravtrykk) | Onesti Products AS |

Alle bruker samme Connect Module (Zigbee 3.0) og identisk firmware. Manualen er lik — forskjell er kun branding og fysisk design.

### Hardware — Connect Module (ZMNC010)

- **Zigbee manufacturer code:** `0x1234` (4660) — placeholder/test-kode, IKKE registrert hos Zigbee Alliance. Tyder på OEM-modul.
- **Chip:** Ukjent — ingen offentlig teardown. Sannsynligvis TI CC2530 eller lignende basert på:
  - `maximum_buffer_size: 108`
  - `maximum_incoming_transfer_size: 127` (tyder på enklere chip)
  - `maximum_outgoing_transfer_size: 127`
- **Radio:** 2.4 GHz (frequency_band: 8), Zigbee 3.0
- **Strøm:** 3x AA batterier (EndDevice, battery-powered)
- **Modell-ID:** ZMNC010 (selges separat som tilbehør)
- **CE-merket** — ingen FCC ID funnet (europeisk produkt)
- **Produsent hevder:** "open and ready to go for any zigbee system" — men bruker ikke-standard manufacturer code og custom attributter (0x0100, 0x0101)

### Community-referanser

- [Z2M PR #11332 — PIN fix](https://github.com/Koenkk/zigbee-herdsman-converters/pull/11332)
- [Z2M issue #17205 — Not fully supported](https://github.com/Koenkk/zigbee2mqtt/issues/17205)
- [Z2M issue #5884 — Original device support](https://github.com/Koenkk/zigbee2mqtt/issues/5884)
- [ZHA issue #3095 — Device support request](https://github.com/zigpy/zha-device-handlers/issues/3095)
- [HA community — Nimly lock thread (12+ sider)](https://community.home-assistant.io/t/nimly-lock-with-zigbee-module/523634)
- [Blakadder — ZMNC010](https://zigbee.blakadder.com/Nimly_ZMNC010.html)
- [Z2M Nimly docs](https://www.zigbee2mqtt.io/devices/Nimly.html)
- [Silicon Labs — Sleepy End Devices](https://docs.silabs.com/zigbee/9.0.0/zigbee-concepts-network/end-devices)

---

## Integrasjon: onesti_lock (nåværende tilstand)

### Fungerer

- ✅ PIN-kode sett/fjern via UI og services (når låsen er våken)
- ✅ Aktivitetssensor: "Kari låste opp med kode" (via cluster.on_event)
- ✅ Slot→navn mapping, persistert
- ✅ Options flow (norsk + engelsk)
- ✅ 28 tester passerer
- ✅ Event firing for automations (`onesti_lock_activity`)

### Kjente problemer

- ⚠️ set_pin timeouter ofte pga sleepy device (spesielt etter batteribytte)
- ⚠️ Slot 0 (master) matcher alltid først — samme kode på slot 0 og 3 bruker slot 0
- ⚠️ Options flow dropdown viste ikke valg (fikset med string-keys)
- ⚠️ Etter batteribytte: reconfigure feiler, battery ikke oppdatert, set_pin timeout

### Deploy til begge HA-instanser

```bash
# Hjemme
cd ~/dev/nimly-touch-pro-integration
tar czf - custom_components/onesti_lock/ | ssh ha-local "cd /root/config && tar xzf -"
ssh ha-local 'ha core restart'

# Hytta (via Tailscale)
tar czf - custom_components/onesti_lock/ | ssh ha-leirnes-ts "cd /root/config && tar xzf -"
ssh ha-leirnes-ts 'ha core restart'
```

---

## HA Leirnes — Tailscale oppsett

- Tailscale-addon installert med Headscale (`https://headscale.serveren.0v.no`)
- Node: `ha-leirnes` (100.64.0.6)
- Subnet route: `192.168.80.0/24` (godkjent i Headscale, node ID 6)
- SSH via Tailscale: `ssh ha-leirnes-ts` (100.64.0.6)
- SSH via LAN: `ssh ha-leirnes-local` (192.168.80.125) — kun på hytta

---

## TODO

- [ ] Vent på at hjemme-lås stabiliserer seg etter batteribytte, prøv set_pin igjen
- [ ] Test ZHA issue_zigbee_cluster_command-metoden for set_pin
- [ ] Skru av debug-logging på hytte-HA (fyller disk)
- [ ] Bytt masterkode på hytte-lås (factory `123`)
- [ ] Rydd warning-level logging i integrasjonen (bytt til info/debug)
- [ ] Vurder å bidra event-decoding upstream til zha-device-handlers
- [ ] Publiser integrasjonen

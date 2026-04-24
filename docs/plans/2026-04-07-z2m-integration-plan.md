# Plan: Onesti Lock Z2M-integrasjon

**Dato:** 2026-04-07 (opprettet), sist oppdatert 2026-04-24
**Status:** Parkert — venter på MQTT-dumper fra Håkon før evt. implementering

## Bakgrunn

Eksisterende Onesti Lock-integrasjon krever ZHA. Brukere som kjører Zigbee2MQTT får en feilmelding og kan ikke bruke integrasjonen. Z2M har en `onesti.ts` converter som allerede dekoder attrid 0x0100 til lesbare MQTT-felter, men det finnes ingen HA-integrasjon som pakker dette inn i sensorer, automations og UI.

## Hvorfor egen integrasjon

ZHA-versjonen og en Z2M-versjon deler nesten ingen kode:

| Komponent | ZHA (eksisterende) | Z2M (ny) |
|-----------|-------------------|----------|
| Event-mottak | zigpy cluster `on_event` | MQTT subscribe |
| Bruker-ID dekoding | Manuell bitmap-parsing av 0x0100 | Allerede dekodet av converter (`last_unlock_source`, `last_unlock_user`) |
| PIN-kommandoer | `issue_zigbee_cluster_command` | MQTT publish til `zigbee2mqtt/<device>/set` |
| Device discovery | ZHA `gateway_proxy.device_proxies` | MQTT discovery eller manuell IEEE-input |
| Auto-wake | Lock-kommando via ZHA entity | Ikke nødvendig (Z2M håndterer retry) |
| Coordinator | Custom `NimlyCoordinator` med ZHA cluster-tilgang | MQTT-basert coordinator |

Å tvinge begge inn i én integrasjon gir `if zha: ... elif z2m: ...` overalt uten gevinst.

## Hva Z2M allerede eksponerer via MQTT

Fra [Z2M Nimly-side](https://www.zigbee2mqtt.io/devices/Nimly.html):

- `last_unlock_source`: zigbee, keypad, fingerprintsensor, rfid, self, unknown
- `last_unlock_user`: slot-nummer
- `last_lock_source` / `last_lock_user`: samme for låsing
- `last_used_pin_code`: faktisk PIN som ble brukt
- `pin_code`: composite feature (user_id, user_type, enabled, code)
- `lock_state`: not_fully_locked, locked, unlocked
- `battery`, `voltage`
- `auto_relock`, `auto_relock_time`
- `sound_volume`: silent, low, high

## Kjente problemer med Z2M-converteren

- Brukere rapporterer at mange felter returnerer `null` etter opplåsing
- Ukjent om dette er converter-bug eller modellspesifikt
- Må verifiseres med faktisk hardware før implementering

## Arkitekturskisse

```
onesti_lock_z2m/
├── __init__.py          # Setup, MQTT subscription, event parsing
├── coordinator.py       # Slot storage (gjenbrukbar fra ZHA-versjon), MQTT publish for PIN
├── config_flow.py       # Device discovery via MQTT eller manuell input
├── sensor.py            # Slot sensors + activity sensor (gjenbrukbar struktur)
├── services.py          # set_pin, clear_pin via MQTT publish
├── const.py             # MQTT topics, source mapping
├── manifest.json        # dependencies: ["mqtt"]
├── strings.json
└── translations/
```

### Config flow

Alternativ A: Autodiscovery via MQTT — subscribe til `zigbee2mqtt/bridge/devices`, filtrer på Onesti-modeller.

Alternativ B: Brukeren skriver inn MQTT device-topic manuelt (enklere, mer pålitelig).

### Event-mottak

```
Topic: zigbee2mqtt/<friendly_name>
Payload: { "last_unlock_source": "keypad", "last_unlock_user": 3, ... }
```

Subscribe til device-topic, parse JSON, oppdater activity sensor.

### PIN-kommandoer

```
Topic: zigbee2mqtt/<friendly_name>/set
Payload: { "pin_code": { "user": 3, "user_type": "unrestricted", "user_enabled": true, "pin_code": "5478" } }
```

## Hva som kan gjenbrukes fra ZHA-versjonen

- **Sensor-strukturen**: `NimlySlotSensor` og `NimlyActivitySensor` — samme konsept, ny datakilde
- **Slot storage**: `_slots` dict-mønsteret med `_save_slots` / `_load_slots`
- **Strings/translations**: Samme UI-tekster
- **Blueprints**: Kan fungere for begge hvis entity-naming er konsistent
- **Tester**: Teststruktur og event-dekoding (men Z2M-versjonen trenger ikke bitmap-tester)

## Hva som IKKE kan gjenbrukes

- `_get_cluster`, `_send_cluster_command`, `_wake_lock` — alt ZHA-spesifikt
- Config flow — helt annen discovery-mekanisme
- Event listener — MQTT i stedet for cluster events
- `_decode_operation_event` — unødvendig, Z2M gjør dette allerede

## Estimat

Mindre enn ZHA-versjonen fordi Z2M gjør det tunge arbeidet (bitmap-dekoding, device management). Hoveddelen er MQTT-plumbing og config flow.

## Åpne spørsmål

1. **Er `null`-problemet i Z2M reelt?** Håkon har en Onesti-lås på Z2M — be ham om MQTT-dumps av lås/opplåsing-events.
2. **Autodiscovery vs. manuell input?** Autodiscovery er bedre UX men mer komplekst.
3. **Nytt repo eller monorepo?** Separat HACS-repo (`onesti-lock-z2m`) er enklest for brukere.
4. **Prioritet?** Vi anbefaler Matter for nye kjøp. Denne integrasjonen er for eksisterende Z2M-brukere med Onesti-lås. Begrenset målgruppe.
5. **Testressurs:** Håkon har Onesti-lås på Z2M.

## Beslutning

Parkert. Bygges hvis det er tilstrekkelig etterspørsel fra Z2M-brukere. Lenkes til fra ZHA-integrasjonens README som en potensiell fremtidig utvikling.

## Neste steg

1. **Håkon leverer MQTT-dump** fra sin Onesti-lås på Z2M, se [`z2m-mqtt-test-instructions.md`](z2m-mqtt-test-instructions.md)
2. **Analyser dumpen:**
   - Kommer `last_unlock_source`, `last_unlock_user` gjennom med verdier, eller er de `null`?
   - Hvilket format er `last_used_pin_code` i — ASCII eller BCD? (ZHA-integrasjonen støtter begge etter v1.1.0)
   - Hvilke andre felter eksponeres i praksis?
3. **Beslutt implementering** basert på dumpen
4. **Hvis ja: opprett nytt repo** `onesti-lock-z2m` med MQTT-basert coordinator

## Lært fra v1.1.0-arbeidet (ZHA-parity med Z2M)

Vi undersøkte Z2M grundig før vi la til parity-features i ZHA-integrasjonen. Relevant for en evt. Z2M-implementasjon:

- **PIN-set "handshake" er ikke løsbart i software:** Både zigpy (Python) og zigbee-herdsman (TS) sender samme ZCL-kommando og får samme malformerte respons. zigpy kaster `IndexError`, herdsman returnerer stille. Ingen av oss får faktisk bekreftelse. Dette er 100% firmware.
- **PIN-koding varierer mellom firmware:** NimlyPRO-captures viser BCD (`b"\x54\x78"` → "5478"). Z2M PR #11332 viser ASCII (`b"\x35\x34\x37\x38"` → "5478"). Z2M-implementasjonen må (som vår) auto-detektere begge.
- **Z2M-converteren gjør tyngst arbeid:** `onesti.ts` dekoder 0x0100 og 0x0101 allerede. MQTT-implementasjonen trenger bare å konsumere ferdig-dekodede felter.
- **Standard ZCL-capabilities (0x0012, 0x0017, 0x0018):** Z2M leser disse. Hvis de faktisk kommer gjennom på Håkons lås, er det nyttig metadata å eksponere.

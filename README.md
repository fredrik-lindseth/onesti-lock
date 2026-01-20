# Nimly Touch Pro

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/fredrik-lindseth/nimly-touch-pro-integration.svg)](https://github.com/fredrik-lindseth/nimly-touch-pro-integration/releases)

Home Assistant-integrasjon for Nimly Touch Pro smartlås. Gir utvidet funksjonalitet utover standard ZHA-integrasjon.

> **Alpha-versjon** - Integrasjonen er under aktiv utvikling.

## Funksjoner

### Lås-kontroll
- Lås/lås opp via Home Assistant
- Sporing av hvem som låste opp (tastatur, manuelt, Home Assistant)
- Siste bruker med tidsstempel

### Sensorer
- Dørstatus (åpen/lukket)
- Låsstatus
- Batterinivå
- Firmware-versjon

### Innstillinger
- LED-lysstyrke (Av/Lav/Medium/Høy)
- Lydvolum (Av/Lav/Medium/Høy)
- Auto-lås tid (0-3600 sekunder)

## Krav

- Home Assistant 2023.11.0 eller nyere
- ZHA-integrasjon konfigurert
- Nimly Touch Pro låsen paret med ZHA

## Installasjon

### Via HACS (anbefalt)

1. Åpne HACS i Home Assistant
2. Klikk på "Integrations"
3. Klikk på de tre prikkene øverst til høyre → "Custom repositories"
4. Legg til `https://github.com/fredrik-lindseth/nimly-touch-pro-integration`
5. Velg "Integration" som kategori
6. Finn "Nimly Touch Pro" i listen og klikk "Download"
7. Start Home Assistant på nytt

### Manuell installasjon

1. Last ned siste release fra [releases](https://github.com/fredrik-lindseth/nimly-touch-pro-integration/releases)
2. Pakk ut og kopier `custom_components/nimly_pro` til din `config/custom_components/` mappe
3. Start Home Assistant på nytt

## Konfigurasjon

1. Gå til **Settings** → **Devices & Services**
2. Klikk **Add Integration**
3. Søk etter "Nimly Touch Pro"
4. Velg din Nimly Touch Pro lås fra listen

## Sensorer

| Sensor | Beskrivelse |
|--------|-------------|
| `lock.nimly_pro_*` | Hovedlås-entitet |
| `binary_sensor.nimly_pro_*_door` | Dørstatus (åpen/lukket) |
| `sensor.nimly_pro_*_firmware` | Firmware-versjon |
| `sensor.nimly_pro_*_last_user` | Siste bruker |
| `select.nimly_pro_*_led` | LED-innstillinger |
| `select.nimly_pro_*_sound` | Lydinnstillinger |
| `number.nimly_pro_*_auto_relock` | Auto-lås tid |

## Feilsøking

### "ZHA not found"
Sørg for at ZHA-integrasjonen er satt opp og fungerer før du legger til Nimly Touch Pro.

### "No devices found"
- Sjekk at låsen er paret med ZHA
- Verifiser at låsen vises i ZHA-enheter
- Låsen må ha manufacturer "Onesti Products AS" og model "NimlyPRO" eller "NimlyPRO24"

## Lisens

MIT License - Se [LICENSE](LICENSE) for detaljer.

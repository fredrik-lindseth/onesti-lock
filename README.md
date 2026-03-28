# Nimly Touch Pro

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/fredrik-lindseth/nimly-touch-pro-integration.svg)](https://github.com/fredrik-lindseth/nimly-touch-pro-integration/releases)

Home Assistant-integrasjon for PIN-kode management på Nimly Touch Pro smartlåser.

## Hvorfor denne integrasjonen?

ZHA (Zigbee Home Automation) håndterer allerede grunnleggende låskontroll for Nimly:
- Lås/lås opp
- Låsstatus, dørstatus, batteri
- Lydvolum, auto-lås

**Denne integrasjonen legger til det ZHA mangler: PIN-kode management.**

Med denne integrasjonen kan du:
- Opprette og slette PIN-koder programmatisk
- Lage midlertidige koder for gjester
- Automatisere PIN-administrasjon basert på tid eller hendelser

## Installasjon

### Via HACS (anbefalt)

1. Åpne HACS → Integrations
2. Klikk ⋮ → Custom repositories
3. Legg til `https://github.com/fredrik-lindseth/nimly-touch-pro-integration` som Integration
4. Installer "Nimly Touch Pro"
5. Start Home Assistant på nytt

### Manuell installasjon

1. Last ned fra [releases](https://github.com/fredrik-lindseth/nimly-touch-pro-integration/releases)
2. Kopier `custom_components/nimly_pro` til `config/custom_components/`
3. Start Home Assistant på nytt

## Oppsett

1. **Settings** → **Devices & Services** → **Add Integration**
2. Søk etter "Nimly Touch Pro"
3. Velg din lås fra listen

**Krav:** ZHA må være konfigurert og låsen paret før du setter opp denne integrasjonen.

## Services

Alle services finnes under **Developer Tools → Actions** (søk "nimly"):

| Service | Beskrivelse |
|---------|-------------|
| `nimly_pro.set_pin_code` | Opprett eller oppdater PIN-kode |
| `nimly_pro.clear_pin_code` | Slett en PIN-kode |
| `nimly_pro.clear_all_pin_codes` | Slett alle PIN-koder |
| `nimly_pro.get_pin_code` | Hent info om en PIN-kode |
| `nimly_pro.get_user_status` | Sjekk om bruker er aktiv |
| `nimly_pro.set_user_status` | Aktiver/deaktiver bruker |

### Opprette PIN-kode

```yaml
service: nimly_pro.set_pin_code
data:
  ieee: "f4:ce:36:88:61:9c:f4:6f"  # Låsens IEEE-adresse
  user_id: 1                        # Slot 0-255
  pin_code: "1234"                  # PIN-koden
```

### Slette PIN-kode

```yaml
service: nimly_pro.clear_pin_code
data:
  ieee: "f4:ce:36:88:61:9c:f4:6f"
  user_id: 1
```

### Finne IEEE-adressen

1. Gå til **ZHA** → **Devices**
2. Klikk på Nimly-låsen
3. IEEE-adressen vises under "Zigbee info" (format: `xx:xx:xx:xx:xx:xx:xx:xx`)

## Viktig: Låsen må være våken

Nimly er batteridrevet og sover for å spare strøm. For å sende kommandoer:

1. **Vekk låsen** - Trykk på tastaturet
2. **Kjør kommandoen innen 10 sekunder**

Får du `TimeoutError`? Låsen sov. Vekk den og prøv igjen.

## Automatiseringseksempler

### Gjeste-PIN som aktiveres med en bryter

```yaml
automation:
  - alias: "Aktiver gjeste-PIN"
    trigger:
      - platform: state
        entity_id: input_boolean.guest_access
        to: "on"
    action:
      - service: nimly_pro.set_pin_code
        data:
          ieee: "f4:ce:36:88:61:9c:f4:6f"
          user_id: 10
          pin_code: "9999"

  - alias: "Deaktiver gjeste-PIN"
    trigger:
      - platform: state
        entity_id: input_boolean.guest_access
        to: "off"
    action:
      - service: nimly_pro.clear_pin_code
        data:
          ieee: "f4:ce:36:88:61:9c:f4:6f"
          user_id: 10
```

### Daglig roterende PIN

```yaml
automation:
  - alias: "Oppdater daglig PIN"
    trigger:
      - platform: time
        at: "06:00:00"
    action:
      - service: nimly_pro.set_pin_code
        data:
          ieee: "f4:ce:36:88:61:9c:f4:6f"
          user_id: 5
          pin_code: "{{ now().strftime('%m%d') }}"  # MMDD
```

## Feilsøking

| Problem | Løsning |
|---------|---------|
| TimeoutError | Vekk låsen (trykk på tastaturet), prøv igjen innen 10 sek |
| "Door Lock cluster not found" | Sjekk at IEEE-adressen er korrekt |
| "ZHA not found" | Sett opp ZHA-integrasjonen først |
| Låsen vises ikke | Par låsen med ZHA på nytt |

## Teknisk info

Nimly Touch Pro bruker **ZCL Door Lock Cluster (0x0101)**, industristandarden for Zigbee-låser. Denne integrasjonen sender ZCL-kommandoer direkte til clusteret via ZHA/zigpy.

Støttede modeller:
- NimlyPRO
- NimlyPRO24

Produsent: Onesti Products AS

## Lisens

MIT License

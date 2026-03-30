# Slot-nummerering — kjente fakta og usikkerhet

Onesti-låsen har brukerslots for PIN-koder, RFID-brikker og fingeravtrykk. Slot-nummereringen varierer mellom tilgangsmetodene, og vi har ikke verifisert om de ulike nummerseriene refererer til samme fysiske lagringsplass i låsen.

## Hva vi vet

### Zigbee ZCL (DoorLock cluster 0x0101)

Verifisert via rå Zigbee-fangster og ZCL `set_pin_code` (0x0005):

| Slot-område | Rolle | Kilde |
|---|---|---|
| 0 | Master-PIN (0927) | Verifisert: `attrid 0x0100` rapporterer `user_slot=0` ved opplasing med master-kode |
| 1-2 | Reservert (antatt) | Aldri observert i bruk. Nimly/EasyAccess-manualen sier "slots 0-2 reserved for master codes" |
| 3-199 | Brukerslots | Verifisert: slot 3 og 4 observert i `attrid 0x0100` event-rapporter |

**Kommandoer som bruker slot-nummer:**
- `set_pin_code` (0x0005): `user_id`-parameter = ZCL slot-nummer
- `get_pin_code` (0x0006): `user_id`-parameter = ZCL slot-nummer
- `clear_pin_code` (0x0007): `user_id`-parameter = ZCL slot-nummer
- `attrid 0x0100` (operation event): byte 0 = slot-nummer som ble brukt

### BLE ekey-protokoll

Dekompilert fra `easyaccess.ekey.app` v1.5.1 (se `docs/ble-protocol.md`):

| Slot-omrade | Rolle | Kilde |
|---|---|---|
| 0 | Master-PIN | Fra dekompilert kode |
| 800-899 | Vanlige bruker-PINer | Fra dekompilert kode (`PinCodeSet` 0x52, `slotNumber` uint16 LE) |

**Eksempel:** Sette PIN "8832" pa slot 803 via BLE sendes som `23 03 04 38 38 33 32` (slot 803 little-endian + lengde + ASCII).

### Cloud API (iotiliti)

Cloud API-et (`POST /devices/{id}/access`) bruker en abstrakt bruker-modell med `userId`, ikke rå slot-nummer. Gatewayen oversetter mellom cloud-bruker og ZCL slot-nummer internt.

## Hva som er usikkert

### Er BLE slot 800 = Zigbee slot 3?

**Hypotese:** BLE slot 800-899 og Zigbee slot 3-199 refererer til samme fysiske brukerslots i lasen, men med forskjellig offset/nummerering.

**Alternativ hypotese:** De kan vaere separate lagringsomrader i firmware. PIN satt via BLE pa slot 800 og PIN satt via Zigbee pa slot 3 kan vaere uavhengige.

**Status:** Ikke testet. For a verifisere trenger vi tilgang til bade BLE-appen og ZHA samtidig — sett en PIN via BLE pa slot 800, sjekk om den dukker opp som slot 3 i Zigbee operation events.

### Reserverte slots 1-2

Slot 1 og 2 er markert som reservert basert pa Nimly-manualen. Vi har aldri observert dem i bruk, men vet ikke hva de er reservert for. Muligheter:

- Ekstra master-koder (admin-PINer)
- Installator-kode
- Service-kode fra fabrikk
- Ubrukt — bare buffer mellom master (0) og brukere (3+)

### Cloud API slot-mapping

Nar cloud API-et mottar `POST /devices/{id}/access` med en ny PIN, velger gatewayen slot-nummer automatisk. Vi vet ikke:

- Hvilken slot den velger (forste ledige fra 3?)
- Om den koordinerer med BLE slot-nummereringen
- Om en PIN satt via cloud kan overskrive en PIN satt direkte via Zigbee

### Fingeravtrykk og RFID

Fingeravtrykk og RFID-brikker har sannsynligvis egne slot-serier (BLE-protokollen har `FingerprintClear` 0x58 og `RfidCodeClear` 0x55 med `slotNumber`-parameter). Vi har ikke kartlagt nummereringen for disse.

## Gjeldende implementasjon

Integrasjonen (`custom_components/onesti_lock/`) bruker ZCL slot-nummerering:

```python
# const.py
MAX_SLOTS = 200       # ZCL slots 0-199
SLOT_FIRST_USER = 3   # Forste brukerslot
NUM_USER_SLOTS = 10   # Viser slots 3-12 i UI
```

- **Options flow** (PIN-administrasjon): Viser slots 3-12 i dropdown. Bruker kan velge slot og sette/fjerne PIN.
- **Sensorer**: 10 slot-sensorer (slot 3-12), viser navn og PIN-status.
- **Coordinator**: Sender ZCL `set_pin_code` med `user_id=<valgt slot>`.
- **Event-dekoding**: `attrid 0x0100` byte 0 gir slot-nummeret som ble brukt ved opplasing — dette er alltid ZCL-nummeret uavhengig av hvordan PINen ble satt.

### Konsekvenser for brukere

- Slot-numrene i HA UI (3-12) er interne ZCL-nummer. De matcher ikke noe brukeren ser pa selve lasen.
- Hvis brukeren ogsa bruker Nimly Connect-appen (cloud), kan PINer satt via appen havne pa andre slots enn de som er synlige i HA (3-12).
- PINer satt via BLE-appen bruker slot 800+. Disse er usynlige i HA med mindre operation events rapporterer dem via `attrid 0x0100`.

## Bekreftet

- **PIN-koder overlever re-paring.** PIN 2510 satt via ZHA (slot 4) fungerte fortsatt etter at låsen ble fjernet fra ZHA og paret med Connect Bridge (hub). PIN-lagring er lokal på låsen og uavhengig av hvilken Zigbee-koordinator som er tilkoblet. (Testet 2026-03-30.)

## Verifiseringsplan

For a lase usikkerheten trengs disse testene:

1. **BLE/Zigbee-krysstest:** Sett PIN via BLE pa slot 800. Las opp med PINen. Sjekk `attrid 0x0100` — rapporterer den slot 3 eller slot 800?
2. **Cloud/Zigbee-krysstest:** Sett PIN via Nimly Connect-appen. Las opp. Sjekk hvilken slot `attrid 0x0100` rapporterer.
3. **Slot 1-2 test:** Forsok a sette PIN pa slot 1 og 2 via ZCL `set_pin_code`. Observerer lasen dem, eller avviser den kommandoen?
4. **Kapasitetstest:** Sett PINer pa slot 3 og slot 800 via ZCL. Er begge gyldige, eller avviser lasen slot 800?

Disse testene krever fysisk tilgang til lasen og er planlagt til neste gang Connect Bridge er tilgjengelig.

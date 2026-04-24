# Test: Verifisere Z2M MQTT-data fra Onesti-lås

## Hva vi trenger

MQTT-dumps av lås/opplåsing-events fra din Onesti-lås på Zigbee2MQTT. Vi vil se om `last_unlock_source`, `last_unlock_user` etc. faktisk har verdier eller om de er `null` (som noen Z2M-brukere rapporterer).

## Forberedelse

1. Finn MQTT-topic for låsen din. Det er typisk `zigbee2mqtt/<friendly_name>`. Du finner friendly_name i Z2M-dashboardet under Devices.

2. Start en MQTT-lytter i terminalen. Hvis du har `mosquitto_sub` installert:

```bash
mosquitto_sub -h localhost -t "zigbee2mqtt/<friendly_name>" -v | tee onesti-mqtt-dump.txt
```

Hvis du bruker en annen MQTT-broker eller trenger brukernavn/passord:

```bash
mosquitto_sub -h <broker-ip> -u <brukernavn> -P <passord> -t "zigbee2mqtt/<friendly_name>" -v | tee onesti-mqtt-dump.txt
```

Alternativt kan du bruke MQTT Explorer (GUI) — koble til brokeren og naviger til `zigbee2mqtt/<friendly_name>`. Kopier payloaden etter hver hendelse.

3. La lytteren stå åpen mens du gjør testene under.

## Testsekvens

Gjør disse i rekkefølge, med noen sekunder mellom hver. Etter hver handling, vent til du ser en MQTT-melding i terminalen.

1. **Lås opp med PIN-kode på keypaden** — tast inn en brukerkode
2. **Lås med keypaden** — trykk lås-knappen
3. **Lås opp med fingeravtrykk** — bruk en registrert finger
4. **Lås med keypaden**
5. **Lås opp med RFID-brikke** — hold en registrert brikke mot leseren
6. **Lås med keypaden**
7. **Lås opp via Z2M** — i Z2M-dashboardet, klikk "Unlock" på låsen
8. **Lås via Z2M**
9. **Vent på auto-lock** — hvis du har auto-relock aktivert, la døren stå og vent til den låser seg selv

## Hva vi ser etter i dataen

For hver hendelse vil Z2M publisere en JSON-payload. Vi trenger å vite om disse feltene har verdier:

```json
{
  "last_unlock_source": "keypad",
  "last_unlock_user": 3,
  "last_lock_source": "keypad",
  "last_lock_user": 3,
  "last_used_pin_code": "5478",
  "lock_state": "unlocked",
  "battery": 95
}
```

Marker gjerne i dumpen hvilken handling du gjorde (f.eks. "--- PIN-kode her ---") så vi kan matche event til handling.

## Etter testene

1. Stopp lytteren (Ctrl+C)
2. Filen `onesti-mqtt-dump.txt` inneholder alt
3. **Fjern PIN-koder fra dumpen** før du sender den — `last_used_pin_code` inneholder faktiske koder. Erstatt med `"REDACTED"` eller slett feltet.
4. Send filen til Fredrik

## Bonus: Sjekk Z2M-versjonen din

```bash
mosquitto_sub -h localhost -t "zigbee2mqtt/bridge/info" -C 1 | python3 -m json.tool | grep version
```

Eller sjekk i Z2M-dashboardet under Settings. Versjonen kan påvirke om converteren fungerer riktig.

# Feilsøking

Praktisk guide for å diagnostisere og løse vanlige problemer med Onesti Lock-integrasjonen.

## 1. Zigbee-tilkobling

### Låsen svarer ikke (sleepy device)

Onesti/Nimly-låser er batteriopererte Zigbee EndDevices. Radioen sover mesteparten av tiden for å spare batteri. Meldinger som venter hos parent-routeren kastes etter **7,68 sekunder**.

**Hva vekker Zigbee-radioen:**

- Taste en komplett PIN-kode + `#` på keypadet
- Fysisk låsing/opplåsing (vriding av knotten)
- Lås/lås opp-kommando fra HA (ZHA bruker forlenget timeout)

**Hva vekker IKKE radioen:**

- Berøring av keypadet alene (vekker bakgrunnsbelysningen, men ikke Zigbee-radioen)

### Hvordan auto-wake fungerer

Integrasjonen har en innebygd vekke-mekanisme i `coordinator.py` (`_send_cluster_command`):

1. **Forsøk 1:** Sender ZCL-kommandoen via `zha.issue_zigbee_cluster_command`
2. **Ved timeout:** Kaller `_wake_lock()` — sender `lock.lock` service call til ZHA-lås-entiteten
3. **Venter 1 sekund** for at radioen skal stabilisere seg
4. **Forsøk 2:** Prøver den opprinnelige kommandoen på nytt

`_wake_lock()` finner ZHA-lås-entiteten ved å lete i entity registry etter en entitet der `platform == "zha"`, `unique_id` inneholder enhetens IEEE-adresse, og `unique_id` ender med `"257"` (DoorLock cluster endpoint).

### Signalproblemer

Metalldør og metallkapsling = Faraday-bur. Zigbee-signalet dempes kraftig.

**Tiltak:**

- Plasser en Zigbee-router (f.eks. en smart plugg) innen 2-3 meter fra låsen
- Unngå at låsen må kommunisere gjennom flere vegger til koordinatoren
- Sjekk LQI (link quality) i ZHA: **Innstillinger → Enheter → [låsen] → Zigbee-info**

### Etter batteribytte

Når batteriene byttes, re-joiner låsen Zigbee-nettverket, men bindinger kan resette:

- Attribute reporting (0x0100-events) slutter å komme
- `set_pin_code` timer konsekvent ut (timer eller dager)
- Lås/lås opp fungerer fortsatt (enklere kommando med ZHAs forlengede timeout)
- `Reconfigure` i ZHA feiler ofte (binding + reporting-oppsett timer ut)

**Løsning:**

1. Prøv **Reconfigure** i ZHA (se neste avsnitt)
2. Hvis det ikke hjelper: vent timer/dager for at bindinger re-etableres av seg selv
3. Siste utvei: fjern og par låsen på nytt i ZHA

### Reconfigure i ZHA

Reconfigure (Innstillinger → Enheter → [låsen] → "Reconfigure device") re-oppretter bindinger og reporting-konfigurasjon. For sleepy devices feiler dette ofte fordi enheten sovner under prosessen.

**Tips for å lykkes:**

1. Gå til Reconfigure-dialogen i ZHA
2. Tast en PIN + `#` på keypadet (vekker radioen)
3. Klikk "Reconfigure" innen 2-3 sekunder
4. Hvis det feiler: prøv igjen, radioen er våken lenger etter en opplåsing

## 2. PIN-kode-feil

### "Kunne ikke nå låsen" i Options flow

Denne feilmeldingen betyr at begge forsøkene i `_send_cluster_command` feilet:

1. Forsøk 1 timet ut (låsen sov)
2. Auto-wake sendte `lock.lock` for å vekke radioen
3. Forsøk 2 timet også ut

**Feilsøking:**

- Trykk en PIN + `#` på keypadet for å vekke låsen manuelt
- Prøv igjen innen 5 sekunder (mens radioen er våken)
- Sjekk at ZHA-lås-entiteten fungerer (lås/lås opp via Lovelace). Hvis den heller ikke svarer, er problemet Zigbee-tilkobling, ikke integrasjonen.

### IndexError-quirken (Nimly response parsing)

PIN-kommandoer (`set_pin_code`, `clear_pin_code`) returnerer et malformatert ZCL-svar fra låsen som krasjer zigpy-parseren med `IndexError: tuple index out of range`. Kommandoen nådde låsen og ble utført — feilen er kun i responsparsing.

Integrasjonen fanger denne feilen og behandler den som suksess:

```python
except IndexError:
    # Nimly quirk: command was sent and received, but response
    # format is unexpected causing "tuple index out of range"
    # in zigpy response parsing. Command still reached the lock.
    return True
```

**Viktig:** Det finnes ingen programmatisk bekreftelse på at PIN-en faktisk ble satt. Du **må** teste koden på keypadet for å verifisere.

### Verifisering av PIN

Etter å ha satt en PIN:

1. Gå til låsen fysisk
2. Tast den nye koden + `#`
3. Sjekk at låsen åpner
4. Sjekk activity-sensoren i HA — den bør vise riktig bruker og slot

## 3. Aktivitetssensor oppdaterer ikke

### attribute_report (attrid 0x0100) mottas ikke

Aktivitetssensoren er avhengig av at låsen sender attribute reports med attrid `0x0100` (Onesti custom operation event). Hvis sensoren aldri oppdaterer:

**Sjekk at event-listeneren er registrert.** I loggen ved oppstart skal du se:

```
Event listener registered on DoorLock (events: ['attribute_report'])
```

Hvis du ser `Could not find DoorLock cluster for event listener`, har integrasjonen ikke funnet clusteret. Prøv å laste inn integrasjonen på nytt (Innstillinger → Integrasjoner → Onesti Lock → Last inn på nytt).

**Sjekk at attribute reports faktisk kommer.** Skru på debug-logging (se avsnitt 4) og utfør en opplåsing. Du bør se:

```
Lock event: unlock by Ola via keypad (raw: 0x02020003)
```

Hvis ingenting logges ved opplåsing: låsen sender ikke reports. Se "Etter batteribytte" i avsnitt 1.

### Auto-lock overskriver brukerevents

Eldre versjoner av integrasjonen lot auto-lock-events overskrive meningsfulle events. For eksempel: "Kari låste opp med kode" ble umiddelbart erstattet av "Auto-lås" 5 sekunder senere.

Dette er fikset — `source != "auto"` filtrerer auto-lock fra aktivitetssensoren:

```python
if decoded["source"] != "auto":
    coordinator.update_activity(...)
```

HA-eventet `onesti_lock_activity` fyres fortsatt for alle events inkludert auto-lock, slik at automasjoner kan bruke det.

### Etter batteribytte

Attribute reports kan stoppe helt etter batteribytte fordi bindinger resettes. Se avsnitt 1 ("Etter batteribytte") for løsninger.

## 4. Debug-logging

### Integrasjonens egen logging

Legg til i `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.onesti_lock: debug
```

Start HA på nytt. Du vil se:

- Event listener-registrering ved oppstart
- Alle innkommende operation events (attrid 0x0100) med rå-verdier
- Auto-wake-forsøk og resultater
- Nimly response quirk (IndexError) når de skjer
- Cluster-lookup-feil

### Zigpy/ZHA debug-logging for rå Zigbee-trafikk

For å se alle rå Zigbee-frames (nyttig når du mistenker at reports ikke sendes):

```yaml
logger:
  default: warning
  logs:
    custom_components.onesti_lock: debug
    zigpy.zcl: debug
    homeassistant.components.zha: debug
```

**Advarsel:** `zigpy.zcl: debug` genererer _mye_ logg. Bruk det kun for feilsøking, ikke permanent.

### Hva du ser etter i loggen

**Vellykket operation event:**

```
Lock event: unlock by Kari via keypad (raw: 0x02020003)
```

Rå-verdien dekodes slik (little-endian bitmap32):

- `0x02020003` → bytes `[03, 00, 02, 02]` → slot 3, action unlock, source keypad

**Auto-wake sekvens:**

```
Timeout on attempt 1 for command 0x0005 — waking lock and retrying
Waking lock via lock.onesti_lock_nimly_pro_...
```

**Mislykket kommando:**

```
Timeout sending command 0x0005 to f4:ce:36:... after wake+retry — lock may be unreachable
```

**Nimly response quirk:**

```
Nimly response quirk (IndexError) for command 0x0005 — command was sent successfully
```

**Event listener ikke registrert:**

```
Could not find DoorLock cluster for event listener
```

eller:

```
ZHA not found
ZHA gateway_proxy not found
```

**Rå attribute report fra zigpy (med `zigpy.zcl: debug`):**

```
[0x...] DoorLock: Received report for attr 0x0100: <bitmap32 value>
```

Hvis du ser reports for `0x0000` (lock state) men ikke `0x0100` (operation event), har låsen mistet sin reporting-konfigurasjon — prøv Reconfigure.

## 5. Vanlige ZHA-problemer

### Enheten vises som "utilgjengelig"

- **Batteri:** Sjekk batterinivå. Når batteriet er lavt, rapporterer låsen sjeldnere og kommandoer timer ut oftere.
- **Signal:** Låsen er for langt fra nærmeste Zigbee-router. Plasser en router nærmere.
- **Etter batteribytte:** Låsen kan ha havnet i en tilstand der den har re-joinet men bindinger er tapt. Se avsnitt 1.

### Reconfigure feiler gjentatte ganger

Låsen sovner for raskt til at Reconfigure rekker å fullføre binding-oppsettet.

**Fremgangsmåte:**

1. Tast PIN + `#` for å vekke låsen
2. Start Reconfigure umiddelbart (innen 2-3 sekunder)
3. Gjenta om nødvendig — låsen er våken lenger etter en opplåsing enn ved bare å røre keypadet
4. Hvis det aldri lykkes etter flere forsøk: fjern enheten fra ZHA og par på nytt

### Tips for stabil drift

- **Zigbee-router nær låsen.** En smart plugg med Zigbee-router-funksjon 1-3 meter fra døren gjør enorm forskjell for sleepy devices.
- **Ikke flytt koordinatoren.** Zigbee-nettverket bruker tid på å re-rute etter topologiendringer.
- **Hold firmware oppdatert.** ZHA støtter OTA for noen enheter, men Onesti/Nimly-låser har ikke OTA via Zigbee — firmware oppdateres kun via BLE-appen.
- **Overvåk batterinivå.** Opprett en automasjon som varsler ved lavt batteri, slik at du unngår problemene som oppstår ved batteribytte.

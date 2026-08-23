# Vurdering: Zigbee2MQTT-støtte i onesti_lock

Dato: 2026-08-23. Basert på kodelesing av `custom_components/onesti_lock/`, den parkerte planen
`docs/plans/2026-04-07-z2m-integration-plan.md`, og dagens `onesti.ts` på master i
zigbee-herdsman-converters (hentet 2026-08-23).

## Anbefaling: Nei, ikke bygg dobbel transport nå. Bidra oppstrøms i stedet.

Det er teknisk mulig å legge Z2M-transport bak samme coordinator, og arkitekturen under viser hvordan.
Men tre ting velter regnestykket:

1. **Z2M-veien kan ikke verifiseres av noen i prosjektet.** Fredrik kjører ZHA. Håkons MQTT-dump,
   som den gamle planen har ventet på siden april, kom aldri. Repoet sin egen historikk
   (`_attr_name`-saken i AGENTS.md) viser at ting som ser riktige ut i stubs ryker i ekte HA.
   En hel transport som aldri kan røyk-testes av vedlikeholder er verre enn en enkeltbug.
2. **PIN-administrasjon, selve hovedgevinsten, blir fire-and-forget over MQTT.** Z2M har ingen
   respons-topic for `/set` mot enheter, så integrasjonen kan ikke skille suksess fra timeout.
   Options flow sitt løfte i dag (spinner, så «ok» eller «lock_unreachable») kan ikke holdes ærlig.
   Og siden timeout ikke kan observeres, kan auto-wake ikke trigges ved behov: enten må døren
   fysisk låses før hver PIN-operasjon, eller så feiler operasjoner stille på sovende lås.
3. **Fundamentet oppstrøms har kjente hull.** Converteren har en ren bug (dead code, se under),
   mangler 0x05-kilden, og publiserer aldri råverdien av 0x0100. Å bygge på det før det er fikset
   oppstrøms er å bygge på sand.

Det som faktisk hjelper Z2M-brukere nå, til en brøkdel av kostnaden: en liten PR til
zigbee-herdsman-converters som fikser buggen og legger til 0x05, samme spor som prosjektet
alt kjører mot zha-device-handlers (PR 4881). Detaljer i spørsmål 5.

**Triggere for å ta saken opp igjen:** reell etterspørsel (flere issues fra Z2M-brukere), en
forpliktet testperson med Onesti-lås på Z2M, og at converter-fiksene er landet oppstrøms.

---

## 1. Er det teknisk mulig?

Kort svar: ja for hendelsesveien, med målbare tap. Halvveis for PIN-veien. Merket **[verifisert]**
når det er lest i kode/docs, **[resonnert]** når det er slutning.

### Binding 1: `manifest.json` `dependencies: ["zha"]` og `zha_not_found`-abort

Ekvivalent finnes. `dependencies` byttes til `after_dependencies: ["zha", "mqtt"]`, som bare
styrer rekkefølge når integrasjonene finnes, uten å kreve dem **[verifisert, HA-dev-docs]**.
Config flow sjekker i runtime hvilke som er satt opp (`hass.config.components`). Kostnad: en ny
abort-grunn («fant verken ZHA eller MQTT») i `strings.json` pluss fire oversettelser.

### Binding 2: Discovery via `hass.data[ZHA_DOMAIN].gateway_proxy.device_proxies`

Ekvivalent finnes. `zigbee2mqtt/bridge/devices` er retained og inneholder `ieee_address`,
`model_id`, `friendly_name` per enhet **[verifisert, Z2M-docs]**. Config flow kan abonnere,
vente kort på retained-meldingen, og filtrere på `SUPPORTED_MODELS` mot `model_id`.
Gotcha: base-topic er konfigurerbar (default `zigbee2mqtt`), så abonnementet bør bruke
wildcard `+/bridge/devices` og huske base-topicen per entry **[resonnert]**.

### Binding 3: Event-mottak, `cluster.on_event("attribute_report")` for attrid 0x0100

Dette er den svakeste ekvivalenten, med fire konkrete tap. Alt fra dagens `onesti.ts` på master:

- **Råverdien finnes ikke over MQTT.** Converteren publiserer kun tolkede felt
  (`last_lock_user`, `last_lock_source`, `last_unlock_user`, `last_unlock_source`,
  `last_used_pin_code`) **[verifisert i kildekoden]**. `_decode_operation_event` sin
  bitmap-dekoding erstattes av en mapping fra converterens felt.
- **Bug i converteren:** `last_action_source` og `last_action_user` skrives til en `result`-dict,
  men funksjonen returnerer `attributes`. De to feltene når aldri MQTT **[verifisert]**.
  Er action-byten noe annet enn 0x01/0x02 publiseres ingenting i det hele tatt.
- **Kildemapping er tapsbelagt:** converteren mapper `00→zigbee, 02→keypad, 03→fingerprintsensor,
  04→rfid, 0a→self`, uten 0x05. NimlyCodePRO sitt «unattributed» blir «unknown»
  **[verifisert]**. Suppresjonslogikken i `__init__.py` (auto-lås skal ikke overskrive «Kari
  låste opp med kode») kan tilnærmes med `source in ("self", "unknown") og lock og slot 0`,
  men mister presisjon **[resonnert]**.
- **Attribusjonsproblemet:** Z2M publiserer full cached state på hver melding fra enheten
  (`cache_state: true` er default, og payloaden inneholder alle attributter, ikke bare endrede)
  **[verifisert, Z2M-docs]**. En batterirapport bærer altså med seg uendrede `last_*`-felt.
  Integrasjonen må diffe mot forrige payload, og en gjentatt identisk hendelse (samme bruker,
  samme handling, uten mellomliggende felt-endring) kan ikke skilles fra en ride-along.
  `lock_state` i diff-tuppelen fanger de fleste reelle sekvenser, men garantien «ett HA-event
  per fysisk hendelse» som ZHA-veien gir, kan ikke loves **[resonnert]**.

Svar på delspørsmålene: nei, råverdien er utilgjengelig; hendelser kommer som state-publisering
per mottatt melding, ikke som dedikerte events; endring må detekteres ved diffing.

### Binding 4: PIN-operasjoner via `zha.issue_zigbee_cluster_command`

Skriving finnes: begge definisjonene har `tz.pincode_lock` i `toZigbee` **[verifisert]**, så
`mqtt.async_publish` til `<base>/<friendly>/set` med
`{"pin_code": {"user": N, "pin_code": "1234", ...}}` sender ZCL 0x0005, og null-kode sletter
**[resonnert ut fra tz-konvertereren, ikke testet]**.

Det som mangler er tilbakemeldingen:
- Ingen respons-topic for device-`/set`. Feil havner som tekst i `zigbee2mqtt/bridge/logging`
  («Publish 'set' ... failed») **[verifisert via Z2M-issues/docs]**, men loggformat og loggnivå
  er ikke kontrakt og har endret seg mellom versjoner. Å parse det er skjørt.
- Nimly-quirken (malformert respons) svelges stille i herdsman, notert i den gamle planen alt,
  så «suksess» betyr uansett bare «sendt». Men ZHA-veien skiller i det minste timeout
  (ureachable) fra sendt. Det skillet forsvinner.

### Binding 5: Auto-wake via `lock.lock` på ZHA-entiteten

Mekanisk mulig: publiser `{"state": "LOCK"}` til `/set`, samme fysiske aktuering **[resonnert]**.
Men dagens design vekker bare ved timeout, og timeout kan ikke observeres over MQTT (binding 4).
Alternativene er å alltid låse døren fysisk før hver PIN-operasjon, eller å droppe wake og la
operasjoner mot sovende lås feile stille. Begge er dårligere enn dagens oppførsel. Den gamle
planens påstand om at «Z2M håndterer retry» er ikke belagt: `onesti.ts` har ingen sendWhen- eller
retry-logikk **[verifisert]**, og herdsman sine retries lever innenfor samme 7,68-sekunders
foreldre-vindu som zigpy **[resonnert]**.

I tillegg: `read_lock_capabilities` (0x0012/0x17/0x18) har ingen Z2M-ekvivalent for
Nimly-modellene. Bare easyCodeTouch-definisjonen prøver å lese dem i configure, og feltene er
STATE, ikke gettable over `/get` **[verifisert]**. `pin_rules.max_user_slot` faller da tilbake
til 999, som den er designet for.

## 2. Hva ville arkitekturen blitt?

Ett transportlag bak samme coordinator, ikke to integrasjoner. Den gamle planens konklusjon om
at «nesten ingen kode deles» stemmer ikke lenger: slot-lagring, aktivitetssensor, suppresjon,
services, options flow, localize og oversettelser er i dag mesteparten av koden og er
transportnøytrale. Snittet:

```
custom_components/onesti_lock/
  transport/
    __init__.py   # LockTransport-protokoll + normalisert LockEvent
    zha.py        # dagens _get_cluster, _send_cluster_command, _wake_lock,
                  # cluster.on_event-lytteren og bitmap-dekodingen flytter hit
    z2m.py        # mqtt.async_subscribe på device-topic, diffing, feltmapping,
                  # async_publish for pin_code/state
```

Grensesnitt (protokoll, ikke arv):
- `async subscribe_events(cb: Callable[[LockEvent], None]) -> unsub`
  der `LockEvent = {user_slot: int|None, action: str, source: str}` med dagens
  `SOURCE_*`/`ACTION_*`-vokabular. Dekoding flytter inn i transporten: ZHA dekoder bitmap,
  Z2M mapper `last_*`-felt og oversetter `fingerprintsensor→fingerprint`, `self→auto`.
- `async set_pin(slot, code) -> bool`, `async clear_slot(slot) -> bool`
- `async read_capabilities() -> dict`

`NimlyCoordinator` beholder slot-lagring, listeners og aktivitet, og delegerer resten.
`__init__.py` sin suppresjonslogikk og `onesti_lock_activity`-firing blir felles og opererer på
`LockEvent`. `sensor.py`, `services.py`, `localize.py` urørt. Config entry får et
`transport`-felt i data; `async_migrate_entry` (VERSION 2 → 3) defaulter eksisterende entries
til `"zha"`.

Ærlighetskrav i grensesnittet: `set_pin` på Z2M kan bare bety «publisert», ikke «levert».
Da må enten returtypen utvides (sent/confirmed/failed) og UI-tekstene skille, eller Z2M-veien
må skilte i options flow at bekreftelse ikke finnes. Det er en produktbeslutning, ikke bare
plumbing.

## 3. Oppdaging uten brukervalg

Config flow (`async_step_user`):
1. Samle kandidater fra begge verdener: ZHA-løkken som i dag hvis `zha` er satt opp, pluss
   retained `+/bridge/devices` med kort timeout (3-5 s) hvis `mqtt` er satt opp
   (`mqtt.async_wait_for_mqtt_client` finnes for å vente på klienten **[HA-docs, ikke
   verifisert lokalt]**).
2. Dedupliser på IEEE. En lås kan bare være paret mot ett nettverk om gangen, så reell kollisjon
   krever to koordinatorer og to lås-eksemplarer; vis begge med kilde i etiketten om det skjer.
3. Én liste, samme skjema som i dag. Transporten lagres i entry.data, brukeren ser den aldri.
4. Verken zha eller mqtt satt opp: abort med ny felles grunn. mqtt satt opp men Z2M ikke
   kjørende: bridge/devices-timeouten slår til, kandidatlisten fra den siden blir tom, og
   `no_devices_found` gjelder som før.

`manifest.json`: `dependencies: []`, `after_dependencies: ["zha", "mqtt"]`. Konsekvens av
after_dependencies: ingen garanti for at noen av dem finnes, all tilgang må runtime-sjekkes,
også i `coordinator`/transport ved oppstart etter HA-restart der MQTT-brokeren er treg.

## 4. Eierkostnad

- **To feilmoduser:** ZHA-veien feiler høylytt (timeout, IndexError-quirk), Z2M-veien feiler
  stille (publish uten ack) eller via loggparsing. Feilsøkingsdocs, README-avgrensninger og
  options flow-tekster må dobles.
- **Oppstrøms drift:** ZHA-veien er sårbar for zigpy/ZHA-refaktorering (kjent, håndtert).
  Z2M-veien blir i tillegg sårbar for converter-endringer (feltnavn er ikke API), Z2M sine
  topic-/loggformat-endringer, og brukerens Z2M-versjon, som integrasjonen ikke kan se.
- **Test:** transport-splitten er faktisk en testgevinst på papiret: `z2m.py` sin diffing og
  feltmapping er ren logikk som kjører under dagens stub-harness (`test_coordinator_behavior.py`
  -mønsteret, `scripts/ci_sim.py`). MQTT-laget stubbes som ZHA stubbes i dag. Men det stubben
  simulerer er min modell av Z2M, ikke Z2M. Uten en ekte instans og en ekte lås på den finnes
  ingen ende-til-ende-verifisering, og `ssh ha-local`-ruten hjelper ikke: Fredriks instans
  kjører ZHA. Enhver brukerrapportert Z2M-bug må feilsøkes i blinde via dumps fra fremmede.
- **HACS-omdømme:** å skipe en «det bare virker»-transport som vedlikeholder aldri har sett
  virke, er risikoen som veier tyngst.

## 5. Er det verdt det?

Hva Z2M-brukere ville fått som de ikke har:
- Navngitte slots og aktivitetssensoren («Kari låste opp med kode»), det reelle salgspunktet.
- `onesti_lock_activity`-eventet med navn, for blueprints og automasjoner.
- PIN-UI i options flow, men degradert (ingen bekreftelse, ingen wake-ved-timeout).

Hva de har fra før via converteren og MQTT discovery: lock-entitet, batteri, slot-nummer og
kilde som sensorer, PIN-skriving via Z2M-frontend. Og én ting integrasjonen ikke kan verne dem
mot på Z2M: converteren publiserer `last_used_pin_code`, selve koden i klartekst, rett inn i
HA-state via discovery **[verifisert]**. Det undergraver prosjektets eget 0x0101-standpunkt,
og en HA-integrasjon oppå kan ikke fjerne det.

Netto: gevinsten er navngiving og pen presentasjon. Kostnaden er en uverifiserbar transport med
ærlighetsproblemer i PIN-veien. Det er ikke verdt det nå.

**Oppstrøms-sporet, konkret:** en PR til zigbee-herdsman-converters `src/devices/onesti.ts` som
1. fikser at `last_action_source`/`last_action_user` legges i `result` som aldri returneres
   (flytt til `attributes`, eller fjern dem og dokumenter), en ren bug som er lett å begrunne,
2. legger `"05": "unattributed"` i kildemappingen, belagt med capture-referansene i
   `docs/zigbee-protocol/zigbee-captures.md`,
3. eventuelt løfter capabilities-lesingen (18/23/24) fra easyCodeTouch-configure til
   Nimly-configure også.

Det gir Z2M-brukere bedre data uansett hva de kjører oppå, koster en kveld pluss review, og
trenger i verste fall én frivillig tester i PR-tråden i stedet for en permanent testforpliktelse
i dette repoet. Skulle dobbel transport bli aktuelt senere, står den PR-en uansett som
forutsetning nummer én.

## Kilder

- `onesti.ts` på master, rå kildekode hentet 2026-08-23:
  https://raw.githubusercontent.com/Koenkk/zigbee-herdsman-converters/master/src/devices/onesti.ts
- Z2M MQTT-topics: https://www.zigbee2mqtt.io/guide/usage/mqtt_topics_and_messages.html
  (bridge/devices retained, availability, bridge/response gjelder bare bridge-requests)
- Z2M devices-groups-docs (cache_state default true, payload med alle attributter)
- Repo: `custom_components/onesti_lock/{__init__,coordinator,config_flow,const,pin_rules}.py`,
  `docs/plans/2026-04-07-z2m-integration-plan.md`, `docs/technical.md`,
  `docs/zigbee-protocol/zigbee-captures.md`

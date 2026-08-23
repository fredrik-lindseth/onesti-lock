# Funnrapport: onesti_lock — bred gjennomgang

Gjennomgått: HEAD-kopi i scratchpad (858 tester grønne). Kildekode, tester, docs,
blueprints, workflows og git-historikk lest. Ekskludert per oppdrag: 16-bit
slotdekoding og fjerning av last_pin_code/_decode_pin_code/0x0101-lytteren.

Alvorlighet: KRITISK > HØY > MEDIUM > LAV.
Status: [verifisert] = bekreftet ved kjøring/simulering, [kode-lest] = bekreftet
ved lesing av koden, [resonnert] = avhenger av HA/zigpy-oppførsel jeg ikke kunne
kjøre her.

---

## P1 — Rammer brukere direkte

### 1. Slot-endringer persisteres ikke etter første lagring (aliasing i _save_slots)
**Alvorlighet: KRITISK — [verifisert ved simulering]**
`coordinator.py:47-51` (`_save_slots`) legger den *levende* `self._slots`-dicten
inn i `entry.options`. Etter første lagring peker `entry.options["slots"]` og
`self._slots` på samme objekt. Neste `set_pin`/`set_slot_name`/`clear_pin`
muterer dicten in-place, så når `_save_slots` kaller
`hass.config_entries.async_update_entry`, ser HA `entry.options == options`,
returnerer False og **planlegger ingen skriving til .storage** (og fyrer ingen
update-listeners). Simulert mot HA-semantikken: save nr. 2 blir no-op.
Konsekvens: alle PIN-navn/has_pin-endringer etter den første går tapt ved
omstart, med mindre en urelatert config-entry-endring tilfeldigvis flusher
storen først (HA serialiserer da hele minnetilstanden, som skjuler feilen
sporadisk — «noen ganger overlever det, noen ganger ikke» er klassisk symptom).
**Anbefaling:** dypkopier ved lagring:
`options={**self.entry.options, "slots": {k: dict(v) for k, v in self._slots.items()}}`,
og/eller re-les med kopi i `_load_slots` (den kopierer allerede — behold).
Legg til en atferdstest med en falsk `async_update_entry` som replikerer
likhets-sjekken.

### 2. clear_slot nullstiller lokal tilstand selv når låsen er uoppnåelig
**Alvorlighet: HØY (sikkerhet) — [kode-lest]**
`coordinator.py:299-309`: «Reset slot even if command failed». Options-flowens
«Slett PIN» bruker nettopp `clear_slot` (`config_flow.py:130-135`). Ved timeout
etter wake+retry vises riktignok `lock_unreachable`-feil i UI
(`config_flow.py:282-304`), men slot-dataene er allerede nullstilt: sensoren
viser «Ledig», sloten forsvinner fra «aktive slots»-listen, og brukeren har
ingen påminnelse om å prøve igjen — mens **låsen fortsatt godtar den gamle
PIN-koden**. En bruker som «fjerner» koden til en tidligere leietaker tror døren
er sikret. `services.py` sin `clear_pin` er derimot konsistent (ruller ikke
tilbake, kaster feil).
**Anbefaling:** ikke nullstill ved feil; sett i stedet en `pending_clear`-markør
eller behold has_pin=True og la UI vise at slettingen feilet. Minimum: behold
navnet så sloten forblir synlig.

### 3. Auto-wake låser døren fysisk som bieffekt
**Alvorlighet: HØY — [kode-lest]**
`coordinator.py:184-205`: `_wake_lock` «vekker» låsen ved å kalle
`lock.lock` på ZHA-entiteten. Hver gang noen setter/sletter en PIN mens låsen
sover (som er normaltilstanden for en batteridrevet EndDevice), blir døren
fysisk låst uten at brukeren har bedt om det. Skjer døren står åpen, kjøres
reilen ut mot karmen. docs/technical.md:59-68 beskriver dette som design, men
bieffekten er reell og udokumentert i README/UI.
**Anbefaling:** vekk med en ufarlig operasjon i stedet — f.eks. les
lock_state-attributtet via ZHA (`zha.issue_zigbee_cluster_command` read, eller
`homeassistant.update_entity` på lock-entiteten som også bruker utvidet
timeout). Hvis lock-kommando må beholdes: les nåværende tilstand først og
re-utfør bare hvis låst, eller dokumenter tydelig.

### 4. Testsuiten gir falsk trygghet — kjernelogikken har null reell dekning
**Alvorlighet: HØY (for videre utvikling) — [verifisert]**
- `tests/test_event_decoding.py:26-52` og `tests/test_event_properties.py:14-42`
  tester en **kopi** av dekodelogikken som er skrevet inn i testfilen, ikke
  `_decode_operation_event` i `__init__.py`. Endres/ødelegges produksjonskoden,
  er ~640 av de 858 testene fortsatt grønne (200+256+100 parametriseringer m.m.).
  Kontrast: `test_pin_code_decoding.py` gjør det riktig (laster funksjonen fra
  kilden via ast/compile) — samme teknikk kan brukes for `_decode_operation_event`.
- `tests/test_options_flow.py:64-77` (`test_timeout_maps_to_lock_unreachable`)
  er **vakuøs**: den leter etter linjen `"asyncio.TimeoutError, TimeoutError"`
  som ikke finnes i config_flow.py (verifisert med grep), så løkke-asserten
  kjører aldri. Testen består uansett hva except-blokken gjør.
- `tests/test_coordinator_slots.py:77-132` («TestSlotLogic») simulerer
  dict-operasjoner ved å kopiere kodelinjene inn i testen — består uansett.
- `tests/test_coordinator.py` tester, tross navnet, bare konstanter og JSON.
- **Ingen** atferdstest finnes for: `_send_cluster_command` (retry-løkken),
  `_wake_lock`, `_get_cluster`-kjedevandringen, `_save_slots`/`_load_slots`
  (ville fanget funn 1!), `read_lock_capabilities` (kun ast-sjekker i
  `test_coordinator_capabilities.py`), event-lytterens filtrering
  (`__init__.py:183-224`), sensorene eller service-handlerne.
**Anbefaling:** innfør lette HA-stubber (som `test_localize.py:15-22` allerede
gjør) og test coordinator + lytter med ekte objekter og falske
`hass.services.async_call`. Fjern eller merk de replikerte suitene.

### 5. «Suksess» betyr bare «sendt» — has_pin kan lyve
**Alvorlighet: MEDIUM-HØY — [kode-lest]**
`coordinator.py:236-245`: IndexError (Nimly-quirken) regnes som suksess — greit
per AGENTS.md — men det finnes ingen verifisering av at låsen *aksepterte*
PIN-en (avvist duplikat-PIN, ugyldig lengde iht. låsens min/max, full
slot-tabell). `set_pin` setter `has_pin=True` (`coordinator.py:279-284`) og UI
sier «vellykket» uansett. Bruker tror en kode virker på døra som ikke gjør det.
**Anbefaling:** der det er mulig, verifiser med `get_pin_code` (0x0006) etter
set, eller dokumenter usikkerheten i UI-teksten. Bruk innleste
`lock_capabilities` (min/max_pin_length) i valideringen i stedet for hardkodet
4-8 (`config_flow.py:161`, `services.py:59`) — verdiene leses i dag men brukes
aldri.

---

## P2 — Reelle hull, mindre eksponering

### 6. Multi-lås: tjenester uten `ieee` tar «første og beste» coordinator
**Alvorlighet: MEDIUM — [kode-lest]**
`services.py:16-24`: uten `ieee` returneres første entry i dict-rekkefølge. Med
to låser kan `onesti_lock.set_pin` programmere PIN på **feil dør** uten
feilmelding. Dict-rekkefølgen avhenger av oppsett-rekkefølge.
**Anbefaling:** krev `ieee` (eller device_id/target) når flere entries finnes;
kast ellers en tydelig feil.

### 7. NimlyCodePRO: auto-relock overskriver aktivitetssensoren likevel
**Alvorlighet: MEDIUM (alle CodePRO-brukere) — [kode-lest]**
`__init__.py:216-219` undertrykker bare `source == "auto"` (0x0A). CodePRO
fw 4.8 rapporterer 0x05 («unattributed») for auto-relock (`__init__.py:42-45`),
så på den modellen overskrives «Kari låste opp med kode» av
«unattributed lock» sekunder senere — akkurat det suppresjonen skulle hindre
(AGENTS.md gotcha 4). Sammenlign også literalen `"auto"` mot konstanten
`SOURCE_AUTO` som importeres men ikke brukes her.
**Anbefaling:** undertrykk også `SOURCE_UNATTRIBUTED` + `ACTION_LOCK`
kombinasjonen (lås-hendelser uten bruker), og bruk konstantene.

### 8. Bare TimeoutError utløser wake+retry — DeliveryError går rett til feil
**Alvorlighet: MEDIUM — [resonnert]**
`coordinator.py:246-263`: zigpy feiler ofte med `DeliveryError`/
`ZigbeeException` (f.eks. når meldingen kastes etter 7,68 s TTL hos parent-
routeren, jf. docs/technical.md:117). De havner i `except Exception` og
returnerer False uten wake-forsøk. Retry-mekanismen dekker dermed bare én av de
to vanlige feilmodusene for en sovende lås.
**Anbefaling:** behandle leveringsfeil som timeout i retry-løkken (match på
unntaksnavn via `type(exc).__name__` hvis zigpy ikke kan importeres direkte).

### 9. Aktivitetssensoren er tom etter hver HA-omstart
**Alvorlighet: MEDIUM — [kode-lest]**
`sensor.py:89-126`: `NimlyActivitySensor` arver ikke `RestoreEntity`;
`self._activity = {}` → state None til neste fysiske hendelse. «Hvem låste opp
sist» — hele poenget med integrasjonen — forsvinner ved hver omstart/oppgradering.
**Anbefaling:** bruk `RestoreEntity`/`RestoreSensor` og gjenopprett attributter.

### 10. Skjøre antakelser om ZHA/zigpy-interna (flere steder)
**Alvorlighet: MEDIUM — [kode-lest/resonnert]**
- `__init__.py:229-233`: `cluster._event_listeners` (privat attributt) leses
  **eagert** som argument til `_LOGGER.debug` — evalueres selv når debug er av.
  Renamer zigpy feltet, krasjer `async_setup_entry` med AttributeError.
- `__init__.py:226`: `cluster.on_event("attribute_report", ...)` er udokumentert
  zigpy-API; ingen fallback hvis signaturen endres.
- `coordinator.py:152-162` + `config_flow.py:43-48`: `zha_data.gateway_proxy
  .device_proxies` — intern struktur som har endret navn før i ZHA-historien.
- `coordinator.py:198`: lock-entitet gjenkjennes på `unique_id.endswith("257")`
  — uformattert antakelse om ZHA sitt unique_id-skjema; slår den feil, blir
  wake-retry stille en no-op.
- `coordinator.py:226`: endpoint 11 er hardkodet i sending, mens `_get_cluster`
  søker alle endpoints — inkonsistent hvis en modell bruker annet endpoint.
- Hvis ZHA lastes på nytt (reload/re-pair) byttes cluster-objektet ut; lytteren
  henger igjen på det gamle og integrasjonen slutter stille å motta hendelser
  til onesti_lock reloades. Ingen deteksjon/reetablering.
**Anbefaling:** pakk debug-linjen i `isEnabledFor`, hent endpoint-id fra
clusteret som ble funnet, lytt på ZHA config-entry state for re-registrering,
og logg tydelig (ikke bare debug) når `_get_cluster` feiler etter oppstart.

### 11. docs/technical.md motsier koden på source-map
**Alvorlighet: MEDIUM (dok) — [verifisert]**
`docs/technical.md:13`: «source (1 = RF, 2 = keypad, 3 = manual, 10 = auto)» —
koden (`__init__.py:37-47`) sier 0=zigbee, 2=keypad, 3=fingerprint, 4=rfid,
5=unattributed, 0x0A=auto. AGENTS.md:30-41 hevder å liste «Final correct values
used in code», men mangler 0x05. `docs/technical.md:16` sier 0x0101 er BCD;
koden håndterer BCD *og* ASCII (irrelevant etter fix 2, men fjern da hele
avsnittet). `docs/technical.md:10` («Byte 0: user_slot») og AGENTS.md:25 må
også oppdateres når 16-bit-fiksen lander (docs/slot-numbering.md:72 har
allerede riktig «bytes 0-1»).
**Anbefaling:** rett technical.md til å speile `_SOURCE_MAP`, føy 0x05 inn i
AGENTS.md, og pek begge til zigbee-captures.md som eneste kanoniske kilde.

### 12. name_slot-steget validerer ikke slot i det hele tatt
**Alvorlighet: MEDIUM-LAV — [kode-lest]**
`config_flow.py:308-325`: `vol.Coerce(int)` uten range — slot -5 eller 99999
aksepteres og lagres i options. Services-laget validerer (3-999), options-flowen
gjør det ikke; og docs/slot-numbering.md:70 sier «any slot number (0-999)» —
tre ulike regler for samme operasjon.
**Anbefaling:** `vol.Range(0, MAX_SLOTS-1)` i skjemaet + samstem docs.

---

## P3 — Mindre funn

### 13. VERSION = 2 uten async_migrate_entry
**LAV — [verifisert]** `config_flow.py:34`. Git-historikken viser at VERSION har
vært 2 siden aller første config-flow-commit (4cb59ba), så ingen v1-entries
finnes i felten — ufarlig i dag, men en felle: bump uten migrasjonssteg gjør at
HA nekter å laste eksisterende entries. Legg inn en no-op
`async_migrate_entry` nå, så er mønsteret etablert.

### 14. Options-flow: delt state og ukansellerte tasks
**LAV — [kode-lest]** `config_flow.py:132,245`: `_set_pin_input` gjenbrukes av
clear_pin («reused for slot reference») — skjør kobling; en fremtidig endring i
set_pin-stien kan gi clear_pin feil slot. Avbrytes flowen (lukk dialog) mens
progress-tasken kjører, fortsetter tasken og muterer options uten UI-feedback;
`async_remove` rydder ikke opp. To samtidige options-flows (to faner/brukere)
gir to tasks som skriver options samtidig — konsistent i minnet (samme
coordinator), men resultat-dialogene kan lyve om hverandres endringer.

### 15. Naiv lokal timestamp
**LAV — [kode-lest]** `sensor.py:155`: `datetime.now().isoformat()` uten
tidssone. HA-konvensjon er `dt_util.utcnow()`; naive stempler gjør
template-sammenligninger og tidssonebytter feilbare.

### 16. Aktivitetssensoren avregistreres aldri
**LAV — [kode-lest]** `sensor.py:136-137`: `set_activity_sensor(self)` i
`async_added_to_hass`, men ingen `async_will_remove_from_hass` som nuller den.
Fjernes entiteten (f.eks. deaktivert av bruker), skriver coordinatoren til en
død entitet (HA logger feil).

### 17. random i testparametrisering
**LAV — [kode-lest]** `test_event_properties.py:117-119`: `random.randint` ved
collection → 100 nye test-IDer per kjøring; bryter reproduserbarhet og
`--last-failed`. Bruk fast seed eller faste verdier.

### 18. Hardkodet norsk i blueprint
**LAV — [kode-lest]** `blueprints/automation/unlock_activity_notify.yaml:49-51,54`:
'Ukjent'/'Dørlåsen' hardkodet — samme klasse feil som issue #5 rettet i Python,
men `test_no_hardcoded_language.py` dekker ikke blueprints (og heller ikke
`__init__.py`, jf. MODULES-listen linje 16-22).

### 19. Dokumentasjon som må ryddes når fix 2 (last_pin_code) lander
**PÅMINNELSE — [verifisert]** README.md:114,120-126 (privacy-avsnittet),
README.md:193 (Z2M-paritetstabellen), docs/technical.md:16,
tests/test_pin_code_decoding.py (hele filen) og
tests/test_coordinator_capabilities.py:71-79 refererer alle last_pin_code /
0x0101 og vil enten motsi koden eller feile bygget etter fjerningen.

---

## Ikke undersøkt / forbehold

- Ingen HA/zigpy installert her: funn 1, 8, 10 bygger på kjent HA/zigpy-
  kjernekode-semantikk (funn 1 dog simulert mot den eksakte likhets-sjekken);
  verifiser mot brukerens faktiske HA-versjon før fiks.
- `.github/workflows/` kun overflatisk sjekket (refererer riktig katalog).
- `docs/nimly-connect-app/`, `docs/connect-bridge/`, BLE-docs og Z2M-planene i
  `docs/plans/` er ikke faktasjekket mot eksterne kilder.
- Åpne GitHub-issues er ikke lest (ingen nettverkstilgang brukt).
- Oversettelsesfilene da/sv er ikke språkvasket, kun strukturtestet (den delen
  av suiten — test_translations_files.py — er for øvrig reell og god).

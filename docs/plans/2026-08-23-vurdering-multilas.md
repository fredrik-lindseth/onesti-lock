# Vurdering: multilås-bug i services.py (dcat issues-58mevg)

## Bekreftelse av funnet (verifisert i kode)

`custom_components/onesti_lock/services.py:16-36`: `_get_coordinator` itererer
`hass.data[DOMAIN]` (dict keyet på `entry.entry_id`, insertion-ordnet etter
oppsettsrekkefølge, verifisert i `__init__.py:63-64`) og returnerer **første**
coordinator når `ieee is None`. Alle fire handlers (`set_pin`, `clear_pin`,
`set_name`, `clear_slot`) kaller den likt, og `ieee` er `vol.Optional` i alle
fire skjemaene (services.py:148-197). Med to låser og utelatt `ieee`
programmeres PIN-en på den låsen som ble konfigurert først, uten feil.
Funnet er reelt og alvorlig: feil dør kan få en gyldig kode.

## Beslutning (svar på spm. 1)

**Anbefaling: guard + device-selector, ikke `target`.**

1. **Bugfix**: `_get_coordinator` skal kaste `HomeAssistantError`
   (`translation_key="multiple_locks"`) når hverken `device_id` eller `ieee`
   er oppgitt og det finnes mer enn én coordinator. Én coordinator uten
   selektor fortsetter å virke som i dag.
2. **Nytt valgfritt felt `device_id`** i alle fire tjenester, med
   `selector: device: integration: onesti_lock` i services.yaml. Integrasjonen
   registrerer egne devices med `identifiers={(DOMAIN, ieee)}` (verifisert i
   `sensor.py:71-73` og `:126-128`), så device-oppslag via device registry er
   rett fram. Presedens: `device_id`-felt med integrasjonsfiltrert
   device-selector er dagens idiom for domenetjenester som virker på én enhet
   (resonnert fra HA-konvensjon, ikke verifisert lokalt).
3. **`ieee` beholdes** som valgfritt felt for bakoverkompatibilitet og
   scripting. Presedens: ZHA selv adresserer enheter med ieee i flere
   tjenester (resonnert fra HA-konvensjon).
4. Prioritet ved begge oppgitt: `device_id` vinner (den kommer fra en
   dropdown og er minst utsatt for skrivefeil).

**Hvorfor ikke `target`/entity_id**: `target`-mønsteret hører til
entity-tjenester. Denne integrasjonens egne entities er sensorer; selve
lock-entiteten eies av ZHA (verifisert: integrasjonen oppretter ingen
lock-plattform, kun `sensor.py`). Å targete ZHA-låsens entity ville kreve
oppslag på tvers av integrasjoner, og å bytte skjema til `target:` bryter
samtlige eksisterende automasjoner. Forkastes.

## Hva brytes (svar på spm. 2)

- **Én lås, uten ieee** (de aller fleste): uendret, virker som før. Verifisert
  at koden tar denne veien (`ieee is None` + én entry → return).
- **Én lås, med ieee**: uendret.
- **Flere låser, med ieee**: uendret.
- **Flere låser, uten ieee**: får nå en handlingsrettet feil i stedet for
  stille programmering av først-konfigurert lås. Dette er selve bugfixen og
  en tilsiktet, ønsket endring i oppførsel.
- Ingen felter fjernes, ingen skjemaendring er breaking. `target`-varianten
  ville brutt alt; derfor valgt bort.

## Oversettelsesnøkler (svar på spm. 3)

Gjenbruk (verifisert at nøklene finnes i alle fem filene med samme
placeholdere; paritet håndheves av `tests/test_translations_files.py`):
- `lock_not_found_ieee` ({ieee}): gjenbrukes både for ukjent ieee OG for et
  device_id som peker på en onesti-device hvis coordinator ikke er lastet
  (vi kjenner da ieee fra device-identifieren).
- `lock_not_found`: gjenbrukes for device_id som ikke er en onesti_lock-device,
  og for null konfigurerte låser.

**Én ny nøkkel trengs**: `multiple_locks` med placeholder `{ieees}`.
Ingen eksisterende nøkkel kan dekke flertydighet ("finnes flere") uten å lyve.
Merk: unngå tankestrek i tekstene (`EM_DASH`-sjekk i testene).

Ferdige tekster (samme i strings.json og translations/en.json, som må være
identiske, håndhevet av `test_strings_json_equals_en`):

- en: "Multiple Onesti locks are configured. Choose one in the lock field or
  give its IEEE address. Configured locks: {ieees}"
- nb: "Flere Onesti-låser er konfigurert. Velg en lås i låsefeltet eller oppgi
  IEEE-adressen. Konfigurerte låser: {ieees}"
- sv: "Flera Onesti-lås är konfigurerade. Välj ett lås i låsfältet eller ange
  dess IEEE-adress. Konfigurerade lås: {ieees}"
- da: "Flere Onesti-låse er konfigureret. Vælg en lås i låsefeltet eller angiv
  dens IEEE-adresse. Konfigurerede låse: {ieees}"

## Er ieee brukervennlig? (svar på spm. 4)

Nei. "00:11:22:33:44:55:66:77" skrevet for hånd i en YAML-automasjon er
feilutsatt (og dagens kode feiler først i runtime, ikke ved validering).
Device-dropdownen viser låsens navn ("Ytterdør") og er riktig svar uavhengig
av bugen. `ieee` beholdes kun som maskinvennlig fallback; beskrivelsen i
services.yaml nedgraderes til "advanced".

## Implementasjonsplan, fil for fil

### 1. custom_components/onesti_lock/services.py

Ny import:

    from homeassistant.helpers import device_registry as dr

Erstatt `_get_coordinator` (linje 16-36) med:

    def _get_coordinator(
        hass: HomeAssistant,
        ieee: str | None = None,
        device_id: str | None = None,
    ):
        """Get the coordinator for one lock, resolved by device or IEEE."""
        coordinators = [
            entry_data["coordinator"]
            for entry_data in hass.data.get(DOMAIN, {}).values()
            if entry_data.get("coordinator") is not None
        ]

        if device_id is not None:
            device = dr.async_get(hass).async_get(device_id)
            device_ieee = None
            if device is not None:
                for domain, identifier in device.identifiers:
                    if domain == DOMAIN:
                        device_ieee = identifier
                        break
            if device_ieee is None:
                raise HomeAssistantError(
                    "No Onesti lock found",
                    translation_domain=DOMAIN,
                    translation_key="lock_not_found",
                )
            ieee = device_ieee

        if ieee is not None:
            for coordinator in coordinators:
                if coordinator.ieee.lower() == ieee.lower():
                    return coordinator
            raise HomeAssistantError(
                f"No Onesti lock found with IEEE {ieee}",
                translation_domain=DOMAIN,
                translation_key="lock_not_found_ieee",
                translation_placeholders={"ieee": ieee},
            )

        if len(coordinators) == 1:
            return coordinators[0]
        if len(coordinators) > 1:
            ieees = ", ".join(c.ieee for c in coordinators)
            raise HomeAssistantError(
                f"Multiple Onesti locks are configured: {ieees}",
                translation_domain=DOMAIN,
                translation_key="multiple_locks",
                translation_placeholders={"ieees": ieees},
            )
        raise HomeAssistantError(
            "No Onesti lock found",
            translation_domain=DOMAIN,
            translation_key="lock_not_found",
        )

I hver av de fire handlerne: legg til
`device_id = call.data.get("device_id")` ved siden av dagens
`ieee = call.data.get("ieee")`, og endre kallet til
`_get_coordinator(hass, ieee, device_id)`.

I alle fire `vol.Schema`-blokkene (linje 152-197): legg til
`vol.Optional("device_id"): cv.string,` ved siden av
`vol.Optional("ieee"): cv.string,`.

### 2. custom_components/onesti_lock/services.yaml

I hver av de fire tjenestene, legg til feltet FØR `ieee` og oppdater
ieee-beskrivelsen. Ferdig tekst per tjeneste (identisk blokk x4):

    device_id:
      name: Lock
      description: The lock to act on (required when multiple locks are configured)
      required: false
      selector:
        device:
          integration: onesti_lock
    ieee:
      name: IEEE address
      description: Advanced alternative to the lock field, e.g. for scripts (optional if only one lock)
      required: false
      selector:
        text:

(Repoet bruker inline name/description i services.yaml, ikke
`services`-seksjon i strings.json; behold det mønsteret. Verifisert:
strings.json har ingen `services`-seksjon.)

### 3-7. strings.json + translations/{en,nb,sv,da}.json

Legg `multiple_locks` inn i `exceptions`-seksjonen i alle fem filene, med
tekstene over. strings.json og en.json må være tegn-for-tegn like.

    "multiple_locks": {
      "message": "Multiple Onesti locks are configured. Choose one in the lock field or give its IEEE address. Configured locks: {ieees}"
    }

(nb/sv/da: tekstene i seksjonen "Oversettelsesnøkler" over.)

### 8. tests/test_translations_files.py

Legg `"multiple_locks"` til i `EXCEPTION_KEYS` (linje 24-30). Paritets- og
placeholder-testene dekker da den nye nøkkelen automatisk. Legg gjerne til:

    def test_multiple_locks_has_ieees(self):
        message = _load("strings.json")["exceptions"]["multiple_locks"]["message"]
        assert _placeholders(message) == {"ieees"}

### 9. tests/test_services_multilock.py (ny fil)

Følg stub-mønsteret fra `tests/test_coordinator_behavior.py` (sys.modules-
stubs + importlib under stub-pakke, sync-tester som driver koroutiner med
`asyncio.run()`). services.py krever stubs for: `homeassistant`,
`homeassistant.core` (`HomeAssistant`, `ServiceCall`),
`homeassistant.exceptions` (`HomeAssistantError` som Exception-subklasse som
aksepterer kwargs `translation_domain`, `translation_key`,
`translation_placeholders` og lagrer dem som attributter),
`homeassistant.helpers`, `homeassistant.helpers.config_validation`
(`cv.string = str`), `homeassistant.helpers.device_registry`
(`async_get = lambda hass: hass.device_registry`) og `voluptuous`
(`Schema`/`Required`/`Optional`/`Coerce` som no-op-klasser; skjemaet
håndheves av HA, ikke av testene). NB: sjekk om tidligere tester allerede har
lagt inn `homeassistant.exceptions`-stub uten kwargs-støtte; bruk
setdefault-mønsteret forsiktig eller overstyr attributtet eksplisitt.

Fakes: `FakeCoordinator(ieee)` med async `set_pin/clear_pin/set_slot_name/
clear_slot` som logger kall og returnerer True. `FakeHass` med
`data = {DOMAIN: {"e1": {"coordinator": c1}, "e2": {"coordinator": c2}}}`,
`services` med `async_register` som fanger handler-funksjonene, og
`device_registry` med `async_get(device_id)` som returnerer objekt med
`identifiers = {(DOMAIN, ieee)}` eller None. `FakeServiceCall` = objekt med
`.data`-dict. Testene registrerer tjenestene via
`asyncio.run(async_setup_services(hass))` og kaller de FANGEDE handlerne,
slik at hele veien handler -> _get_coordinator -> coordinator bevises, ikke
bare kildetekst.

Oppførselstester (alle via handlers, primært `set_pin`):
1. To låser, hverken device_id eller ieee: `HomeAssistantError` med
   `translation_key == "multiple_locks"` og begge ieee-ene i
   `translation_placeholders["ieees"]`; INGEN coordinator fikk kall.
2. To låser, ieee = lås 2 med annen casing ("AA:BB..." mot "aa:bb..."):
   lås 2 sin `set_pin` kalles med (slot, name, code), lås 1 urørt.
3. Én lås, ingen selektor: virker (bakoverkompatibilitet).
4. To låser, device_id som resolver til lås 2: lås 2 kalles, lås 1 urørt.
5. device_id som ikke er en onesti-device (registry returnerer None eller
   identifiers uten DOMAIN): `translation_key == "lock_not_found"`.
6. Ukjent ieee: `translation_key == "lock_not_found_ieee"` med
   `translation_placeholders == {"ieee": ...}`.
7. Samme flertydighetsfeil for `clear_pin`, `set_name` og `clear_slot`
   (parametrisert over de fire fangede handlerne).
8. device_id OG ieee oppgitt, motstridende: device_id vinner.

### 10. README.md (valgfritt, anbefalt)

Dokumenter det nye feltet og flerlås-kravet i tjenesteeksemplene.

## Rekkefølge og risiko

Rekkefølge: 1 (services.py) -> 2 (yaml) -> 3-7 (JSON x5) -> 8 -> 9.
Kjør `ruff check` + `pytest tests/ -v`. Størst risiko: stub-kollisjon i
sys.modules mellom testfiler (HomeAssistantError-stub uten kwargs fra en
annen testfil kan lekke inn avhengig av kjørerekkefølge); løses ved å sette
kwargs-varianten ubetinget i den nye testfilen før modulen lastes, eller ved
å laste services.py under eget pakkenavn slik test_coordinator_behavior.py
gjør. Ingen endring i coordinator.py eller __init__.py er nødvendig.

## Verifisert vs. resonnert

Verifisert i repoet: hele buggen og dict-rekkefølgen; at ieee er Optional i
alle fire skjemaer; device-identifiers `(DOMAIN, ieee)` i sensor.py; at
integrasjonen ikke har egen lock-entity; exceptions-nøklene og parity-testene;
stub-/CI-begrensningene (CI = ruff + pytest, tests/ stubber homeassistant).
Resonnert fra HA-konvensjon (ikke verifiserbart lokalt uten HA installert):
at `device:`-selector med `integration:`-filter er dagens idiom for
enhetsrettede domenetjenester; at `target:` hører til entity-tjenester; at
`dr.async_get(hass).async_get(device_id)` er riktig registry-API; at HA
oversetter `exceptions`-seksjonen med placeholders slik koden antar (dagens
kode bruker allerede mønsteret, så antakelsen er lav risiko).

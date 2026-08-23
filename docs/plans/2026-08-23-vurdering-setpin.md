# Vurdering: set_pin melder suksess uten bekreftelse (dcat issues-2i5n8q)

Dato: 2026-08-23. Kun analyse — ingen kode endret.

## Konklusjon i kortform

1. **Tilbakelesing med `get_pin_code` (0x0006): IKKE nå.** Uverifisert på denne maskinvaren, sannsynligvis rammet av samme responsquirk som gjør at vi ikke kan lese svar i dag, og selve svaret er PIN i klartekst. Hardware-test først; til da er en tilbakelesing bygget på antakelser.
2. **Validering mot kapabiliteter: JA.** Lav risiko, ren gevinst. Bruk innleste `min_pin_length`/`max_pin_length` med fallback 4-8 når de ikke er lest.
3. **Ærlig UI-tekst: JA.** Skjemabeskrivelsen for set_pin skal si at låsen ikke bekrefter at koden ble godtatt, og at koden må testes på tastaturet. `invalid_pin`-nøklene gjenbrukes med `{min}`/`{max}`-placeholdere — ingen nye nøkler.

Punkt 2 og 3 fjerner de mest sannsynlige årsakene til stille avvisning (feil lengde) og gjør resten (duplikat, full tabell) synlig som en dokumentert begrensning i stedet for en løgn. Ekte bekreftelse krever hardware-arbeid først (se «Hardware-tester»).

---

## 1. Tilbakelesing med get_pin_code (0x0006)

### Hva jeg har verifisert i repoet

- **Ingen capture finnes.** `docs/zigbee-protocol/zigbee-captures.md` inneholder ikke ett eneste 0x0006-svar. Kommandoen nevnes bare som eksisterende i `docs/slot-numbering.md:17`, og `CMD_GET_PIN = 0x0006` i `const.py:37` er definert men aldri brukt. Vi vet altså ikke hva låsen svarer.
- **Dagens sendevei kan ikke lese svar i det hele tatt.** `coordinator.py` `_send_cluster_command` går via HA-tjenesten `zha.issue_zigbee_cluster_command`, som ikke returnerer responsdata til kalleren. En tilbakelesing måtte gå direkte på zigpy-clusteret fra `_get_cluster()` (`await cluster.get_pin_code(user_id)`) — en ny kodevei med egne feilmoduser.
- **Quirken treffer sannsynligvis også 0x0006.** `docs/technical.md:56` og `docs/debugging.md` (avsnittet «IndexError quirk») dokumenterer at PIN-kommandoenes svar er misformet og krasjer zigpys parser med `IndexError` før payload er tilgjengelig. Hele verdien av `get_pin_code` ER svaret; hvis Get PIN Code Response er misformet på samme måte, får vi `IndexError` og null informasjon. Bare sniffing på ekte lås kan avgjøre dette.
- **Det finnes en bedre kilde til samme informasjon.** ZCL-spesifikasjonen sier at Set PIN Code (0x0005) skal besvares med en Set PIN Code Response med statusbyte: 0 = success, 1 = general failure, 2 = memory full, 3 = duplicate code. Det er *nøyaktig* informasjonen funnet etterlyser — og det er nøyaktig det svaret quirken ødelegger. Den riktige langsiktige fiksen er å capture det rå svaret og skrive en zigpy-quirk som parser det (kan sendes oppstrøms til zha-device-handlers, jf. eksisterende referanse til PR #4881). Da får vi ekte aksept/avvisning uten ekstra round-trip og uten å røre PIN i klartekst.
- **Kostnad mot sovende lås:** En tilbakelesing rett etter vellykket set_pin skjer trolig mens radioen fortsatt er våken (den ACK-et nettopp kommandoen), så auto-wake (`_wake_lock`: `lock.lock` + 1 s sleep) trengs sannsynligvis ikke — men «trolig» er uverifisert, og våken-vinduets lengde er ukjent. I verste fall dobles tiden (timeout → wake → retry). Viktigere: tilbakelesing gir en ny tvetydig tilstand — «satt, men verifisering timet ut» — som IKKE kan rapporteres som feil (koden kan ligge der). UI måtte skille «bekreftet» / «sendt, ubekreftet» / «feilet». Det er mye kompleksitet for en mekanisme vi ikke vet virker.

### Sikkerhet hvis tilbakelesing likevel innføres senere

Et vellykket 0x0006-svar inneholder PIN i klartekst (samme klasse problem som attributt 0x0101, fjernet i commit 57ed320). Kravene, som en fremtidig plan må oppfylle:

- Svaret sammenlignes i en lokal variabel i coordinator-metoden og forkastes umiddelbart. Aldri argument til `_LOGGER`, aldri inn i `slot_data`, aldri i exception-tekst. Logg kun utfallet som boolsk («PIN verified in slot %d» / «PIN mismatch in slot %d»).
- `tests/test_no_pin_exposure.py` forblir grønn av konstruksjon: AST-vakten flagger PIN-formede identifikatorer som sendes til `_LOGGER`-kall og `slot_data["code"]`-lagring; en ren i-minne-sammenligning trigger ingen av delene. Testen skal IKKE svekkes — den er nettopp vakten mot regresjon her.
- Restrisiko som må aksepteres eksplisitt: zigpy/ZHA logger rå frames på DEBUG-nivå utenfor vår kontroll. Det gjaldt også 0x0101-rapportene, men en aktiv tilbakelesing *velger* å frakte PIN over løsningen én gang til. Enda et argument for quirk-på-0x0005-status i stedet: statusbyten inneholder ingen PIN.

### Anbefaling punkt 1

Ikke implementer tilbakelesing nå. Kjør hardware-testene nedenfor; hvis 0x0005-responsen viser seg å ha parsebar status, er zigpy-quirk veien til ekte bekreftelse. Tilbakelesing er reserveløsning hvis 0x0006 mot formodning parser rent mens 0x0005-responsen forblir ubrukelig.

---

## 2. Validering mot lock_capabilities

### Verifisert i koden

- `coordinator.read_lock_capabilities()` (`coordinator.py:97-142`) leser 0x0012/0x0017/0x0018 og legger `num_pin_users`, `max_pin_length`, `min_pin_length` i `self.lock_capabilities`. Kalles fire-and-forget fra `__init__.py:78`; dicten kan altså være tom lenge (sovende lås ved oppstart) eller for alltid (varianter uten attributtene).
- Verdiene brukes i dag KUN som sensorattributter (`sensor.py:121-122`). Valideringen er hardkodet `len(code) < 4 or len(code) > 8` to steder: `services.py:59` og `config_flow.py:161`.
- Live-verifiserte verdier for NimlyPRO står i `tests/test_coordinator_capabilities.py:48-49`: 0x0012=50, 0x0017=8, 0x0018=4. Altså: fallback 4-8 er identisk med det ekte svaret på referanselåsen.

### Fallback eller nekte?

**Fallback til 4-8.** Å nekte PIN-setting fordi låsen sov gjennom oppstart er dårligere UX uten reell sikkerhetsgevinst — låsen avviser selv koder utenfor sitt område, og punkt 3 gjør den begrensningen ærlig i UI. 4-8 er dessuten verifisert korrekt for NimlyPRO og er området BLE-appen håndhever (`reversing/.../CommandPincodeSet.java:28` — `verifyRawString(..., 4, 8)`), så det er en trygg antakelse for hele Onesti-familien. Legg inn sanity-clamp: rapporterer låsen tull (min<1, max>20, min>max), bruk 4-8.

**Bonus (valgfritt):** i `set_pin`/`clear_pin`-suksessveien, hvis `lock_capabilities` er tom, trigg `read_lock_capabilities()` — radioen er beviselig våken akkurat da. Merk: gjøres dette med `hass.async_create_task` må `FakeHass` i `tests/test_coordinator_behavior.py` få en `async_create_task`-stub; hold det derfor som eget, valgfritt steg.

### Merknad utenfor scope (bør bli egen sak)

`num_pin_users=50` på NimlyPRO, men `MAX_SLOTS=1000` og services.yaml sier 3-199. Slot ≥ 50 avvises muligens stille i dag — samme klasse problem som funnet. Hardware-test 300 (sammenfaller med 16-bit-testen i `zigbee-captures.md:38-45`) og f.eks. slot 60.

---

## 3. Implementasjonsplan (fil for fil)

### 3.1 Ny fil: `custom_components/onesti_lock/pin_rules.py`

Ren modul, null HA-importer (dermed direkte testbar i CI som kun har pytest):

```python
"""PIN validation rules — pure logic, no Home Assistant imports."""
from __future__ import annotations

from collections.abc import Mapping

DEFAULT_MIN_PIN_LENGTH = 4
DEFAULT_MAX_PIN_LENGTH = 8
# Sanity bounds: capabilities outside this window are treated as garbage.
_ABSOLUTE_MIN = 1
_ABSOLUTE_MAX = 20


def pin_length_range(capabilities: Mapping[str, int] | None) -> tuple[int, int]:
    """Effective (min, max) PIN length: lock capabilities with 4-8 fallback."""
    caps = capabilities or {}
    min_len = caps.get("min_pin_length", DEFAULT_MIN_PIN_LENGTH)
    max_len = caps.get("max_pin_length", DEFAULT_MAX_PIN_LENGTH)
    if not (
        isinstance(min_len, int)
        and isinstance(max_len, int)
        and _ABSOLUTE_MIN <= min_len <= max_len <= _ABSOLUTE_MAX
    ):
        return DEFAULT_MIN_PIN_LENGTH, DEFAULT_MAX_PIN_LENGTH
    return min_len, max_len


def is_valid_pin(code: str, capabilities: Mapping[str, int] | None) -> bool:
    """Digits only, length within the lock's advertised range."""
    min_len, max_len = pin_length_range(capabilities)
    return code.isdigit() and min_len <= len(code) <= max_len
```

(Verdiene fra `read_lock_capabilities` er allerede `int(value)`, så isinstance-sjekken er belte og bukser.)

### 3.2 `custom_components/onesti_lock/coordinator.py`

Legg til convenience-metode (ingen endring i `set_pin`s suksessdefinisjon i denne omgang):

```python
from .pin_rules import pin_length_range

def pin_length_range(self) -> tuple[int, int]:
    """Effective (min, max) PIN length for this lock."""
    return pin_length_range(self.lock_capabilities)
```

(Navnekollisjon modul/metode unngås med `from .pin_rules import pin_length_range as _pin_length_range` eller `from . import pin_rules` + `pin_rules.pin_length_range(...)` — velg det siste for lesbarhet.)

### 3.3 `custom_components/onesti_lock/services.py`

Erstatt i `handle_set_pin` (linje 59-64):

```python
        coordinator = _get_coordinator(hass, ieee)
        min_len, max_len = coordinator.pin_length_range()
        if not code.isdigit() or not min_len <= len(code) <= max_len:
            raise HomeAssistantError(
                f"PIN code must be {min_len}-{max_len} digits",
                translation_domain=DOMAIN,
                translation_key="invalid_pin",
                # HA rejects non-string placeholder values.
                translation_placeholders={"min": str(min_len), "max": str(max_len)},
            )
```

Merk: `_get_coordinator`-kallet må flyttes FØR valideringen (i dag ligger det etter). `translation_placeholders`-mekanismen er verifisert i repoet — `invalid_slot` bruker den allerede (services.py:52-57).

### 3.4 `custom_components/onesti_lock/config_flow.py`

I `async_step_set_pin`:

```python
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        min_len, max_len = coordinator.pin_length_range()
        ...
            if not code.isdigit() or not min_len <= len(code) <= max_len:
                errors["code"] = "invalid_pin"
                suggested = user_input
        ...
        return self.async_show_form(
            step_id="set_pin",
            data_schema=self._build_set_pin_schema(strings, suggested),
            errors=errors,
            description_placeholders={
                "pin_min": str(min_len),
                "pin_max": str(max_len),
                "min": str(min_len),
                "max": str(max_len),
            },
        )
```

`description_placeholders` på `async_show_form` er verifisert mønster i repoet (view_slots, config_flow.py:369). At HA-frontenden også substituerer placeholdere i *error*-strenger må verifiseres i live HA (se hardware/live-tester); beskrivelsesteksten viser uansett riktig område, så feilrendring degraderer til «{min}-{max}» i verste fall — da fjernes placeholderne fra error-strengen og den gjøres tall-løs («PIN-koden har feil lengde, se beskrivelsen»).

### 3.5 Tekster — alle fem JSON-filene

Tre endringer per fil. `strings.json` og `translations/en.json` skal være identiske (AGENTS.md gotcha 7).

**`options.step.set_pin.description`:**
- en/strings.json: `"Select slot, enter name and PIN code ({pin_min}-{pin_max} digits). Slot numbers correspond to the lock's internal user slots (ZCL DoorLock). Slots 0-2 are reserved for master codes. The lock confirms receiving the code but not accepting it — test the code on the keypad afterwards."`
- nb: `"Velg slot, skriv navn og PIN-kode ({pin_min}-{pin_max} siffer). Slot-numrene tilsvarer låsens interne brukerslots (ZCL DoorLock). Slot 0-2 er reservert for master-koder. Låsen bekrefter at koden er mottatt, men ikke at den er godtatt — test koden på tastaturet etterpå."`
- sv: `"Välj plats, ange namn och PIN-kod ({pin_min}-{pin_max} siffror). Platsnumren motsvarar låsets interna användarplatser (ZCL DoorLock). Plats 0-2 är reserverade för masterkoder. Låset bekräftar att koden tagits emot, men inte att den godtagits — testa koden på knappsatsen efteråt."`
- da: `"Vælg plads, indtast navn og PIN-kode ({pin_min}-{pin_max} cifre). Pladsnumrene svarer til låsens interne brugerpladser (ZCL DoorLock). Plads 0-2 er reserveret til masterkoder. Låsen bekræfter, at koden er modtaget, men ikke at den er accepteret — test koden på tastaturet bagefter."`

**`options.error.invalid_pin`** (gjenbrukt nøkkel, nå med placeholdere):
- en/strings.json: `"PIN code must be {min}-{max} digits"`
- nb: `"PIN-koden må være {min}-{max} siffer"`
- sv: `"PIN-koden måste vara {min}-{max} siffror"`
- da: `"PIN-koden skal være {min}-{max} cifre"`

**`exceptions.invalid_pin.message`** (gjenbrukt nøkkel):
- en/strings.json: `"PIN code must be {min}-{max} digits"`
- nb: `"PIN-koden må være {min}-{max} siffer"`
- sv: `"PIN-koden måste vara {min}-{max} siffror"`
- da: `"PIN-koden skal være {min}-{max} cifre"`

Ingen nye nøkler. `tests/test_translations_files.py` håndhever nøkkel- OG placeholder-paritet på tvers av alle fem filene, så identiske placeholdere overalt holder den grønn.

### 3.6 `custom_components/onesti_lock/services.yaml`

`code`-feltets beskrivelse: `"PIN code (digits; most models accept 4-8, the lock enforces its own limits)"`. Statisk engelsk tekst, ingen placeholder-støtte her. Vurder samtidig `set_pin`-tjenestens description: `"Send a PIN code to a lock slot. The lock does not confirm acceptance — test the code on the keypad."`

### 3.7 `docs/debugging.md`

Avsnittet «There is no programmatic confirmation …» stemmer og beholdes; legg til én setning om at lengde nå valideres mot låsens rapporterte min/max før sending.

---

## 4. Tester (kjører uten homeassistant og uten voluptuous)

CI installerer kun ruff + pytest, så alt følger mønstrene i repoet: rene moduler importeres direkte, HA-avhengige filer analyseres som tekst/AST, coroutines drives med `asyncio.run()`.

1. **Ny `tests/test_pin_rules.py`** — importerer `pin_rules.py` via `importlib.util.spec_from_file_location` under stub-pakke (mønster: `test_coordinator_behavior.py:41-56`; her trengs ikke engang HA-stubber siden modulen er ren). Tester:
   - tom/None capabilities → (4, 8)
   - `{"min_pin_length": 6, "max_pin_length": 10}` → (6, 10)
   - delvis (`kun min` / kun max) → resten fra default
   - søppel (min 0; max 99; min > max) → (4, 8)
   - `is_valid_pin`: «123» avvist, «1234» og «12345678» godtatt, «123456789» avvist, «12a4» avvist, «12.4» avvist (`isdigit` er falsk), grenser respekterer capabilities
2. **Utvid `tests/test_coordinator_behavior.py`** — `coord.pin_length_range()` er (4, 8) ved tom `lock_capabilities` og (6, 10) etter `coord.lock_capabilities.update(...)`. Kjører mot ekte klasse med eksisterende FakeHass.
3. **Ny AST/tekst-test (f.eks. i `tests/test_pin_rules.py` eller egen fil)** — leser `services.py` og `config_flow.py` som tekst (mønster: `test_coordinator_capabilities.py`) og asserter at (a) begge refererer `pin_length_range`, (b) hardkodingen `len(code) < 4` / `len(code) > 8` er borte, (c) `services.py` sender `translation_placeholders` med `min`/`max` for `invalid_pin`.
4. **Eksisterende vakter forblir grønne uendret:** `test_no_pin_exposure.py` (ingen nye `_LOGGER`-kall med PIN-formede verdier, `DEFAULT_SLOT` urørt, ingen `slot_data["code"]`), `test_translations_files.py` (paritet), `test_no_hardcoded_language.py` (alle nye brukertekster ligger i JSON, ikke Python — merk at f-strengen i HomeAssistantError-fallbacken i services.py er engelsk fallback slik `invalid_slot` allerede gjør).

---

## 5. Hardware-/live-tester (Fredrik, ekte lås + HA)

Kan ikke verifiseres i repoet — må testes:

1. **Sniff Set PIN Code Response (0x0005)** med Zigbee-sniffer for: (a) gyldig ny kode, (b) duplikat av eksisterende kode, (c) slot 60 og 300 (over num_pin_users=50; sammenfaller med 16-bit-slot-testen i `zigbee-captures.md:38-45`), (d) om mulig for kort kode sendt rått. Finnes en statusbyte (ZCL: 0/1/2/3=duplicate) i det «misformede» svaret, er en zigpy-quirk veien til ekte bekreftelse — legg rå frames i `docs/zigbee-protocol/zigbee-captures.md`.
2. **Prøv `cluster.get_pin_code(slot)`** direkte på zigpy-clusteret (Developer Tools / debug-script): parser svaret, eller `IndexError`? Hva returneres for opptatt vs. ledig slot? IKKE logg payload permanent noe sted.
3. **Avviser låsen duplikat-PIN i det hele tatt?** Sett samme kode i to slots, test på tastaturet hvilken slot 0x0100-eventen rapporterer.
4. **Våken-vindu:** hvor lenge etter en ACK-et kommando svarer låsen uten wake? (Avgjør om fremtidig verifisering trenger auto-wake.)
5. **Live HA:** bekreft at `{min}`/`{max}` substitueres i options-flow-*error*-strengen (beskrivelsen er dokumentert-sikker). Rendres de literalt, aktiver fallbacken i 3.4.
6. **Kapabilitetslesing på hans lås:** bekreft 0x0012=50 / 0x0017=8 / 0x0018=4 og at lesingen lykkes når låsen er våken.

---

## 6. Skillet verifisert / antatt

**Verifisert i repo:** ingen 0x0006-captures; `zha.issue_zigbee_cluster_command` returnerer ikke respons til `_send_cluster_command`; quirken dokumentert for 0x0005/0x0007; capabilities leses men brukes ikke i validering; live-verdier 50/8/4 i testkommentar; `translation_placeholders`-mønsteret for exceptions; `description_placeholders`-mønsteret for step-beskrivelser; BLE-appen håndhever 4-8; alle fem JSON-filers nåværende innhold.

**Antatt / må testes:** at 0x0006-responsen krasjer parseren; at statusbyten finnes i 0x0005-responsen; at radioen er våken rett etter ACK; at duplikat faktisk avvises av låsen; at HA substituerer placeholdere i options-error-strenger; at fallback 4-8 gjelder alle Onesti-varianter.

### Critical Files for Implementation

- /Users/fredrik/dev/privat/hacs-onesti/custom_components/onesti_lock/coordinator.py
- /Users/fredrik/dev/privat/hacs-onesti/custom_components/onesti_lock/services.py
- /Users/fredrik/dev/privat/hacs-onesti/custom_components/onesti_lock/config_flow.py
- /Users/fredrik/dev/privat/hacs-onesti/custom_components/onesti_lock/strings.json (+ translations/{en,nb,sv,da}.json)
- /Users/fredrik/dev/privat/hacs-onesti/tests/test_coordinator_behavior.py (mønster for nye tester)

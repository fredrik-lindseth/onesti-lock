# Vurdering: aliasing-fiksen i ee9b2db og samme feilklasse ellers

Dato: 2026-08-23. Arbeidstre rent, HEAD `4f8a5e1`. Testsuite kjørt: 1454 passed (verifisert).
Metode: hele veien options flow -> coordinator -> lagring lest; ekte `coordinator.py` og
`localize.py` kjørt mot stubbet HA (samme sele som `tests/test_coordinator_behavior.py`),
med identitetsprober (`is`) på hvert ledd. Merket per punkt: [KJØRT] = verifisert ved
kjøring, [RESONNERT] = kodelesing (HA er ikke installert).

## Del 1: Holder fiksen? JA

`custom_components/onesti_lock/coordinator.py:55-61` (`_save_slots`) kopierer hver
slot-dict: `{k: dict(v) for k, v in self._slots.items()}`.

1. **Dyp nok?** Ja. Slot-dictene inneholder kun `name` (str), `has_pin`/`has_rfid` (bool).
   Alle skrivere er lest: `set_slot_name` (:82), `set_pin` (:281-283), `clear_pin` (:295),
   `clear_slot` (:310), `_load_slots` (:45). Ingen legger inn nestede mutable verdier, så
   ett nivå kopi er tilstrekkelig. [KJØRT: verdi-typene i en levende slot er str/bool;
   `entry.options["slots"] is not coord._slots` og inner-dict `is not` på hvert nivå.]
2. **Kan aliaset gjenoppstå?**
   - `_load_slots` (:44-45): bygger nye dicter med `{**DEFAULT_SLOT, **v}` — ingen alias
     mot `entry.options`. [KJØRT: restart-rundtur via json-persistert options, `is`-sjekk negativ.]
   - Options flow: `config_flow.py:213,300,322` gjør `async_create_entry(data=self.config_entry.options)`.
     HA sin OptionsFlowManager kaller `async_update_entry(entry, options=result["data"])`;
     data ER `entry.options`, sammenligner likt -> no-op. Selv om den skrev, inneholder
     `entry.options["slots"]` allerede kopier fra `_save_slots`, aldri `_slots`-objektene.
     [KJØRT mot fake som replikerer likhetsporten: ingen re-alias, og NESTE lagring
     persisteres fortsatt. RESONNERT: at ekte HA wrapper i MappingProxyType uten kopi —
     ufarlig fordi eneste sted `_slots`-innhold krysser inn i options er `_save_slots`.]
   - Ingen andre steder i integrasjonen kaller `async_update_entry` eller skriver options (grep).
3. **Teoretisk rest** [RESONNERT]: håndredigert `.storage` med nestet mutable verdi inne i
   en slot ville deles mellom `_slots` og options (`{**DEFAULT_SLOT, **v}` og `dict(v)` er
   begge grunne), men ingen kode leser eller muterer slike verdier. Inert, ikke en bug.

## Del 2: Samme feilklasse ellers — 0 reelle bugs, 3 uheldige mønstre

**Reelle bugs (noen muterer faktisk): INGEN.**

Uheldige mønstre (kan bli bug, ingen muterer i dag):

1. `coordinator.py:65-67` `get_slot`: opptatt slot returnerer den LEVENDE inner-dicten,
   ledig slot returnerer fersk kopi. Asymmetrisk kontrakt. Dagens kallere (`sensor.py:58,63`)
   leser bare. [KJØRT: `get_slot(3) is coord._slots["3"]` == True; simulert muterende
   kaller korrumperer `_slots` stille — ulagret og uten listener-varsel — men `entry.options`
   forblir ren pga. ee9b2db.] Utløses av: enhver fremtidig kaller som skriver i returverdien.
2. `coordinator.py:76-78` `get_all_slots`: ytre dict kopieres, inner-dictene er levende.
   [KJØRT: `allslots["3"] is coord._slots["3"]` == True.] Null kallere i integrasjon OG
   tester (grep) — død offentlig API. Utløses kun hvis noen tar den i bruk og muterer.
3. `localize.py:70-74` strings-cache: samme dict-objekt deles per språk mellom alle
   entries, `coordinator.strings` og options flow. Ingen muterer i dag (grep: ingen
   `strings[...] =` i custom_components). [KJØRT: `s1 is s2` == True; én skrivning
   forgifter alle konsumenter i HA-instansen.] Utløses av første konsument som skriver.

Sjekket og friskmeldt (ikke engang mønster):
- `sensor.py:119-123` `extra_state_attributes` (aktivitet): fersk `dict(self._activity)`
  hver gang; `attrs.update(lock_capabilities)` kopierer int-verdier inn i den ferske dicten —
  ingen delt mutabel når HA. `read_lock_capabilities` (:142) muterer kun sin egen dict.
  Eneste anmerkning [RESONNERT]: capabilities som ankommer etter siste state-write vises
  først ved neste write (staleness, ikke aliasing).
- `sensor.py:147-153` `_activity`: erstattes atomisk, muteres aldri in-place, skalarverdier.
- `__init__.py:183-186` event-payload: fersk dict per event fra fersk `decoded` (:112-117),
  skalarverdier. Trygt.
- `DEFAULT_SLOT` (`const.py:51`): alle seks bruksstedene (coordinator.py:45,67,82,281,295,310)
  spread-kopierer `{**DEFAULT_SLOT}`; aldri tilordnet bar, og verdiene er immutable. Trygt.

## Del 3: Implementasjonsplan

Ikke påkrevd — ingen reelle bugs. Valgfri herding om mønstrene skal lukkes (klart merket
som herding, ikke feilretting):
- `coordinator.py`: `get_slot` -> `return {**DEFAULT_SLOT, **self._slots.get(str(slot), {})}`
  (alltid kopi, symmetrisk); `get_all_slots` slettes (død API) eller dypkopierer per slot.
- Test i `tests/test_coordinator_behavior.py` (gjenbruk selen): assert
  `coord.get_slot(3) is not coord._slots["3"]` etter `set_slot_name`, og at mutasjon av
  returverdien ikke lekker inn i `coord._slots` / `entry.options`.
- Ev. `localize.py`: returner `MappingProxyType(cache[lang])` — krever at ingen konsument
  forventer dict-API for skriving (ingen gjør det i dag).

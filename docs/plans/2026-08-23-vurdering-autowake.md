# Vurdering: auto-wake låser døren fysisk (dcat issues-11muex)

## Bekreftelse av funnet

Funnet stemmer. `_wake_lock()` i `custom_components/onesti_lock/coordinator.py` (linje 185–209)
kaller HA-tjenesten `lock.lock` på ZHA-lock-entiteten. Docstringen lyver: den sier
«sending a lock state read», men koden sender en fysisk låsekommando. Innført i commit
`d76e1fe` («fix: auto-wake + retry for PIN-setting»).

Når utløses wake (`_send_cluster_command`, linje 211–265):

- Kun ved `TimeoutError` på **første** forsøk av en ZCL-kommando: `set_pin` (0x0005),
  `clear_pin`/`clear_slot` (0x0007). Siden låsen sover mesteparten av tiden, er timeout
  på forsøk 1 normaltilfellet — wake kjøres altså ved nesten hver PIN-operasjon.
- Retry-løkken: 2 forsøk totalt. `IndexError` (Nimly-quirken) = suksess. Timeout på
  forsøk 2 = `False` + warning. Andre exceptions = `False` uten wake.
- `read_lock_capabilities()` (kjøres ved setup) leser attributter direkte på clusteret
  UTEN wake og degraderer stille ved timeout — integrasjonen har altså allerede et
  «les uten å vekke»-mønster, og erfaringen der er at det bare timer ut mot sovende lås.

## Mekanikken — kan noe annet enn en kommando «vekke» låsen?

Viktig presisering: **ingenting sendt over lufta vekker en sovende EndDevice.** Radioen
er av. Alt HA-siden kan gjøre er å legge en unicast i kø hos parent-routeren (TTL 7,68 s
per `docs/technical.md`) og håpe at låsen poller parent innenfor vinduet. Når låsen
mottar én frame, går den i fast-poll og henter flere ventende meldinger — det er dette
som ser ut som «vekking».

På MAC-nivå skiller indirekte levering IKKE mellom read og write: en
`read_attributes(lock_state)` køes hos parent på nøyaktig samme måte som en
lock-kommando. Hvis `lock.lock` empirisk virker bedre, skyldes det retry-/timeout-
konvolutten i ZHA/zigpy-stien for lock-entiteter (extended timeout for end devices +
gjentatte APS-forsøk som re-armerer 7,68-sekundersvinduet), ikke at det er en
skriveoperasjon. **Dette kan jeg ikke verifisere her**: zigpy er ikke installert i
miljøet og HA finnes ikke. At `lock.lock` «reliably wakes» er en empirisk observasjon
fra Fredriks egen testing (commit-loggen), ikke noe koden beviser. Om en read med samme
konvolutt er like pålitelig kan bare hardware avgjøre — eksperiment nedenfor.

## Alternativene

1. **Lese attributt (`lock_state`) via direkte cluster-tilgang** — mekanisk likeverdig
   i teorien (samme kø hos parent), men `read_lock_capabilities` viser at direkte reads
   i praksis timer ut. Usikkert om zigpy gir reads samme retry-konvolutt. Må testes.
2. **Annen ufarlig ZCL-kommando** — ingen god kandidat finnes. DoorLock-serverkommandoer
   er enten farlige (lock/unlock/toggle) eller PIN-relaterte (nettopp de som timer ut).
   Ingenting tyder på at kommando-vs-read er det som betyr noe.
3. **`homeassistant.update_entity` på lock-entiteten** — beste kandidat. Går til ZHA
   lock-entitetens `async_update` → `read_attributes(lock_state)` gjennom samme
   cluster-handler-sti som `lock.lock` bruker, altså samme transportkonvolutt, men uten
   fysisk bevegelse. Uverifisert mot ekte hardware.
4. **Behold + dokumenter** — null regresjonsrisiko, bieffekten består.
5. **Annet:**
   a. *Retry-only*: dropp wake helt, retry selve PIN-kommandoen 3–4 ganger. Hvis wake
      bare er transportmekanikk, er dette renest — meldingen som leveres ER
      PIN-kommandoen, og Nimly-quirken (IndexError) gir suksess-signal.
   b. *Betinget wake*: send `lock.lock` bare hvis HA-entitetens cachede tilstand
      allerede er `locked` (da er kommandoen no-op). Tilstanden er hendelsesdrevet
      (låsen rapporterer selv ved fysisk betjening, som vekker radioen), så den er
      som regel korrekt i akkurat det farlige tilfellet (ulåst/åpen dør).

**Å sjekke `lock_state` over Zigbee først er derimot samme runde med samme problem** —
en ny read mot en sovende enhet. Sjekken må gjøres mot HAs cachede entity-state, som er
gratis og øyeblikkelig. Forbeholdet: staten kan være stale etter batteribytte/mistet
rapportering; da feiler PIN-operasjonen med eksisterende `lock_unreachable`-melding,
som er en akseptabel feilmodus.

## Er det verre å låse en åpen dør enn å la PIN-operasjonen feile?

Ja. Låsing av åpen dør gir reile mot karm/luft, mulig skade når døren så lukkes mot
utkjørt reile, og en uventet fysisk aktuering brukeren aldri ba om. En feilet
PIN-operasjon er fullt gjenopprettbar: feilhåndteringen finnes allerede
(`lock_unreachable` i options-flowen med bevart input), og brukeren kan vekke låsen
selv. Sikkerhetsmessig feiler dagens mekanisme «trygt» (den låser, åpner aldri), men
mekanisk og UX-messig feiler den stygt.

Bimerknad: feilteksten «Trykk på keypadet og prøv igjen» er misvisende —
`docs/technical.md` sier eksplisitt at keypad-touch alene IKKE vekker radioen (kun
fullført PIN + #, eller fysisk vridning av knappen). Bør rettes samtidig.

## Anbefaling (todelt)

**A) Nå, uten hardware:** Dokumenter bieffekten (tekster nedenfor) i README og i
options-flowens `set_pin`- og `clear_pin`-beskrivelser, i alle fem JSON-filene.
Fiks samtidig den misvisende `_wake_lock`-docstringen og «trykk på keypadet»-teksten.

**B) Hardware-eksperiment som avgjør om mekanismen kan byttes:**

1. La låsen sove ≥5 min (ingen aktivitet, ZHA debug-logging på).
2. Kall `homeassistant.update_entity` på ZHA-lock-entiteten. Observer om entiteten
   faktisk oppdateres / read-svar kommer i loggen — det beviser levert frame.
3. Umiddelbart etterpå: `set_pin` fra options-flowen. Lykkes forsøk 1?
4. Gjenta 10 runder. Sammenlign suksessrate med 10 kontrollrunder med dagens
   `lock.lock`-wake.
5. Test også retry-only: gjør `_wake_lock` midlertidig til no-op, øk attempts til 3–4.
   Lykkes `set_pin` uten noen wake?

Suksesskriterium: minst samme suksessrate som dagens mekanisme, ingen fysisk bevegelse.
- Hvis update_entity-wake (eller retry-only) består → bytt `_wake_lock` til den.
- Hvis ikke → behold `lock.lock`, men legg inn betinget wake (kun når cached state er
  `locked`). Det gjør PIN-operasjon mot ulåst sovende lås til en tydelig feil i stedet
  for en overraskende fysisk låsing — det er riktig bytte.

**Kost/brudd:** Dokumentasjon bryter ingenting. Bytte av wake-mekanisme risikerer at
PIN-operasjoner blir upålitelige hos brukere med annen parent-router/poll-oppsett enn
testmiljøet — derfor hardware-test først, og vurder to-trinns wake (read først,
`lock.lock` som siste fallback) i en overgangsversjon. Betinget wake er en bevisst
funksjonell regresjon for tilfellet «dør lukket men ulåst» (i dag lykkes PIN-op via
uønsket låsing; etterpå feiler den med beskjed) — det er dokumenterbart og forsvarlig.

## Tekster som skal inn (leveres ferdig, uansett utfall av eksperimentet)

### README.md — erstatt punkt 3 under «Limitations»

> 3. **Sleepy device** — the lock sleeps aggressively to save battery. Commands may
> timeout on first attempt. The integration auto-wakes and retries — but note that the
> auto-wake works by sending a **lock command** to the lock. If the door is unlocked
> when you set or clear a PIN, the door will physically lock; if the door is standing
> open, the bolt is driven out into the air. Close the door before managing PIN codes,
> or wake the lock yourself first by turning the thumb-turn. Also place a Zigbee router
> right next to the door — the metal casing acts as a Faraday cage.

### Options-flow: tillegg i `set_pin.description` (etter eksisterende tekst)

- **strings.json + translations/en.json:**
  "Note: if the lock is asleep, the first attempt times out and the integration wakes
  the lock by sending a lock command. If the door is unlocked it will be physically
  locked — close the door before you start."
- **translations/nb.json:**
  "Merk: hvis låsen sover, tidsavbrytes første forsøk og integrasjonen vekker låsen
  ved å sende en låsekommando. Er døren ulåst, blir den fysisk låst — lukk døren før
  du starter."
- **translations/sv.json:**
  "Obs: om låset sover får första försöket timeout och integrationen väcker låset
  genom att skicka ett låskommando. Är dörren olåst blir den fysiskt låst — stäng
  dörren innan du börjar."
- **translations/da.json:**
  "Bemærk: hvis låsen sover, får første forsøg timeout, og integrationen vækker låsen
  ved at sende en låsekommando. Er døren ulåst, bliver den fysisk låst — luk døren,
  før du starter."

### Options-flow: tillegg i `clear_pin.description`

- **strings.json + en:** "If the lock is asleep, the integration wakes it by sending a
  lock command — an unlocked door will be physically locked."
- **nb:** "Hvis låsen sover, vekker integrasjonen den ved å sende en låsekommando —
  en ulåst dør blir fysisk låst."
- **sv:** "Om låset sover väcker integrationen det genom att skicka ett låskommando —
  en olåst dörr blir fysiskt låst."
- **da:** "Hvis låsen sover, vækker integrationen den ved at sende en låsekommando —
  en ulåst dør bliver fysisk låst."

Husk gotcha 7 i AGENTS.md: `strings.json` skal være identisk med `translations/en.json`,
og `tests/test_no_hardcoded_language.py` vokter norske literaler i Python.

### Kritiske filer

- /Users/fredrik/dev/privat/hacs-onesti/custom_components/onesti_lock/coordinator.py
- /Users/fredrik/dev/privat/hacs-onesti/custom_components/onesti_lock/strings.json
- /Users/fredrik/dev/privat/hacs-onesti/custom_components/onesti_lock/translations/nb.json (+ en/sv/da)
- /Users/fredrik/dev/privat/hacs-onesti/README.md
- /Users/fredrik/dev/privat/hacs-onesti/docs/technical.md

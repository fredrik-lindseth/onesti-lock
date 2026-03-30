# Options Flow UX — PIN-setting med progress og feilhåndtering

Løser issues-s88brd (Unknown error) og issues-uzg85d (bedre UX).

## Problem

1. Ubehandlede exceptions i options flow propagerer og viser "Unknown error"
2. Brukeren mister all input ved feil og må starte på nytt
3. Ingen visuell feedback mens PIN-kommando sendes (10-30 sek)
4. Brukeren må "huske å vekke låsen først"

## Løsning

### async_show_progress for PIN-operasjoner

HA sitt `async_show_progress()` / `async_show_progress_done()` mønster gir spinner
med tekst mens bakgrunnsoppgaven kjører. Brukes i options flow for set_pin og clear_pin.

### Flyt: Sett PIN

```
Meny → Sett PIN (form) → [Submit] → Spinner: "Sender PIN-kode..."
                                          ↓ suksess        ↓ feil
                                     create_entry     Tilbake til form
                                                      (pre-fylt, med feilmelding)
```

### Flyt: Fjern PIN

```
Meny → Fjern PIN (form) → [Submit] → Spinner: "Fjerner PIN-kode..."
                                           ↓ suksess        ↓ feil
                                      create_entry     Tilbake til form
                                                       (med feilmelding)
```

### Steg i options flow

**set_pin:**
1. `async_step_set_pin` — viser form, validerer input, lagrer user_input, starter task
2. `async_step_set_pin_progress` — viser spinner via async_show_progress, sjekker task
3. Ved task done: async_show_progress_done → `async_step_set_pin_result`
4. `async_step_set_pin_result` — suksess → create_entry, feil → tilbake til set_pin med errors

**clear_pin:**
Samme mønster med `clear_pin_progress` og `clear_pin_result`.

### Feilhåndtering

- Wrap all coordinator-kall i try/except
- TimeoutError → `errors["base"] = "lock_unreachable"`
- Exception → `errors["base"] = "unknown"`, logg traceback
- Aldri la exceptions propagere fra flow steps

### Form-data bevaring

Bruk `add_suggested_values_to_schema()` for å pre-fylle slot, navn og kode ved retry.
Fjern "Husk å vekke låsen først!" fra descriptions — auto-wake håndterer det.

### Nye/endrede strings.json

```json
"progress": {
  "set_pin_progress": "Sender PIN-kode til låsen...",
  "clear_pin_progress": "Fjerner PIN-kode fra låsen..."
},
"error": {
  "invalid_pin": "PIN-kode må være 4-8 siffer",
  "lock_unreachable": "Kunne ikke nå låsen. Trykk på keypadet og prøv igjen.",
  "unknown": "En uventet feil oppstod. Sjekk loggene."
}
```

## Implementasjonsplan

### 1. config_flow.py — refaktorer set_pin med progress

- Legg til instansvariabler: `_set_pin_task`, `_set_pin_input`, `_set_pin_error`
- `async_step_set_pin`: validerer input → lagrer i self → starter task → ruter til progress
- `async_step_set_pin_progress`: async_show_progress med progress_task
- `async_step_set_pin_result`: sjekker task-resultat, ruter til create_entry eller tilbake til form
- Bevar form-data med add_suggested_values_to_schema ved feil

### 2. config_flow.py — refaktorer clear_pin med progress

Samme mønster som set_pin.

### 3. strings.json — oppdater

- Legg til progress-strenger
- Legg til "unknown" error
- Fjern "Husk å vekke låsen først!" fra descriptions

### 4. Tester

- Test at timeout gir "lock_unreachable" feilmelding (ikke "Unknown error")
- Test at uventet exception gir "unknown" feilmelding
- Test at form-data bevares ved feil

---
description: Fullfør issue fra beads (Home Assistant)
---

1. **Sjekk klar arbeid**: `bd ready` viser ublokkerte issues
2. **Claim task**: `bd update <id> --status in_progress`
3. **Code style**: Les @AGENTS.md for HA regler
4. **Implementer**: Jobb kun med valgt oppgave
5. **Oppdag nytt arbeid?** Opprett lenket issue:
   - `bd create "Funnet bug" --description="Detaljer" -p 1 --deps discovered-from:<parent-id>`
6. **Kvalitetssjekk** (HA spesifikt):
   - `ruff check` - Linting og format
   - `ruff format` - Kodeformatering
   - Test med nyeste Home Assistant versjon
   - Sjekk logger for errors/warnings
7. **Før fullføring**: Kall reviewer sub-agent for å sjekke arbeidet
8. **Oppdater AGENTS.md** hvis du finner gjenbrukbare mønstre
9. **Commit** med norsk melding: `[issue_type]: [Issue ID] - [Issue Title]`
10. **Fullfør**: `bd close <id> --reason "Completed"`

## Home Assistant Spesifikke Regler

- Følg HA custom integration best practices
- Bruk ruff for linting og formatering
- Skriv enhetstester med pytest
- Oppdater manifest.json ved versjonsendring
- Test med nyeste HA versjon
- Følg HACS guidelines for publisering
- Bruk SSH for testing: `scp *.py ha-local:/config/custom_components/nimly_pro/`

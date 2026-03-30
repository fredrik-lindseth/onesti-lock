
## Nye funn fra white-label dekompilering (2026-03-30)

Dekompilerte alle white-label apper i iotiliti-økosystemet. Iotiliti-basen (io.iotiliti.home) har en nyere versjon med oppdaterte API-URLer.

### Oppdaterte API-URLer (fra iotiliti-appen)

Nimly Connect v1.27.84 bruker `api-neutralclone.iotiliti.cloud`, men nyere versjoner har migrert til:

| Merke | Prod API URL | Test API URL | Client Secret |
|-------|-------------|-------------|---------------|
| **Nimly** | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | `test-api-neutralclone.iotiliti.cloud` | `<client-secret>` |
| **Homely** | `api.homely.no` | `test-api-homely.iotiliti.cloud` | `<client-secret>` |
| **Keyfree** | `api.customer.keyfree.iotiliti.cloud` | `test-api-keyfree.iotiliti.cloud` | `<client-secret>` |
| **Forebygg** | `api.customer.forebygg.iotiliti.cloud` | `test-api-forebygg.iotiliti.cloud` | `<client-secret>` |
| **Safe4 Care** | `api-safe4care.iotiliti.cloud` | `test-api-safe4care.iotiliti.cloud` | `<client-secret>` |
| **Tryg Smart** | `api.tryg.iotiliti.cloud` | `test-api-tryg.iotiliti.cloud` | `<client-secret>` |
| **Salus** | `api-salus.iotiliti.cloud` | `test-api-salus.iotiliti.cloud` | `<client-secret>` |
| **LF** | `api-lf.iotiliti.cloud` | `test-api-lf.iotiliti.cloud` | `<client-secret>` |
| **Copiax** | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | (delt) | `<client-secret>` |
| **Tekam** | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | (delt) | `<client-secret>` |
| **Folklarm** | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | (delt) | `<client-secret>` |

### Intern test-URL

`https://test-api-neurosys.iotiliti.cloud` — intern Neurosys (utviklerselskap) test-API med egen client_secret `<client-secret>`.

### Developer Options (skjult)

Appen har en skjult "Developer Options"-meny med:
- Bytt mellom Production/Test/Internal API
- Enable Instabug (feilrapportering)
- Copy Device Token
- Enable Error Reports

### LF-instans (interessant avvik)

LF-merket bruker en helt separat Keycloak-realm: `realms/lftt-kong-oidc/protocol/openid-connect/token`.
Ekstern auth via `https://test-auth.lfhub.net` med `clientId: 'kong-oidc'`, `clientSecret: '<client-secret>'`.
Bruker username-login (ikke email), ingen passordbytte, ingen kontosletting.

### Bekreftet: group-devices er tom på begge APIer

Testet med fersk token mot både `api-neutralclone.iotiliti.cloud` og `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` — begge returnerer `[]` for group-devices. Delt database, ingen forskjell i respons.

### Konklusjon

Alle white-label apper deler samme kodebase og endepunkter. Prod-API har migrert fra `api-neutralclone.iotiliti.cloud` til `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` for de fleste merker. `group-devices` returnerer `[]` uavhengig av URL — problemet er sannsynligvis i server-side tilgangskontroll eller at devicene aldri ble registrert korrekt i cloud API.

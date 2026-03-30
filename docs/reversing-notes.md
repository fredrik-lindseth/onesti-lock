
## Nye funn fra white-label dekompilering (2026-03-30)

Dekompilerte alle white-label apper i iotiliti-økosystemet. Iotiliti-basen (io.iotiliti.home) har en nyere versjon med oppdaterte API-URLer.

### Oppdaterte API-URLer (fra iotiliti-appen)

Nimly Connect v1.27.84 bruker `api-neutralclone.iotiliti.cloud`, men nyere versjoner har migrert til:

| Merke | Prod API URL | Test API URL | Client Secret |
|-------|-------------|-------------|---------------|
| **Nimly** | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | `test-api-neutralclone.iotiliti.cloud` | `55c78905-7601-48fa-b589-2d15c4ad60e7` |
| **Homely** | `api.homely.no` | `test-api-homely.iotiliti.cloud` | `71fb00d6-ad04-43ca-96f4-fb797259da65` |
| **Keyfree** | `api.customer.keyfree.iotiliti.cloud` | `test-api-keyfree.iotiliti.cloud` | `e1428615-350f-4762-b3ec-02a36402603c` |
| **Forebygg** | `api.customer.forebygg.iotiliti.cloud` | `test-api-forebygg.iotiliti.cloud` | `ac252b25-995c-4bee-ac18-97812e16fc88` |
| **Safe4 Care** | `api-safe4care.iotiliti.cloud` | `test-api-safe4care.iotiliti.cloud` | `5DCevi7ncs7n2cbl9NCeEEetlM7ImWej` |
| **Tryg Smart** | `api.tryg.iotiliti.cloud` | `test-api-tryg.iotiliti.cloud` | `9b88cb32-9595-4cf5-b245-c9de139ce03e` |
| **Salus** | `api-salus.iotiliti.cloud` | `test-api-salus.iotiliti.cloud` | `24fc232a-2f9c-4de1-9d89-b8ca4c5225c9` |
| **LF** | `api-lf.iotiliti.cloud` | `test-api-lf.iotiliti.cloud` | `ad9c3162-7ad5-49c6-bbe6-d9b868cd0f1c` |
| **Copiax** | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | (delt) | `55c78905-7601-48fa-b589-2d15c4ad60e7` |
| **Tekam** | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | (delt) | `55c78905-7601-48fa-b589-2d15c4ad60e7` |
| **Folklarm** | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | (delt) | `55c78905-7601-48fa-b589-2d15c4ad60e7` |

### Intern test-URL

`https://test-api-neurosys.iotiliti.cloud` — intern Neurosys (utviklerselskap) test-API med egen client_secret `fde2ad9f-f55b-4ed4-9a01-ddb0421c5efa`.

### Developer Options (skjult)

Appen har en skjult "Developer Options"-meny med:
- Bytt mellom Production/Test/Internal API
- Enable Instabug (feilrapportering)
- Copy Device Token
- Enable Error Reports

### LF-instans (interessant avvik)

LF-merket bruker en helt separat Keycloak-realm: `realms/lftt-kong-oidc/protocol/openid-connect/token`.
Ekstern auth via `https://test-auth.lfhub.net` med `clientId: 'kong-oidc'`, `clientSecret: 'IoJFWmQRIYHKDX9bzEW0mxVaQqHKZE4I'`.
Bruker username-login (ikke email), ingen passordbytte, ingen kontosletting.

### Bekreftet: group-devices er tom på begge APIer

Testet med fersk token mot både `api-neutralclone.iotiliti.cloud` og `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` — begge returnerer `[]` for group-devices. Delt database, ingen forskjell i respons.

### Konklusjon

Alle white-label apper deler samme kodebase og endepunkter. Prod-API har migrert fra `api-neutralclone.iotiliti.cloud` til `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` for de fleste merker. `group-devices` returnerer `[]` uavhengig av URL — problemet er sannsynligvis i server-side tilgangskontroll eller at devicene aldri ble registrert korrekt i cloud API.

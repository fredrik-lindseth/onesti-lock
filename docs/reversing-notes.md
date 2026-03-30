# Nimly Connect App — Reverse Engineering Notes

APK: `com.easyaccess.connect` v1.27.84
Framework: React Native med Hermes bytecode
Dekompilert med: `jadx` + `hermes-dec`

## Cloud API

Appen kommuniserer med `iotiliti.cloud` — en felles plattform for flere låsmerker:

### Nimly / EasyAccess ("neutralclone")
```
API_URL: https://api-neutralclone.iotiliti.cloud
API_CLIENT_SECRET: <extracted-from-apk, see secrets.md>
TEST_API_URL: https://test-api-neutralclone.iotiliti.cloud
TEST_API_CLIENT_SECRET: 904dfbcb-61d2-48db-ae68-55af64d2472a
COMPANY_ID: 90ded287-2356-4007-ac39-d3e1261afb59
```

### Keyfree (annet merke, samme plattform)
```
API_URL: https://api-keyfree.iotiliti.cloud
API_CLIENT_SECRET: e1428615-350f-4762-b3ec-02a36402603c
COMPANY_ID: b960e7e6-02bd-490b-8c90-e6c428c45eea
```

### Andre merker på samme plattform
- `api-salus.iotiliti.cloud` — Salus
- `test-api-neurosys.iotiliti.cloud` — Neurosys (intern)
- `test-key-cloud-neutralclone.iotiliti.cloud/mobile`

## Doorlock events (fra JS-kode)

```javascript
'doorlock-settings-changed'
'doorlock-access-created'
'doorlock-access-scan-requested'
'doorlock-access-deleted'
'doorlock-failed-to-lock'
'doorlock-access-updated'
```

## App-konfigurasjon (Nimly-spesifikt)

```javascript
{
  safeUnlockEnabled: true,
  amsServiceEnabled: true,          // Access Management System
  fireAlarmWidgetEnabled: false,
  hasMultipleEms: true,             // Multiple External Management Systems
  isPrivateAccessTypeValidInAms: true,
  showUserForFingerprintEvents: false,  // ← Interessant!
  keypadAsAccessDeviceEnabled: true,
  fontFamily: 'Stabil Grotesk',
  installationPartnerCountryListEnabled: true,
}
```

`showUserForFingerprintEvents: false` — Nimly-konfigurasjonen skjuler bruker for fingeravtrykk-events!

## Support-telefonnumre

```javascript
{
  homely: '815 69049',
  tekam: '815 69049',
  iotiliti: '21931814',
  eidsiva: '815 69049',
  forebygg: '0770 337 332',
  salus: '0844 8712223'
}
```

## Neste steg

1. **Utforske API-et** — `https://api-neutralclone.iotiliti.cloud` med client secret kan gi oss REST-endepunkter for PIN-administrasjon
2. **Finne BLE-protokoll** — appen snakker BLE med låsen for PIN-setting (raskere enn Zigbee)
3. **Event stream** — `/v1/apps/{ApplicationId}/eventstream` kan gi real-time events
4. **Grave i addCode-funksjonen** — finne den faktiske PIN-setting logikken

## Verktøy brukt

- `apkeep` — APK-nedlasting fra Play Store
- `jadx` — Android APK dekompilering
- `hermes-dec` — React Native Hermes bytecode → JavaScript

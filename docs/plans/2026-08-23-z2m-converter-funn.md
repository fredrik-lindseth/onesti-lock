# Funn i Zigbee2MQTT-converteren for Onesti/Nimly

Dato: 2026-08-23. Grunnlag: `src/devices/onesti.ts` på `master` i
`Koenkk/zigbee-herdsman-converters`, hentet 2026-08-23. Linjenumre i dette
dokumentet viser til den filen slik den var da, 266 linjer totalt. Sjekk dem på
nytt før PR-en skrives, filen er liten og flytter seg.

```bash
curl -sL https://raw.githubusercontent.com/Koenkk/zigbee-herdsman-converters/master/src/devices/onesti.ts
```

Alt under er lest ut av kode. Ingenting er testet mot maskinvare i denne runden.
Der en påstand bygger på resonnement framfor en capture, står det uttrykkelig.

## Kort oppsummert

Sju funn. To av dem er nye siden `docs/upstream-status.md` ble skrevet, og et av
de nye er større enn alle de andre: hele kapabilitetsblokken i converteren
(`max_pin_users`, `min_pin_length`, `max_pin_length`) er død kode som aldri kan
kjøre, og navnene er dessuten byttet om.

| #   | Funn                                                     | Alvor     | Status i upstream-status.md |
| --- | -------------------------------------------------------- | --------- | --------------------------- |
| 1   | `last_used_pin_code` antar ASCII, NimlyPRO sender BCD    | Feil verdi | Kjent                       |
| 2   | Kilde `0x05` mangler i oppslaget                         | Feil verdi | Kjent                       |
| 3   | `0x0a` heter `self`, ikke `auto`                         | Navngiving | Kjent                       |
| 4   | `result` er en lokal variabel som aldri returneres       | Kosmetisk  | Kjent                       |
| 5   | Attributt 18/23/24 leses på numerisk nøkkel, som aldri finnes | Død kode | **Nytt**               |
| 6   | 23 og 24 er dessuten byttet om mot ZCL                   | Feil verdi | **Nytt**                    |
| 7   | `voltage`-grenen i converteren er død, verdien kommer fra `fz.battery` | Død kode | **Nytt**       |

Byterekkefølge og slotbredde er kontrollert og er **riktige**. Modellisten er
kontrollert og er **komplett** mot vår `SUPPORTED_MODELS`. Ingen av de to er
funn.

## Ingenting av dette er meldt oppstrøms

Søk 2026-08-23 med `gh` i `Koenkk/zigbee-herdsman-converters` og
`Koenkk/zigbee2mqtt` på onesti, nimly, easyCodeTouch og `last_used_pin_code`.

Ingen åpne PR-er berører `src/devices/onesti.ts`. Ingen åpne issues beskriver
noen av de sju funnene.

Relevant historikk:

- **PR 11332**, «Fix PIN code parsing and user tracking for Nimly/Onesti locks»,
  merget 2026-01-18 av markus-lassfolk. Denne la inn hele blokken vi nå finner
  feil i: ASCII-antakelsen for PIN, `voltage`, `auto_relock_time` og de tre
  kapabilitetsattributtene. Beskrivelsen sier «Tested on multiple Nimly NimlyPRO
  locks». Se avsnittet om PIN under, den testingen forklarer hvorfor forfatteren
  så ASCII.
- **PR 11874**, «Add support for Nimly Code Pro smart lock», merget 2026-04-05
  av robin-wallberg. Én linje: `NimlyCodePRO` lagt i `zigbeeModel`. Ingenting
  ble gjort med kildeoppslaget, som er grunnen til at funn 2 finnes.
- **Issue 32469** i `Koenkk/zigbee2mqtt`, åpen siden 2026-07-02: Nimly viser 200
  % batteri. Det handler om `meta: {battery: {dontDividePercentage: true}}` på
  linje 147 og 204, altså en firmwaresplitt vi ikke kan avgjøre uten flere
  enheter. **Ikke rør dette i vår PR.** Det er nevnt her bare så neste økt ikke
  blir dratt inn i det.

## Funn 1: PIN-en publiseres som søppel på NimlyPRO

Linje 33 til 52:

```ts
// Handle attribute 257: last_used_pin_code
// The lock sends PIN codes as the actual digits typed
// Report exactly what the lock sends
if (msg.data["257"] !== undefined) {
    const data = msg.data["257"];

    if (Buffer.isBuffer(data)) {
        // Convert buffer to ASCII string
        attributes.last_used_pin_code = data.toString("ascii").trim();
    } else if (Array.isArray(data)) {
        // Array of bytes, convert to ASCII string
        attributes.last_used_pin_code = Buffer.from(data).toString("ascii").trim();
    } else if (typeof data === "string") {
        ...
```

Attributt `0x0101` er OCTET_STR (type `0x41`), så zigbee-herdsman leverer en
`Buffer`. Første gren treffer.

Vår capture i `docs/zigbee-protocol/zigbee-captures.md` viser PIN «5478» på
NimlyPRO som `b"\x54\x78"`, to bytes for fire sifre, altså pakket BCD. Kjørt
gjennom converteren:

```
Buffer.from([0x54, 0x78]).toString("ascii")  ->  "Tx"
```

Flere eksempler, regnet ut med node:

| PIN    | BCD-bytes   | Publisert `last_used_pin_code` |
| ------ | ----------- | ------------------------------ |
| 1234   | `12 34`     | `"\x124"`, altså 0x12 og `4`   |
| 5478   | `54 78`     | `"Tx"`                         |
| 9999   | `99 99`     | `"\x19\x19"`, to kontrolltegn |
| 0000   | `00 00`     | `"\x00\x00"`, to nullbytes    |
| 123456 | `12 34 56`  | `"\x124V"`                    |

Merk at Node sin `ascii`-koding maskerer bort høyeste bit, så `0x99` blir
`0x19`. Verdien er ubrukelig: den er ikke PIN-en, den er ikke stabil, og for
flere PIN-er er den kontrolltegn som havner escapet i MQTT-payloaden og videre
inn i en HA-tekstentitet.

**Hvorfor PR 11332 så noe annet.** Beskrivelsen viser før-og-etter:

```
Before: last_used_pin_code: "313131313131"  (hex-doubled, unusable)
After:  last_used_pin_code: "141141"        (actual digits typed)
```

`313131313131` er hex av ASCII `111111`. På den forfatterens lås kom PIN-en
altså som seks ASCII-bytes, ikke som tre BCD-bytes. Begge formatene finnes i
felt. Vår egen fjernede `_decode_pin_code` (commit `57ed320`, se
`git show 57ed320 -- custom_components/onesti_lock/__init__.py`) håndterte
begge, med akkurat den begrunnelsen i docstringen, og pekte selv på PR 11332
som ASCII-kilden.

Dette er ikke en sikkerhetssak. En firesifret dørkode er ikke særlig sensitiv,
og converteren skal fortsette å eksponere feltet. Saken er at feltet i dag
publiserer feil verdi på den vanligste modellen.

**Fiksen.** Kjenn igjen formatet i stedet for å anta. To signaler, i denne
rekkefølgen:

1. **Lengde.** En PIN på N sifre er N bytes i ASCII og `ceil(N / 2)` bytes i
   BCD. NimlyPRO rapporterer `minPinLen` = 4 (verifisert live, se vår commit
   `8256a83`), så en buffer på 2 bytes kan ikke være en ASCII-PIN. Er `minPinLen`
   ikke kjent, hopp til punkt 2.
2. **Byteverdier.** Er hver byte i `0x30`-`0x39`, er det ASCII-sifre. Ellers
   pakk ut nibbler, og krev at hver nibble er 0-9, hvis ikke er dataen noe annet
   og bør ikke publiseres.

Heuristikken er ikke vanntett alene: BCD-PIN-en «3939» er bytene `0x39 0x39`,
som også ser ut som ASCII «99». Lengdesjekken mot `minPinLen` løser akkurat den.
Skriv i kommentaren at ambiguiteten er kjent og hvorfor lengden går først.

Stripp også etterfølgende `0x00` før tolking. `String.prototype.trim()` fjerner
whitespace, men ikke NUL, så dagens `.trim()` slipper nullbytes rett gjennom.

## Funn 2 og 3: kildeoppslaget

Linje 62 til 69:

```ts
const lookup: {[key: string]: string} = {
    "00": "zigbee",
    "02": "keypad",
    "03": "fingerprintsensor",
    "04": "rfid",
    "0a": "self",
};
result.last_action_source = lookup[firstOctet] || "unknown";
```

`0x05` mangler. NimlyCodePRO (fw 4.8.02) sender `0x05` for Zigbee-kommando,
auto-relåsing og innvendig tastatur, alltid med brukerslot 0, payload
`0x05010000`. Kilden er supersej i
[zha-device-handlers#4881](https://github.com/zigpy/zha-device-handlers/pull/4881),
gjengitt i vår `docs/zigbee-protocol/zigbee-captures.md`. Modellen har vært i
converteren siden PR 11874 i april, så Z2M rapporterer i dag `unknown` for
alle hverdagsoperasjoner på den låsen.

Vi kaller `0x05` for `unattributed`, nettopp fordi payloaden ikke kan skille de
tre fra hverandre. Bruk samme navn oppstrøms, ellers får de to prosjektene ulike
navn på samme byte.

`0x0a` heter `self`. Vi kaller den `auto`, og det er også det ZHA-quirken vår PR
retter til. `self` sier ingenting om at det er auto-relåsing.

**Vær klar over at et navnebytte er brekkende for Z2M-brukere.** `last_lock_source`
er en `enum`-expose, verdiene havner rett i automasjoner og i HA-tilstander. Z2M
har ingen deprecation-mekanisme for enum-verdier. Vurder å la `self` stå og bare
legge til `0x05`, eller å skille navnebyttet ut som eget punkt i PR-teksten så
Koenkk kan si nei til det uten å ta ned resten. Se «Deling av PR-er» nederst.

Legges `0x05` inn, må `unattributed` også inn i begge enum-listene, altså linje
172, 176, 220 og 224. Ellers avviser Z2M verdien mot expose-definisjonen.

## Funn 4: `result` returneres aldri

Linje 30 deklarerer den, linje 69 og 72 skriver til den, linje 75, 79 og 82
leser fra den, og linje 113 til 115 returnerer `attributes`:

```ts
if (Object.keys(attributes).length > 0) {
    return attributes;
}
```

`result` er altså bare en mellomlagring med et misvisende navn. Ingen `last_action_source`
eller `last_action_user` når MQTT. Informasjonen kommer fram, under navnene
`last_lock_source`, `last_unlock_source`, `last_lock_user` og `last_unlock_user`
(linje 77 til 83). Rent kosmetisk, men det får converteren til å lese som om det
finnes to felter som ikke finnes. Erstatt `result` med to lokale variabler.

## Funn 5: kapabilitetsattributtene leses på en nøkkel som aldri finnes

Dette er det største funnet, og det er nytt.

Linje 96 til 110:

```ts
// Handle lock capabilities (if present)
// Attribute 18 (0x12): Number of PIN users supported
if (Object.hasOwn(msg.data, 18)) {
    attributes.max_pin_users = (msg.data as KeyValue)[18];
}

// Attribute 23 (0x17): Min PIN code length
if (Object.hasOwn(msg.data, 23)) {
    attributes.min_pin_length = (msg.data as KeyValue)[23];
}

// Attribute 24 (0x18): Max PIN code length
if (Object.hasOwn(msg.data, 24)) {
    attributes.max_pin_length = (msg.data as KeyValue)[24];
}
```

`msg.data` bygges av `ZclFrameConverter.attributeKeyValue` i zigbee-herdsman
(`src/controller/helpers/zclFrameConverter.ts`). Den slår opp hver `attrId` med
`Zcl.Utils.getClusterAttribute` og bruker **attributtnavnet** som nøkkel når
attributtet finnes i clusterdefinisjonen. Bare ukjente attributter faller
tilbake på det numeriske ID-et:

```ts
const attribute = Zcl.Utils.getClusterAttribute(cluster, item.attrId, manufacturerCode);

if (attribute) {
    ...
    payload[attribute.name] = attrData;
} else {
    payload[item.attrId] = item.attrData;
}
```

Alle tre er standardattributter i `closuresDoorLock`
(`src/zspec/zcl/definition/cluster.ts`):

```ts
numOfPinUsersSupported: {name: "numOfPinUsersSupported", ID: 0x0012, type: DataType.UINT16, default: 0},
maxPinLen: {name: "maxPinLen", ID: 0x0017, type: DataType.UINT8, default: 8},
minPinLen: {name: "minPinLen", ID: 0x0018, type: DataType.UINT8, default: 4},
```

Nøklene blir altså `numOfPinUsersSupported`, `maxPinLen` og `minPinLen`.
`Object.hasOwn(msg.data, 18)` er alltid usant. De tre exposene på linje 182 til
184 og 230 til 232 får aldri en verdi.

Det forklarer også hvorfor `256` og `257` faktisk virker: de er *ikke* i
clusterdefinisjonen, så de faller ned i `else`-grenen og blir numeriske nøkler.
Converteren gjør riktig for de to og feil for de tre andre, i samme funksjon.

Reservasjon: dette er lest ut av zigbee-herdsman, ikke observert på en kjørende
Z2M. Det er lett å bekrefte i en test, se testavsnittet.

**Fiksen.** Bytt til attributtnavn, samme mønster som `autoRelockTime` på linje
92 til 94 allerede bruker riktig:

```ts
if (Object.hasOwn(msg.data, "numOfPinUsersSupported")) { ... }
if (Object.hasOwn(msg.data, "maxPinLen")) { ... }
if (Object.hasOwn(msg.data, "minPinLen")) { ... }
```

**Bonusfunn i samme område:** `configure` på Nimly-definisjonen (linje 205 til
213) leser aldri kapabilitetene i det hele tatt. Bare easyCodeTouch gjør det,
linje 155 til 161. Selv med riktige nøkler ville Nimly-låser først fått verdiene
hvis låsen selv rapporterte dem uoppfordret. Legg samme `try`-blokk inn i
Nimly sin `configure`.

## Funn 6: 23 og 24 er byttet om

Samme kodeblokk. Kommentarene sier «Attribute 23 (0x17): Min PIN code length» og
«Attribute 24 (0x18): Max PIN code length». ZCL sier det motsatte, og
zigbee-herdsman sin egen definisjon sier det motsatte, se sitatet over:
`maxPinLen` er `0x0017`, `minPinLen` er `0x0018`.

Vi hadde nøyaktig samme feil og rettet den i commit `8256a83`, verifisert live
mot en NimlyPRO: `0x0017` returnerer 8, `0x0018` returnerer 4. Firmwaren er
riktig, mappingen var snudd.

Funn 5 og 6 fikses i samme håndgrep, siden riktige navn gjør ombyttingen umulig
å gjøre igjen.

Navngivingen bør også ryddes mens man er der: `max_pin_users` er antall
slots, ikke et maksimum for noe. ZCL kaller det `NumberOfPINUsersSupported`, og
vi kaller det `num_pin_users` etter samme opprydding. Men dette er et
expose-navn, altså brekkende for brukere på samme måte som `self` til `auto`.
Siden feltet **aldri har hatt en verdi** (funn 5), er det ingen som har en
automasjon på det, så her er omdøpingen gratis. Det argumentet bør stå i
PR-teksten.

## Funn 7: `voltage`-grenen er død

Linje 87 til 89:

```ts
if (Object.hasOwn(msg.data, "voltage")) {
    attributes.voltage = (msg.data as KeyValue)["voltage"];
}
```

`nimly_pro_lock_actions` er registrert på `cluster: "closuresDoorLock"` (linje
27). `closuresDoorLock` har ikke noe attributt som heter `voltage`.
Batterispenning ligger på `genPowerCfg` som `batteryVoltage`, og `fz.battery`
(`src/converters/fromZigbee.ts` linje 446 til 448) publiserer den som `voltage`:

```ts
if (msg.data.batteryVoltage !== undefined && msg.data.batteryVoltage < 255) {
    // Deprecated: voltage is = mV now but should be V
    payload.voltage = msg.data.batteryVoltage * 100;
```

`fz.battery` står i `fromZigbee` på begge definisjonene (linje 142 og 199), så
`e.voltage()` fungerer. Grenen i `nimly_pro_lock_actions` er bare død kode fra
PR 11332. Slett den. Ingen bruker mister noe.

## Det som er kontrollert og er riktig

Ta ikke opp dette i PR-en, det er bare notert så neste økt slipper å gjøre
arbeidet på nytt.

**Byterekkefølge og slotbredde stemmer.** Linje 60 til 72 gjør
`(msg.data["256"] as number).toString(16).padStart(8, "0")`, altså en
big-endian-heksstreng av 32-bitstallet. Da er `substring(0, 2)` bits 24-31
(kilde), `substring(2, 4)` bits 16-23 (handling), og `substring(4, 8)` bits 0-15
(slot, 16 bit). Det er nøyaktig det samme som vår `_decode_operation_event`:

```python
user_slot = val & 0xFFFF
action = _ACTION_MAP.get((val >> 16) & 0xFF, ACTION_UNKNOWN)
source = _SOURCE_MAP.get((val >> 24) & 0xFF, SOURCE_UNKNOWN)
```

Kommentaren på linje 56 til 58 («Byte 0: Source ... Bytes 2-3: User ID») er
riktig om posisjoner i heksstrengen, men leses lett som byteposisjoner på tråden,
der rekkefølgen er motsatt (little-endian). Rett gjerne kommentaren i farten, men
koden er riktig.

Merk at 16-bitsbredden ikke er bekreftet av noen capture, verken hos oss eller
oppstrøms. Ingen observert slot har oversteget 255. Ikke fremstill det som
verifisert i PR-en.

**Modellisten er komplett.** Converteren dekker `easyCodeTouch_v1`,
`EasyCodeTouch`, `EasyFingerTouch` (linje 133) og `NimlyPRO`, `NimlyCode`,
`NimlyTouch`, `NimlyIn`, `NimlyPRO24`, `NimlyShared`, `NimlyCodePRO` (linje 191).
Det er de samme ti som vår `SUPPORTED_MODELS` i `const.py`. Ingen mangler.

## Hva PR-en bør inneholde

Prosjektet krever `pnpm run check` (biome, `--error-on-warnings`) og
`pnpm run test` (vitest, `--config ./test/vitest.config.mts`). Biome er satt til
fire mellomrom, linjebredde 150 og `bracketSpacing: false`. `useNamingConvention`
er `error`, men tillater snake_case for objektliteral-nøkler, så
`last_used_pin_code` og vennene er greie.

### Endringer, i filrekkefølge

1. **Linje 33-52.** Erstatt ASCII-antakelsen med formatgjenkjenning. Trekk den ut
   i en navngitt hjelpefunksjon i `fzLocal`-omfanget, den blir for lang til å bo
   inne i `convert`. Ta imot `Buffer`, `number[]` og `string`. Stripp
   etterfølgende NUL. Skriv en kommentar som sier at begge formater finnes i
   felt, med henvisning til PR 11332 (ASCII) og
   zha-device-handlers#4881 (BCD).
2. **Linje 62-68.** Legg `"05": "unattributed"` i oppslaget. Vurder `"0a": "auto"`
   separat, se under.
3. **Linje 30, 69, 72, 75, 79, 82.** Fjern `result`, bruk to lokale variabler.
4. **Linje 87-89.** Slett `voltage`-grenen.
5. **Linje 96-110.** Bytt til attributtnavn (`numOfPinUsersSupported`,
   `maxPinLen`, `minPinLen`), rett den ombyttede min/max-mappingen, og døp
   `max_pin_users` om til `num_pin_users`.
6. **Linje 182 og 230.** Følg omdøpingen i exposes.
7. **Linje 172, 176, 220, 224.** Legg `"unattributed"` i begge enum-listene, i
   begge definisjonene.
8. **Linje 205-213.** Legg kapabilitetslesingen inn i Nimly sin `configure`,
   samme `try`-blokk som easyCodeTouch har på linje 155-161.

### Tester

Testene ligger i `test/`, kjøres med vitest, og er per leverandør:
`test/tuya.test.ts`, `test/sonoff.test.ts`, `test/nodieby.test.ts` og så videre.
`test/utils.ts` gir `mockDevice`, og `findByDevice` fra `src/index` slår opp
definisjonen. `test/fromZigbee.test.ts` viser det enkleste mønsteret: kall
`converter.convert(...)` direkte med en `msg`-literal og sammenlign med
`toStrictEqual`.

Det finnes ingen `test/onesti.test.ts` i dag. Legg en ny fil. Minimum:

- PIN i BCD: `msg.data` med `{257: Buffer.from([0x54, 0x78])}` gir
  `last_used_pin_code: "5478"`.
- PIN i ASCII: `{257: Buffer.from("141141", "ascii")}` gir `"141141"`. Dette er
  regresjonsvernet for PR 11332.
- Tvetydigheten: `{257: Buffer.from([0x39, 0x39])}` med `minPinLen` kjent som 4
  gir `"3939"`, ikke `"99"`. Klarer ikke fiksen dette uten tilstand, dokumenter
  valget i testen i stedet for å late som.
- Kilde `0x05`: `{256: 0x05010000}` gir
  `{last_lock_source: "unattributed", last_lock_user: "0"}`.
- Kjente kilder: `{256: 0x02020003}` gir
  `{last_unlock_source: "keypad", last_unlock_user: "3"}`. Dette er en ekte
  capture fra `docs/zigbee-protocol/zigbee-captures.md`, verdt å sitere i
  testkommentaren.
- Auto: `{256: 0x0a010000}`.
- Kapabiliteter: `{numOfPinUsersSupported: 50, maxPinLen: 8, minPinLen: 4}` gir
  `{num_pin_users: 50, max_pin_length: 8, min_pin_length: 4}`. Denne testen er
  hele beviset for funn 5 og 6, og den ville feilet på dagens kode.
- En negativ test på at numeriske nøkler ikke lenger brukes er unødvendig hvis
  testen over kjører mot navn.

`test/checkDefinition.test.ts` og `test/index.test.ts` går over alle
definisjoner og validerer exposes. De fanger opp en enum-verdi som mangler.
Kjør hele suiten, ikke bare den nye filen.

### Deling av PR-er

Foreslått deling, hvis Koenkk vil ha den:

**PR 1, ren feilretting, ingen brekkende endring.** Funn 1 (PIN-format), funn 2
(`0x05` lagt til, som bare fyller et hull der `unknown` sto), funn 5 og 6
(attributtnavn og min/max, der omdøpingen `max_pin_users` til `num_pin_users`
ikke kan brekke noe fordi feltet aldri har hatt en verdi), funn 7 (dødt
`voltage`), funn 4 (`result`), pluss kapabilitetslesing i Nimly sin `configure`.
Dette er hoveddelen, og alt av det er forsvarbart uten maskinvare.

**PR 2, `0x0a` fra `self` til `auto`.** Én linje pluss fire enum-lister.
Brekkende for automasjoner. Skill den ut, så et nei ikke tar med seg resten.
Nevn at ZHA-quirken gjør samme rename i
[zha-device-handlers#4881](https://github.com/zigpy/zha-device-handlers/pull/4881),
så de to økosystemene ender likt.

### Hva PR-teksten må være ærlig om

Ingen i dette prosjektet kjører Zigbee2MQTT, og ingen har testet endringene mot
en lås. Alt bygger på ZCL-captures fra en NimlyPRO gjennom ZHA (`docs/zigbee-protocol/zigbee-captures.md`),
på rapporter i zha-device-handlers#4881, og på lesing av zigbee-herdsman sin
egen kode. Skriv det rett ut i PR-en, og be om at noen med NimlyCodePRO
bekrefter `0x05` og at noen med en ASCII-lås bekrefter at PIN-en fortsatt kommer
riktig ut. Det er den eneste måten `0x05`-mappingen og PIN-heuristikken blir
verifisert.

16-bitsbredden på slot skal ikke fremstilles som bekreftet, se over.

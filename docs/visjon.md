# Visjon: Nimly PRO

## Den låsen du aldri tenker på

Nimly PRO-integrasjonen er den selvfølgelige måten å administrere en Nimly-lås på. Ingen app, ingen manuell programmering på keypadet, ingen regneark med koder. Låsen er en del av hjemmet ditt — og hjemmet ditt kjenner alle som bor der, alle som besøker, og alle som har vært.

## Hvem har tilgang

Familien har faste koder som bare er der. Fredrik, Frode, Anna, Annicken — navnene deres lever i Home Assistant, knyttet til hver sin kode og hver sin RFID-brikke. Når mamma ringer og sier at vaskehjelpen trenger tilgang neste uke, tar det ti sekunder: åpne HA, trykk "Sett kode", velg et navn, skriv fire siffer. Ferdig. Når uken er over, forsvinner koden av seg selv.

Gjester på hytta får en engangskode via SMS eller e-post. Koden aktiveres fredag kl 15 og slutter å virke søndag kl 12. Ingen trenger å tenke på det — verken gjesten eller deg. Hvis gjesten kommer for sent og koden har utløpt, sender du en ny med to trykk.

Oversikten over hvem som har tilgang er alltid oppdatert, alltid synlig, alltid ett sted. Ingen tvil om "har vi husket å fjerne koden til håndverkeren?"

## Hvem var her

Når noen låser opp døren, vet hjemmet hvem det var. Ikke bare "noen låste opp" — men "Frode låste opp med kode kl 16:43". Aktivitetsloggen er en tidslinje med navn, ikke anonyme hendelser. Fingeravtrykk, kode, RFID, nøkkel, remote — hver metode er tydelig markert.

Loggen er ikke bare for nysgjerrighet. Når du er hjemme i byen og vil vite om barna har kommet inn på hytta, ser du det umiddelbart. Når alarmen går og du vil vite hvem som var sist inne, er svaret der. Når du vil automatisere — "slå på varmen når noen låser opp for første gang etter tre dager" — har systemet dataene som trengs.

## Tillit uten verifisering

Når du setter en kode, vet du at den virker. Ikke "koden ble sendt, test den manuelt" — men "koden er aktiv på slot 5, bekreftet av låsen." Systemet leser tilbake fra låsen og verifiserer at koden faktisk ble lagret. Hvis noe gikk galt, sier det ifra umiddelbart — ikke etter at gjesten står ute i regnet og banker på.

Batterinivået vises tydelig, og du får varsel i god tid — ikke et rødt blink på keypadet som ingen ser. Signalkvaliteten til Zigbee-nettverket overvåkes, og om låsen mister kontakt, vet du det før det blir et problem.

## Administrasjon som ikke krever ekspertise

Faren din på 68 år åpner HA-appen, ser "Dørlås" i menyen, og forstår umiddelbart hva han kan gjøre. Legge til en kode, fjerne en kode, se hvem som har tilgang. Ingen Developer Tools, ingen YAML, ingen service-kall. Grensesnittet er designet for folk som bruker låser, ikke folk som programmerer smarthus.

Masterkoden er beskyttet. Fabrikkoden er byttet ut. Integrasjonen minner deg på det ved oppsett, og den advarer om sikkerhetsproblemer den kan oppdage — åpne slots med svake koder, koder som har stått uendret i måneder, brukere som aldri har låst opp.

## Alle Nimly-låser, overalt

Integrasjonen fungerer med enhver Nimly Touch Pro og Touch Pro 24, uavhengig av firmware-versjon. Den håndterer Zigbee-quirks automatisk — brukeren trenger ikke vite at Nimly returnerer malformede ZCL-responser eller at clustere lever på det tredje nivået i ZHA-objektkjeden. Den bare virker.

Hjemme-låsen og hytte-låsen administreres fra samme sted. Samme brukere, samme koder om du vil, eller ulike — du bestemmer. Når du legger til en ny lås, arver den familiens brukere automatisk hvis du ønsker det.

## Mer enn en lås

Låsen er en trigger for resten av hjemmet. Når Frode låser opp på hytta fredag ettermiddag, slår varmepumpen seg på, lyset i gangen tennes, og du får et stille varsel på telefonen: "Frode er fremme." Når siste person låser og går, setter hytta seg i hvilemodus — varme ned, lys av, alarmen på.

Dette krever ikke kompleks konfigurasjon. Integrasjonen eksponerer rike events som HA-automations kan bygge på — hvem, når, hvordan, hvilken lås. Byggeklossene er der. Brukeren kobler dem sammen.

---

Nimly PRO-integrasjonen gjør Nimly-låsen til en fullverdig del av det smarte hjemmet. Den fjerner den manuelle programmeringen, erstatter anonyme hendelser med navn, og gir trygghet om at tilgangen er nøyaktig slik du bestemte. Den er bygget av folk som faktisk har stått ute i kulda og lurt på hvorfor koden ikke virket — og som bestemte seg for at det aldri skal skje igjen.

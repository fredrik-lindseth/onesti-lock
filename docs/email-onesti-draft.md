# E-post til Onesti Products AS

**Til:** support@nimly.io / support@easyaccess.com
**Emne:** Zigbee integration — spørsmål om Connect Module (ZMNC010) for Home Assistant

---

Hei,

Jeg utvikler en open source Home Assistant-integrasjon for Onesti-låser (Nimly Touch Pro, EasyCodeTouch, EasyFingerTouch) via ZHA/Zigbee. Integrasjonen gir PIN-administrasjon og aktivitetssporing og er den eneste som fungerer med disse låsene over ZHA.

Under utviklingen har vi reverse-engineered noen Zigbee-attributter som ikke er dokumentert i ZCL Door Lock-spesifikasjonen, og jeg ønsker å verifisere funnene våre og stille noen tekniske spørsmål.

## 1. Attributt 0x0100 på DoorLock cluster — operation event

Vi har funnet at attrid 0x0100 sendes som bitmap32 (Report_Attributes) ved hver lås/opplåsings-hendelse. Vår dekoding (little-endian):

```
Byte 0: user_slot (0 = system, 3+ = brukerslot)
Byte 1: reservert (alltid 0)
Byte 2: action (1 = lock, 2 = unlock)
Byte 3: source (1 = RF, 2 = keypad, 3 = manual, 10 = auto)
```

Spørsmål:
- Er denne dekodingen korrekt?
- Hvilke source-verdier finnes for fingeravtrykk og RFID?
- Finnes det andre action-verdier utover lock/unlock?

## 2. Attributt 0x0101 — PIN-kode

Vi ser at attrid 0x0101 sendes som LVBytes med PIN-koden i BCD-format (f.eks. `0x09 0x27` = "5478"). Stemmer dette?

## 3. set_pin_code timeout

Lock/unlock-kommandoer via Zigbee fungerer pålitelig, men set_pin_code (ZCL command 0x05) timeouter ofte. Vi mistenker at respons-formatet avviker fra ZCL-standarden — zigpy får `IndexError` ved parsing av responsen, noe som tyder på et uventet format.

- Er respons-formatet for PIN-kommandoer dokumentert?
- Er det en spesifikk wake-timing eller sekvens som kreves for at låsen skal akseptere PIN-kommandoer?

## 4. Connect Module hardware

- Hvilken Zigbee SoC bruker ZMNC010? (Vi ser manufacturer code 0x1234, max buffer 108 bytes, max transfer 127 bytes)
- Hva er standard poll-intervall for sleepy end device-modusen?

## Bakgrunn

Integrasjonen er tilgjengelig på GitHub og støtter alle Onesti-modeller (NimlyPRO, NimlyPRO24, easyCodeTouch_v1, EasyCodeTouch, EasyFingerTouch). Den bruker `cluster.on_event("attribute_report")` i zigpy for å fange operation events — noe ingen andre ZHA-integrasjoner har fått til.

Vi bidrar gjerne funnene våre tilbake til community hvis dere kan bekrefte dekodingen.

Med vennlig hilsen,
Ola Lindseth
https://github.com/fredrik-lindseth/nimly-touch-pro-integration

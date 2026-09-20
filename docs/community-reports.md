# What the user community has reported

Everything below comes from Nordic and international user forums, vendor PDFs
that only surface through forum links, and app store listings. It is the one
place in this repo where the source is somebody else's door rather than our
own, so every claim carries a marker:

- **Measured** means the poster showed a screenshot, a log line, a payload, a
  photo or an oscilloscope-grade number they took themselves.
- **Relayed** means a user quoting the vendor or support. The quote is real,
  what it says may not be.
- **Anecdote** means somebody describing what they experienced or heard,
  without evidence anyone else can check.

Swept 2026-09-20 across hjemmeautomasjon.no, byggahus.se, hemautomation.se,
sweclockers, Danish forums and retailers, community.home-assistant.io,
community.homey.app, community.openhab.org, community.smartthings.com,
Hubitat, Reddit and YouTube. GitHub, Zigbee2MQTT, ZHA and the vendor's own
site are covered in `docs/upstream-status.md` and
`docs/hardware-generations.md` and were deliberately left out here.

## Bluetooth

**Nobody outside the vendor has ever posted a BLE scan of one of these
locks.** Not a screenshot from nRF Connect, not a GATT dump, not an
advertisement hex string, in any forum in any of the four languages searched.
The only third party who has scanned at all is aridder/nimly-manager, already
on record in `docs/upstream-status.md`. That silence is itself the finding:
our own failure to see an advertisement (`hacs-onesti-3y0crhl`) is not a
local fault, it is the normal state of affairs for everyone.

What the sweep did turn up is the vendor tying the Bluetooth radio to the
pairing window, which nothing we had said before.

The Connect Module installation guide on nimly.se, file dated 2024-10-23,
says it in one line (**relayed**, but it is the vendor's own PDF):

> The module enters pairing mode automatically for four minutes, indicated by
> orange (zigbee) and blue (bluetooth) flashing from the module.

and, for a module that has already been paired:

> Did you use too long to connect? To re-enter pairing mode, remove and
> reinsert the batteries/power while the units are connected.

and for the reset:

> How to reset: hold down the reset button on the module until the orange
> indicator blinks rapidly (about 15 seconds). Release the button
> immediately. On certain modules, you may need to wait four minutes (until
> pairing mode have ended) before performing the reset.

<https://nimly.se/wp-content/uploads/2024/10/EN-Connect-Module-Installation-Guide-231024-bluetooth-app-and-nimly-connect.pdf>

A user described the same two colours three years earlier, on 2021-10-10 on
hjemmeautomasjon.no, telling another user how to get the module into search
mode on Futurehome: pull one battery and put it back, and it "blinker gult og
blått" (**anecdote**, first-hand, independent of the PDF).
<https://www.hjemmeautomasjon.no/forums/topic/6786-easy-access-easycodetouch/page/2/>

Two independent sources therefore agree that the blue Bluetooth indicator is
a pairing-mode indicator, not a running-state one. That is the strongest
evidence yet for outcome (c) in `hacs-onesti-3y0crhl`: the module probably
only advertises inside the four-minute window, and `hacs-onesti-5fvt04o` (pull
a battery and watch) is the measurement that settles it.

The same PDF confirms the unloc route needs no hub: "Do you want to create
and share digital keys? No gateway required. Connect with the unloc-app
(BLE)."

Apple's App Store listing for **nimly BLE**, publisher Easy Access AS, says
"Create digital access or operate your device with basic functions by BLE.
Works with Zigbee BLE Module and Connect Module, installed in compatible
electronic device from EasyAccess or nimly." Version 1.0 shipped 2023-07-24,
1.0.3 on 2023-09-26 added "lock management and eKey functionality", 1.5.0 on
2025-06-08 was the rebrand from EasyAccess to nimly plus a Bluetooth signal
strength display and automatic disconnect on inactivity (**measured**, it is
the store's own version history).
<https://apps.apple.com/no/app/nimly-ble/id6451232924>

Note the two module names in that sentence. "Zigbee BLE Module" and "Connect
Module" are listed as separate things, which is consistent with the two
generations in `docs/hardware-generations.md` but does not by itself say which
is which.

On 2022-08-05, a hjemmeautomasjon.no user relaying what EasyAccess had told
him wrote that "Bluetooth-delen på modulen i låsen er under utvikling", the
Bluetooth part of the in-lock module is still under development (**relayed**).
That dates the BLE side as not yet live in the summer of 2022, on a module
that was already shipping with Zigbee.

**A line the text extract hides.** "*Bluetooth is only available on the newer
versions of the module" does stand in the Connect Module installation guide,
printed small under the green "Works with unloc" badge on the English 2024
edition and repeated in the Norwegian 2026 one. `pdftotext` drops it on the
English file, so a grep of the extract says it is not there. Render the page
and read it instead, as [docs/manuals/README.md](manuals/README.md) says.

### The first-generation Bluetooth module was a different device

This is the most useful single post found, and it predates everything else.

On 2018-10-17 on hjemmeautomasjon.no, GustavM bought the separate Bluetooth
module sold for the EasyAccess EasyCode, opened it and probed the connector
between module and lock (**measured**, first-hand instrumentation):

> De 4 pinnene er VCC, Jord og 2 pinner som settes høy for å hhv åpne og lukke
> låsen. [...] Unlock pin: Høy i 650 millisekund >>> 10,5 sekunder pause >>>
> Lock pin: Høy i 650 millisekund. Spenningsnivået når pinnene blir satt høy
> er ca 4.6V [...] Pluggen er en 4pin JST PH 2mm pitch.

There is no serial protocol and no authentication on that link. The module is
a dumb GPIO bridge that pulses two pins, and it sits in the same slot the
Zigbee module later took.

The consequence for us is worth stating plainly: "Bluetooth module" in this
product line has meant two entirely unrelated things. The old one carries no
lock protocol at all, so the ekey command set in
`docs/nimly-ble-app/ble-protocol.md` can only belong to the newer combined
module. An older lock that shows nothing on a BLE scan is behaving exactly as
designed.
<https://www.hjemmeautomasjon.no/forums/topic/3791-easyaccess-easycode-pinout/>

A year later, on 2019-12-12, another user on the same forum asked whether the
lock's Bluetooth could be paired to a Raspberry Pi or an ESP32 and driven
directly. Nobody ever answered that they had done it.
<https://www.hjemmeautomasjon.no/forums/topic/5766-easy-access-easycode-v2-kodel>

## Firmware versions people report

All of these come from the long Home Assistant thread "Nimly lock, with
Zigbee module". The firmware rows come from the first 181 posts,
January 2023 to December 2025; the thread ran to 241 posts by 2026-09-13.
<https://community.home-assistant.io/t/nimly-lock-with-zigbee-module/523634>

| Version | Date code | What the poster said | Post, date | Status |
| ------- | --------- | -------------------- | ---------- | ------ |
| not stated | `20220614`, `20230210` | both worked on Z2M, `20230530` did not | #50, dauzzen, 2023-08-22 | anecdote, read second-hand |
| not stated | `20230210` | battery reported as 200 % | #102, AdamOttvar, 2024-04-03 | anecdote, read second-hand |
| `4.5.26` | not stated | batteries every two weeks | #170, uvnikita, 2025-09-14 | measured, read directly |
| not stated | `20240529` | batteries drain | #168, Freddan101, 2025-09-14 | anecdote, read directly |
| `4.7.78` | not stated | module died after 2-3 days, lost Zigbee every night | #155, t0ffemannen, 2025-02-09 | anecdote, read second-hand |
| `4.7.79` | `20240625` | still drains faster than a Danalock | #174, NeoID, 2025-11-05 | anecdote, read directly |
| `4.7.79` | `20240625` | named as the minimum that works at all | #181, pyberg, 2025-12-08 | anecdote, read directly |
| `4.7.98` | `20240625` | after upgrading from 4.5.26, "batteries last so much longer" | #170, uvnikita, 2025-09-14 | measured, read directly |

`4.8.01` on `20240625` is already in `docs/hardware-generations.md` from
Z2M#31385, and a replacement module in the Homey thread carries the same
build, so the ladder runs at least 4.5.24, 4.5.26, 4.7.78, 4.7.79, 4.7.98,
4.8.01 against date codes `20220614`, `20230210`, `20230530`, `20240529` and
`20240625`. Note that one date code covers four different software builds,
which is another reason the date code alone says nothing about a generation.

## Updates arrive in the post, not over the air

Every user who got a newer firmware got it as a physically different module
mailed out by support. Post #20 (TheQue42, 2023-04-05) "I got the reseller to
provide me with an updated chip"; post #107 (retif, 2024-08-06) "That's my 3rd
module, as previous two had certain defects"; posts #152 and #154 (January and
February 2025) the same again. Post #174 (NeoID, 2025-11-05) says it outright:
"I'm a bit disappointed that there isn't support for OTA for this card."
Nobody in any forum reports an over-the-air update.

That is an independent confirmation, from the user side, of the conclusion
already reached from the Koenkk OTA index in `hacs-onesti-3c4bl36-c3`.

## Battery

The reason this section is long is that battery is the single most reported
problem with these locks, by a wide margin, in every forum and every language.

**Do not leave the module in an unpaired lock.** EasyAccess's own product
text, quoted on hjemmeautomasjon.no on 2021-10-09 (**relayed**):

> Vi anbefaler ikke å sette ZigBee modulen i dørlåsen om den ikke skal kobles
> opp mot et smarthjemsystem. Da vil modulen stå i kontinuerlig «søkemodus» og
> tappe dørlåsen for batteri.

An unpaired module sits in permanent search mode and drains the lock. This
matters for any hardware session where the module is deliberately left
unpaired between experiments.

**Real numbers from real doors.** On 2026-05-23 a hjemmeautomasjon.no user
running Z2M on an SLZB-06 reported changing batteries every two months on a
Nimly Touch Pro and every month on a Nimly Indoor, against the vendor's
claimed twelve (**anecdote**, first-hand, no log).
<https://www.hjemmeautomasjon.no/forums/topic/13667-nimly-id-lock-eller-nuki/>

**The battery percentage is wrong in two separate ways.** In December 2021 a
user watched the lock blink red and start to labour while Home Assistant
still showed 100 %. In 2024 the reported value was doubled: post #118
(uvnikita, 2024-10-22) through post #133 (Eriond, 2024-10-27) work out that
`battery_percentage_remaining` runs 0 to 200 per the ZCL spec and that the
fix is a `DoublingPowerConfigurationCluster` (**measured**, they show the
numbers, 20 against 40 and 37 against 74).

**The lock reports the wrong power source.** Post #118, uvnikita, 2024-10-22
(**measured**, read directly):

> I think the reason why ZHA is not showing battery percentage is because
> Nimly lock incorrectly presents itself as a Mains powered device.

This is a checkable claim about the Basic cluster `PowerSource` attribute,
and if it holds it is directly relevant to the sleepy-radio problem: a device
that declares itself mains-powered is not one a coordinator will queue
messages for. It costs one attribute read to settle and belongs on the
hardware checklist in `hacs-onesti-7ldhq4`.

**A claim that could not be verified.** A statement circulating from this
sweep, that a Homey user named the module "SIGMI" and blamed the drain on it
advertising as a non-sleepy mains-powered end device, was not found in the
Homey thread when that thread was read. The power-source half of it is the
same as uvnikita's verified post above; the module name is unsupported. Do
not cite it.

## Range and coverage

Second only to battery, and often the same thread. All post numbers below are
from the Home Assistant thread unless another source is named.

**The lock transmits weakly, and owners work it out the hard way.** The
pattern across three years is the same story told by strangers: the lock
pairs or reports badly, the owner adds a mains-powered router within a few
metres of the door, and it starts working.

- Post #54 (erik85, 2023-08-22), **measured**: nothing was found until the
  coordinator was moved into the same room. "Signal strength is 116 lqi with
  2m distance which seems a bit low?"
- Post #112 (haarfagr, 2024-09-21), **anecdote**: pairing only worked after
  moving the coordinator closer on a USB extension cable.
- Post #137 (mpcpro, 2024-11-24), **anecdote**: commands timing out after a
  successful pairing. "Seems like the range was the issue. Fixed with an ikea
  tretakt smart plug/repeater."
- Post #148 (MakkaKaplar, 2025-01-03), **anecdote**: a dimmer and a Trådfri
  repeater put within 2 m of the door before pairing would take.
- Post #180 (markus-lassfolk, 2025-12-07), **anecdote**: four locks, none
  stable until a full module reset plus "a Zigbee Repeater connected to the
  main power and not relying on battery based repeaters. I think this really
  did the difference."
- Post #185 (markus-lassfolk, 2026-01-20), **anecdote**: "The range of their
  hub and zigbee was terrible and unreliable."
- Post #220 (kork123, 2026-02-26), **anecdote**: an IKEA smart plug as an
  intermediate router works; an Aqara plug did not, because "the lock
  preferred to connect directly to the ConBee II and ignored the Aqara plug".
- Post #224 (endallas1, 2026-03-02), **anecdote**: 5-6 m, wooden walls only,
  no sensor updates at all until an IKEA switch went in near the door. "I
  guess it sends a quite weak signal."
- Post #244 (sebrk, 2026-09-13), **anecdote**: 2 m, one wooden wall, two
  different coordinators tried, raising transmit power tried. The lock still
  flips between available and unavailable every five minutes. Post #245
  (Fumble, same day) answers with three locks that all work, nearest repeater
  2-3 m away.

**Owners name the metal themselves.** Post #225 (kork123, 2026-03-03),
**anecdote**: "I would agree that there must be weak signals. The lock is
metal and the module sits behind the pcb." That is the only place anybody
outside this repo connects the enclosure to the radio, and it is a guess from
a user, not a measurement.

**The lock picks its parent badly, and slowly.** Mastiff's sequence in
February 2026 is the most detailed account anyone has posted (**measured**, he
gives LQI numbers throughout). Posts #197 and #201: a Sonoff dongle about six
metres away, the lock goes unavailable after a day to a week, and only a
battery pull brings it back; he is on Zigbee channel 25 with his own two
2.4 GHz networks on 1 and 6, in a dense neighbourhood. He adds an IKEA
Trådfri extender between dongle and lock, and "the lock does not go
automatically via the extender even after a couple of days". Post #209: moved
half a metre from the lock, the extender finally gets the pairing, and link
quality goes from under 100 to 148. Post #210, the next morning: with no
reboot and no intervention, every device in that flat moved over to the
Trådfri at once, LQI 196. Post #187 (pyberg, 2026-01-24) says the same thing
from the other side: a bulb inside the door acting as a router, and an
SLZB-06 coordinator chosen because it "have a better antenna than the
Skyconnect".

Two things follow for anyone buying. A router near the door is necessary but
not sufficient: the lock may keep talking to a distant coordinator for days
before it re-parents, and nothing in Home Assistant forces it. And the LQI
numbers people quote as working, 116 to 196, are the whole reported range;
nobody has posted a comfortable one.

`docs/buying-a-lock.md` has the measurements from Fredrik's own door against
this, and `docs/debugging.md` says what to do about it.

## Losing the connection, and getting it back

The sleepy-radio behaviour we measured on Fredrik's own lock is reported by
strangers in the same words.

- Post #104 (Dorenix, 2024-05-23): the lock "becomes unresponsive to messages
  sent from home assistant after it has not been used for some time (~1h)".
- Posts #40 and #47 (JesperWe, August 2023): the connection dies after a few
  hours idle and a battery pull is needed to get it back.
- Post #180 (markus-lassfolk, 2025-12-07): pairing only became stable after a
  full Zigbee reset and switching to mains-powered repeaters rather than
  battery-powered ones.

Two reset recipes are on record, and they differ, which is worth knowing
before a hardware session. EasyAccess support in 2021 said to hold the button
on the module for 12 to 18 seconds until a fast yellow blink, then pull and
reinsert a battery. The 2024 vendor guide says about 15 seconds until the
orange indicator blinks rapidly, release immediately, and that on some
modules you have to wait out the four-minute pairing window first. The colour
is the same one under two names; the timing advice is not.

## What users saw over Zigbee before we started

Two posts are worth keeping because they date things we thought were recent.

On 2021-03-21, a hjemmeautomasjon.no user listed what Z2M gave him on a fresh
module: remaining battery, battery type AA, lock state, the source of the
unlock (keypad against RFID tag), lock and unlock commands, auto-relock and
sound volume. He adds that opening with the physical key produces no response
over Zigbee at all (**anecdote**, first-hand). The negative is the useful
part: a mechanical key turn is invisible to us and always has been.

On 2022-12-27 another user posted a raw Z2M payload (**measured**):

```
{"action":null,"action_source_name":null,"action_user":null,"auto_relock":null,
"battery":100,"linkquality":255,"lock_state":"unlocked","sound_volume":"high_volume",
"state":"UNLOCK"}
```

with the complaint that `action_user` is always null. That is the same report
matthiasnielsen1 filed in 2026 and that `docs/upstream-status.md` treats as
open. It is four years older than we thought.

## The PIN in the clear, confirmed by strangers

Post #166 (sintei, 2025-09-14) after a Z2M change: "With these changes we can
now see the users pincode in the logfile which is horrible." Post #167
(uvnikita, same day): "That's why I disabled this entity by default ... the
actual pin code there instead of just a slot number" (**measured**, read
directly).

Independent users hitting the same exposure we removed in v1.3.0 and raised
on the ZHA quirk PR is worth having in hand the next time that thread needs a
nudge. `docs/upstream-status.md` holds the thread itself.

## Models and brands

Unloc's own install guide, updated 2024-10-11, is titled "How to install
Nimly Touch Pro/Touch/Code/Indoor", which is the first place **Nimly Indoor**
turns up in our material. A hjemmeautomasjon.no user runs one alongside a
Touch Pro on the same Z2M install.
<https://help.unloc.app/en/article/how-to-install-nimly-touch-protouchcodeindoor-aesdl5>

EasyAccess's 2021 product text lists the smart home systems it then worked
with, Safe4, Homely, FutureHome and Homey, with "EasyAccess App, Unloc" under
development. On 2021-05-12 a user confirmed the same Zigbee 3.0 module fits
both the Touch series and the older EasyCode V2, the latter through an
adapter PCB (**anecdote**, first-hand purchase), which is a small piece of
evidence that the module is one article across a wider range of locks than
the model table suggests.

Nothing substantial was found under the Salus, Keyfree, Copiax, Tryg Smart or
Safe4 names. Searches in Swedish and Danish retailer and forum space returned
product listings and the vendor's own manuals rebadged, no user discussion
with technical content, and no Salus-specific material at all despite Salus
having its own hub ecosystem.

## What does not exist anywhere

Listing this is the point of the sweep as much as the findings are. None of
the following could be found in any forum, blog, video or comment thread:

- A BLE scan, advertisement dump or GATT listing of any lock in this family
  by anyone other than aridder/nimly-manager.
- A teardown photo showing the module's PCB at chip level. The closest is
  smartahemtest.se, which photographs the opened inside unit with the module
  fitted, at a distance that resolves nothing.
  <https://www.smartahemtest.se/djupgaende-tester/nimly-touch-pro-black>
- Any FCC internal photo set for ZMNC010.
- A single first-hand account of using unloc with one of these locks. The
  integration is documented only by unloc and by the vendor.
- Anyone who has had shell, UART or root on a Connect Bridge. Develco's own
  MGW211 material describes Squid.link as an open Linux platform and mentions
  SSH as a feature, but no user has reported getting in.
- Any over-the-air firmware update.
- Anyone distinguishing module generations by silkscreen, revision number or
  any other visible mark. Users tell them apart only by behaviour, which
  means the Ember/Datek against Nordic/E-Life split in
  `docs/hardware-generations.md` is ours alone.
- Any Reddit discussion at all, in any subreddit, in any language.

## Sources

- hjemmeautomasjon.no, thread 3791 "EasyAccess Easycode pinout", 2018-10-17 to
  2021-12, <https://www.hjemmeautomasjon.no/forums/topic/3791-easyaccess-easycode-pinout/>
- hjemmeautomasjon.no, thread 6786 "Easy Access EasyCodeTouch", 2020 to
  2022-12, <https://www.hjemmeautomasjon.no/forums/topic/6786-easy-access-easycodetouch/>
- hjemmeautomasjon.no, thread 5766 "EasyAccess EasyCode V2 kodelås",
  2019-12-12, <https://www.hjemmeautomasjon.no/forums/topic/5766-easy-access-easycode-v2-kodel>
- hjemmeautomasjon.no, thread 13667 "Nimly, ID-lock eller Nuki", 2026-05-12 to
  2026-05-23, <https://www.hjemmeautomasjon.no/forums/topic/13667-nimly-id-lock-eller-nuki/>
- community.home-assistant.io, "Nimly lock, with Zigbee module", 241 posts,
  2023-01 to 2026-09, read in full from the thread JSON on 2026-09-20, <https://community.home-assistant.io/t/nimly-lock-with-zigbee-module/523634>
- community.homey.app, "Can't add Nimly / EasyAccess lock", 2023-07,
  <https://community.homey.app/t/cant-add-nimly-easyaccess-lock/78867>
- community.openhab.org, "Binding request for Easyaccess EASYCODETOUCH door
  lock", 2021-08-21, <https://community.openhab.org/t/binding-request-for-easyaccess-easycodetouch-door-lock/125747>
- community.smartthings.com, "Easy Access EasyCode door lock zigbee module",
  2018-04 to 2018-05, <https://community.smartthings.com/t/easy-access-easycode-door-lock-zigbee-module-compatible-with-smartthings-hub/86418>
- byggahus.se, "Nimly Touch / Touch Pro -tråd" (497166), "Nimly Code / Code
  Pro -tråd" (573457) and "Nimly Zigbee - Z2M eller ZHA?" (543716). All three
  block automated fetching and were only reachable through search engine
  summaries, so nothing from them is cited above as fact. Someone reading them
  by hand, logged in, is the obvious next step.
- nimly.se, Connect Module installation guide, file dated 2024-10-23,
  <https://nimly.se/wp-content/uploads/2024/10/EN-Connect-Module-Installation-Guide-231024-bluetooth-app-and-nimly-connect.pdf>
- App Store, nimly BLE, Easy Access AS, <https://apps.apple.com/no/app/nimly-ble/id6451232924>
- help.unloc.app, "How to install Nimly Touch Pro/Touch/Code/Indoor",
  updated 2024-10-11

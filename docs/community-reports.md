# What the user community has reported

Everything here comes from Nordic and international forums, vendor PDFs that
only surface through forum links, and app store listings. The source is
somebody else's door, so every claim carries a marker:

- **Measured**: the poster showed a screenshot, a log line, a payload, a
  photo or a number they took themselves.
- **Relayed**: a user quoting the vendor or support. The quote is real, what
  it says may not be.
- **Anecdote**: somebody describing what they experienced or heard, with
  nothing anyone else can check.

Swept 2026-09-20 across hjemmeautomasjon.no, byggahus.se, hemautomation.se,
sweclockers, Danish forums and retailers, community.home-assistant.io,
community.homey.app, community.openhab.org, community.smartthings.com,
Hubitat, Reddit and YouTube.

Since then the material is read from a local archive, not the web: 105 dated
sources listed in [docs/manuals/README.md](manuals/README.md) and fetched by
`python3 scripts/fetch_manuals.py --living`. That is 24 forum threads, 62
GitHub issues and pull requests across the four upstream projects, the
converter and quirk sources, and the vendor's product pages and app listings.
The counts below were made from that archive and can be redone. Rerunning the
fetch says what has arrived since.

## What people actually complain about

A census: every archived thread read through, one count per problem,
counting people rather than posts. Someone who raised the same thing in three
places counts once. The numbers are a floor: how many owners wrote it down
somewhere this archive reaches.

| Problem | People | Where | Solved by, and for how many |
| ------- | -----: | ----- | --------------------------- |
| Pairing fails, or the lock drops off and goes unavailable | ~47 | HA thread (40), Homey (6), SmartThings (1), plus 7 more on GitHub | A replacement module from the vendor (about 10), a mains-powered router by the door (about 6), a full module reset (3). Unresolved for at least 8 at their last post |
| No way to tell who opened the door, or how | ~30 | 19 in the HA thread, 6 on GitHub, 5 on hjemmeautomasjon and Homey | Z2M since 2021 for the source type, never the slot number. ZHA since the 4138 quirk. deCONZ never |
| Battery percentage is wrong: halved, doubled, or stuck | 16 | 8 in the HA thread, 4 on Z2M, 4 on Homey and hjemmeautomasjon | Found and fixed upstream: the attribute is 0-200 per ZCL. ZHA PRs 3457 and 3465, Z2M converter PRs 6940 and 7237. One user still saw 50 % on a new module months after |
| Batteries do not last | ~11 | 8 in the HA thread, more on Homey | Firmware 4.7.98 for exactly one person. Nothing else |
| The vendor gateway and a Zigbee coordinator cannot both have the lock | 10 | 8 in the HA thread, 2 on Homey | Nothing to solve: one Zigbee network per device. Two users found out only after buying |
| The model string is not in the converter, so the lock is a dumb device | ~10 | Ten separate "new device support" issues, 2021 to 2026 | Each one by hand, each time merged. It keeps happening because the same hardware ships under new strings |
| Auto-relock cannot be turned off | 6 | 5 on Homey, 1 on hjemmeautomasjon (an older model) | Nothing. A battery pull makes the setting take, sometimes |
| The PIN is in the log in clear text | 3 | HA thread, ZHA quirk, Z2M converter | Disabling the entity. Still open upstream in both projects |
| Sensors stopped updating after HA 2026.2 | 3 | HA thread, and zha-device-handlers#5235 | Nothing merged. One user moved to Z2M |

Two of those deserve more than the count.

Auto-relock is the vendor's own answer to a sleepy device. Five Homey owners
set auto-relock off, the lock accepted it, and the door relocked a few seconds
later anyway. Nimly support, quoted in full by the thread's first poster
(**relayed**), says why:

> the lock is a battery device [...] there is a difference between a command
> and a configuration update: the first is always accepted, the second
> unfortunately is not

That is the vendor saying a configuration write to a sleeping lock is
unreliable, which is what `ZhaLockTransport.send()` works around and why a
PIN write is only believed after a delivered send. Their advice is to give up
on the setting and rebuild auto-relock in automations.
<https://community.homey.app/t/104305>

Nobody can set a PIN and be sure it took. One Homey user's code did not work
on the keypad and then started working about twelve hours later, nothing
changed (**measured**, he gives the timing). Another's never took. On the
Home Assistant side, one user hit a plain ZCL timeout on Set PIN Code
(cluster 257, command 5, 10 s) through the Z2M dashboard and got it through by
publishing the payload by hand, while a second needed a differently shaped
payload on a different topic for the same operation (**measured**, both
payloads are in the thread). A third asked and was answered, empirically,
that PIN, RFID and fingerprint each have their own ID range, so the same
number in all three is three different credentials.
<https://community.home-assistant.io/t/nimly-touch-pro/930415>

### Things reported once or twice, worth knowing anyway

- A mechanical fault that looks like a radio fault. Two HA thread users
  (kork123 #220-#222, Mastiff #227) traced intermittent dropouts to the module
  losing pin contact when the door slams, and fixed it with double-sided tape
  between module and PCB. If that holds, some of the range story is not range.
- No child lock, on purpose. The inside handle cannot be disabled, and the
  vendor withholds away-mode from the Homey app on fire escape grounds (Homey
  thread 147580, one asker, answered by the app author).
- Fingerprint and RFID can only be enrolled on the keypad, not over Zigbee.
  Two or three reporters. A firmware limit, not an integration one.
- The lock declares itself mains powered. One open Z2M issue (#32772,
  2026-08-07) and a 2021 deCONZ device record with `"powerSource":"DC
  Source"` for the same family. Same claim as in the battery section below,
  visible in the record for five years.
- Support is inconsistent rather than bad. In one Homey thread one owner got
  no answer at all while another got one within a week and later within 24
  hours, on the same problem.
- A motor that stopped after five months, replaced under warranty, and a lock
  that beeps at an unlock command without moving the bolt. One report each.

### Where the search found nothing

The GitHub sweep covered every issue and PR mentioning nimly, onesti,
easyaccess, easycode, easyfinger or e-life in zigbee2mqtt,
zigbee-herdsman-converters, zha-device-handlers and deconz-rest-plugin: 62 in
all. `ZMNC010`, the module's part number, returns zero hits in all four.
Nobody on GitHub has ever called the module by the name in the manual.
`keyfree` and a lock-related `salus` return nothing either; a plain `salus`
search gives fifty issues about the unrelated thermostat brand.

## Bluetooth

Nobody outside the vendor has ever posted a BLE scan of one of these locks.
No nRF Connect screenshot, no GATT dump, no advertisement hex string, in any
forum in any of the four languages searched. The only third party who has
scanned at all is aridder/nimly-manager, on record in
`docs/upstream-status.md`. That silence is the finding: our own failure to
see an advertisement is the normal state for everyone.

What the sweep did turn up is the vendor tying the Bluetooth radio to the
pairing window, which nothing we had said before. The Connect Module
installation guide on nimly.se, file dated 2024-10-23 (**relayed**, but the
vendor's own PDF):

> The module enters pairing mode automatically for four minutes, indicated by
> orange (zigbee) and blue (bluetooth) flashing from the module.

For a module already paired:

> Did you use too long to connect? To re-enter pairing mode, remove and
> reinsert the batteries/power while the units are connected.

And the reset:

> How to reset: hold down the reset button on the module until the orange
> indicator blinks rapidly (about 15 seconds). Release the button
> immediately. On certain modules, you may need to wait four minutes (until
> pairing mode have ended) before performing the reset.

<https://nimly.se/wp-content/uploads/2024/10/EN-Connect-Module-Installation-Guide-231024-bluetooth-app-and-nimly-connect.pdf>

A user described the same two colours three years earlier, 2021-10-10 on
hjemmeautomasjon.no, telling another how to get the module into search mode
on Futurehome: pull one battery and put it back, and it "blinker gult og
blått" (**anecdote**, first-hand, independent of the PDF).
<https://www.hjemmeautomasjon.no/forums/topic/6786-easy-access-easycodetouch/page/2/>

Two independent sources agree that the blue indicator means pairing mode, not
running state. That is the strongest evidence yet that the module only
advertises inside the four-minute window, and pulling a battery while
watching a scanner is the measurement that settles it. Nobody has run it.

The same PDF confirms the unloc route needs no hub: "Do you want to create
and share digital keys? No gateway required. Connect with the unloc-app
(BLE)."

Apple's App Store listing for nimly BLE, publisher Easy Access AS, says
"Create digital access or operate your device with basic functions by BLE.
Works with Zigbee BLE Module and Connect Module, installed in compatible
electronic device from EasyAccess or nimly." Version 1.0 shipped 2023-07-24,
1.0.3 on 2023-09-26 added "lock management and eKey functionality", 1.5.0 on
2025-06-08 was the rebrand from EasyAccess to nimly plus a signal strength
display and automatic disconnect on inactivity (**measured**, the store's own
version history). <https://apps.apple.com/no/app/nimly-ble/id6451232924>

"Zigbee BLE Module" and "Connect Module" are listed there as separate things,
which fits the two generations in `docs/hardware-generations.md` but does not
say which is which.

On 2022-08-05 a hjemmeautomasjon.no user relaying EasyAccess wrote that
"Bluetooth-delen på modulen i låsen er under utvikling", the Bluetooth part
of the module is still under development (**relayed**). So the BLE side was
not live in the summer of 2022, on a module already shipping with Zigbee.

One line the text extract hides: "*Bluetooth is only available on the newer
versions of the module" does stand in the Connect Module guide, small under
the green "Works with unloc" badge on the English 2024 edition and repeated in
the Norwegian 2026 one. `pdftotext` drops it on the English file, so a grep
says it is not there. Render the page, as
[docs/manuals/README.md](manuals/README.md) says.

### The first-generation Bluetooth module was a different device

The most useful single post found, and it predates everything else. On
2018-10-17 on hjemmeautomasjon.no, GustavM bought the separate Bluetooth
module sold for the EasyAccess EasyCode, opened it and probed the connector
(**measured**, first-hand):

> De 4 pinnene er VCC, Jord og 2 pinner som settes høy for å hhv åpne og lukke
> låsen. [...] Unlock pin: Høy i 650 millisekund >>> 10,5 sekunder pause >>>
> Lock pin: Høy i 650 millisekund. Spenningsnivået når pinnene blir satt høy
> er ca 4.6V [...] Pluggen er en 4pin JST PH 2mm pitch.

No serial protocol, no authentication. That module is a GPIO bridge that
pulses two pins, in the slot the Zigbee module later took. So "Bluetooth
module" has meant two unrelated things in this product line. The old one
carries no lock protocol, so the ekey command set in
`docs/nimly-ble-app/ble-protocol.md` can only belong to the newer combined
module, and an older lock that shows nothing on a BLE scan is behaving as
designed.
<https://www.hjemmeautomasjon.no/forums/topic/3791-easyaccess-easycode-pinout/>

On 2019-12-12 another user on the same forum asked whether the lock's
Bluetooth could be driven from a Raspberry Pi or ESP32. Nobody ever answered
that they had done it.
<https://www.hjemmeautomasjon.no/forums/topic/5766-easy-access-easycode-v2-kodel>

## Firmware versions people report

All from the Home Assistant thread "Nimly lock, with Zigbee module". The rows
come from the first 181 posts, January 2023 to December 2025; the thread ran
to 241 posts by 2026-09-13.
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

`4.8.01` on `20240625` is in `docs/hardware-generations.md` from Z2M#31385,
and a replacement module in the Homey thread carries the same build. So the
ladder runs at least 4.5.24, 4.5.26, 4.7.78, 4.7.79, 4.7.98, 4.8.01 against
date codes `20220614`, `20230210`, `20230530`, `20240529` and `20240625`. One
date code covers four software builds, so the date code alone says nothing
about a generation.

## Updates arrive in the post, not over the air

Every user who got newer firmware got it as a different module mailed by
support. Post #20 (TheQue42, 2023-04-05): "I got the reseller to provide me
with an updated chip". Post #107 (retif, 2024-08-06): "That's my 3rd module,
as previous two had certain defects". Posts #152 and #154 (January and
February 2025): the same. Post #174 (NeoID, 2025-11-05): "I'm a bit
disappointed that there isn't support for OTA for this card." Nobody in any
forum reports an over-the-air update. That confirms, from the user side,
what the Koenkk OTA index already said.

## Battery

Battery is the single most reported problem with these locks, by a wide
margin, in every forum and language.

Do not leave the module in an unpaired lock. EasyAccess's product text,
quoted on hjemmeautomasjon.no on 2021-10-09 (**relayed**):

> Vi anbefaler ikke å sette ZigBee modulen i dørlåsen om den ikke skal kobles
> opp mot et smarthjemsystem. Da vil modulen stå i kontinuerlig «søkemodus» og
> tappe dørlåsen for batteri.

An unpaired module sits in permanent search mode and drains the lock, which
matters for any hardware session that leaves the module unpaired between
experiments.

Real numbers from real doors: on 2026-05-23 a hjemmeautomasjon.no user on
Z2M with an SLZB-06 reported changing batteries every two months on a Touch
Pro and every month on a Nimly Indoor, against the vendor's claimed twelve
(**anecdote**, first-hand, no log).
<https://www.hjemmeautomasjon.no/forums/topic/13667-nimly-id-lock-eller-nuki/>

The battery percentage is wrong in two separate ways. In December 2021 a user
watched the lock blink red and labour while Home Assistant showed 100 %. In
2024 the value was doubled: posts #118 (uvnikita, 2024-10-22) through #133
(Eriond, 2024-10-27) work out that `battery_percentage_remaining` runs 0 to
200 per ZCL and that the fix is a `DoublingPowerConfigurationCluster`
(**measured**, 20 against 40 and 37 against 74).

The lock reports the wrong power source. Post #118, uvnikita, 2024-10-22
(**measured**, read directly):

> I think the reason why ZHA is not showing battery percentage is because
> Nimly lock incorrectly presents itself as a Mains powered device.

A checkable claim about the Basic cluster `PowerSource` attribute, and
relevant to the sleepy-radio problem if it holds: a coordinator does not
queue messages for a device that says it is mains powered. One attribute read
settles it, and nobody has done it.

A claim that could not be verified: the story that the module is called
"SIGMI" and drains the lock by advertising as non-sleepy turns up once, in
the Homey thread "[APP] Nimly", post #3, and the poster says he got it from
ChatGPT. The power-source half is true and independently measured (uvnikita
above, and Z2M issue #32772); the module name is an invention. Do not cite it.
<https://community.homey.app/t/143578>

## Range and coverage

Second only to battery, often in the same thread. Post numbers are from the
Home Assistant thread unless another source is named.

The lock transmits weakly, and owners find out the hard way. Three years of
strangers telling the same story: the lock pairs or reports badly, the owner
adds a mains-powered router within a few metres of the door, and it works.

- Post #54 (erik85, 2023-08-22), **measured**: nothing found until the
  coordinator was moved into the same room. "Signal strength is 116 lqi with
  2m distance which seems a bit low?"
- Post #112 (haarfagr, 2024-09-21), **anecdote**: pairing only worked after
  moving the coordinator closer on a USB extension cable.
- Post #137 (mpcpro, 2024-11-24), **anecdote**: commands timing out after a
  successful pairing. "Seems like the range was the issue. Fixed with an ikea
  tretakt smart plug/repeater."
- Post #148 (MakkaKaplar, 2025-01-03), **anecdote**: a dimmer and a Trådfri
  repeater within 2 m of the door before pairing would take.
- Post #180 (markus-lassfolk, 2025-12-07), **anecdote**: four locks, none
  stable until a full module reset plus "a Zigbee Repeater connected to the
  main power and not relying on battery based repeaters. I think this really
  did the difference."
- Post #185 (markus-lassfolk, 2026-01-20), **anecdote**: "The range of their
  hub and zigbee was terrible and unreliable."
- Post #220 (kork123, 2026-02-26), **anecdote**: an IKEA smart plug as router
  works; an Aqara plug did not, because "the lock preferred to connect
  directly to the ConBee II and ignored the Aqara plug".
- Post #224 (endallas1, 2026-03-02), **anecdote**: 5-6 m, wooden walls, no
  sensor updates until an IKEA switch went in near the door. "I guess it
  sends a quite weak signal."
- Post #244 (sebrk, 2026-09-13), **anecdote**: 2 m, one wooden wall, two
  coordinators tried, transmit power raised. The lock still flips between
  available and unavailable every five minutes. Post #245 (Fumble, same day)
  answers with three locks that all work, nearest repeater 2-3 m away.

Post #225 (kork123, 2026-03-03), **anecdote**: "I would agree that there must
be weak signals. The lock is metal and the module sits behind the pcb." The
only place anybody outside this repo connects the enclosure to the radio, and
a guess, not a measurement.

The lock picks its parent badly, and slowly. Mastiff's sequence in February
2026 is the most detailed account posted (**measured**, LQI numbers
throughout). Posts #197 and #201: a Sonoff dongle about six metres away, the
lock goes unavailable after a day to a week, and only a battery pull brings it
back; Zigbee channel 25, his own two 2.4 GHz networks on 1 and 6, dense
neighbourhood. He adds an IKEA Trådfri extender between dongle and lock, and
"the lock does not go automatically via the extender even after a couple of
days". Post #209: extender moved to half a metre from the lock, it finally
takes the pairing, LQI from under 100 to 148. Post #210, next morning: with
no intervention, every device in the flat moved to the Trådfri, LQI 196. Post
#187 (pyberg, 2026-01-24) says the same from the other side: a bulb inside the
door as router, and an SLZB-06 chosen because it "have a better antenna than
the Skyconnect".

Two things follow for a buyer. A router near the door is necessary but not
sufficient: the lock may keep talking to a distant coordinator for days, and
nothing in Home Assistant forces it. And the LQI numbers people quote as
working, 116 to 196, are the whole reported range; nobody has posted a
comfortable one.

`docs/debugging.md` has the measurements from Fredrik's door against this,
and what to do about it.

## Losing the connection, and getting it back

The sleepy-radio behaviour measured on Fredrik's lock is reported by strangers
in the same words.

- Post #104 (Dorenix, 2024-05-23): the lock "becomes unresponsive to messages
  sent from home assistant after it has not been used for some time (~1h)".
- Posts #40 and #47 (JesperWe, August 2023): the connection dies after a few
  hours idle and a battery pull is needed.
- Post #180 (markus-lassfolk, 2025-12-07): pairing only became stable after a
  full Zigbee reset and mains-powered repeaters instead of battery ones.

Two reset recipes are on record, and they differ. EasyAccess support in 2021
said to hold the module button 12 to 18 seconds until a fast yellow blink,
then pull and reinsert a battery. The 2024 vendor guide says about 15 seconds
until the orange indicator blinks rapidly, release at once, and on some
modules wait out the four-minute pairing window first. Same colour under two
names; the timing advice differs.

## What users saw over Zigbee before we started

Two posts date things we thought were recent.

On 2021-03-21 a hjemmeautomasjon.no user listed what Z2M gave him on a fresh
module: battery, battery type AA, lock state, the source of the unlock
(keypad against RFID tag), lock and unlock commands, auto-relock and sound
volume. Opening with the physical key produced no response over Zigbee at all
(**anecdote**, first-hand). The negative is the useful part: a mechanical key
turn is invisible to us and always has been.

On 2022-12-27 another user posted a raw Z2M payload (**measured**):

```
{"action":null,"action_source_name":null,"action_user":null,"auto_relock":null,
"battery":100,"linkquality":255,"lock_state":"unlocked","sound_volume":"high_volume",
"state":"UNLOCK"}
```

with the complaint that `action_user` is always null. That is the report
matthiasnielsen1 filed in 2026 and that `docs/upstream-status.md` treats as
open. It is four years older than we thought.

## The PIN in the clear, confirmed by strangers

Post #166 (sintei, 2025-09-14) after a Z2M change: "With these changes we can
now see the users pincode in the logfile which is horrible." Post #167
(uvnikita, same day): "That's why I disabled this entity by default ... the
actual pin code there instead of just a slot number" (**measured**, read
directly).

Independent users hitting the exposure we removed in v1.3.0 and raised on the
ZHA quirk PR. Worth having in hand next time that thread needs a nudge;
`docs/upstream-status.md` holds the thread.

## Models and brands

Unloc's install guide, updated 2024-10-11, is titled "How to install Nimly
Touch Pro/Touch/Code/Indoor", the first place Nimly Indoor turns up in our
material. A hjemmeautomasjon.no user runs one next to a Touch Pro on the same
Z2M install.
<https://help.unloc.app/en/article/how-to-install-nimly-touch-protouchcodeindoor-aesdl5>

EasyAccess's 2021 product text lists the systems it then worked with, Safe4,
Homely, FutureHome and Homey, with "EasyAccess App, Unloc" under development.
On 2021-05-12 a user confirmed the same Zigbee 3.0 module fits both the Touch
series and the older EasyCode V2, the latter through an adapter PCB
(**anecdote**, first-hand purchase): a small sign that the module is one
article across more locks than the model table suggests.

Nothing substantial under the Salus, Keyfree, Copiax, Tryg Smart or Safe4
names. Swedish and Danish retailer and forum searches returned listings and
the vendor's manuals rebadged, no user discussion with technical content, and
nothing Salus-specific despite Salus having its own hub ecosystem.

## The vendor's hub

Owners who bought the Connect Gateway write about it in the same tone as the
module: it works until the radio does not reach. One HA thread user got only
one of four locks onto the hub, and that one dropped off after a few days, so
he moved all four to Z2M with a mains-powered repeater by the door (#180,
**anecdote**). Another: "the range of their hub and Zigbee was terrible and
unreliable, made me switch to Z2M" (#185, **anecdote**). A third bought the
gateway solely to get a module firmware update through it, and got none
(#42, **anecdote**). The one contented report is from a user who has run the
lock only on the hub and had not changed batteries in over a year, though the
app never showed him a battery level (#171, **anecdote**).

Nobody has integrated the hub with anything. Two people asked in the Home
Assistant thread whether the Nimly gateway could be reached from HA, in
November 2023 (#62) and December 2024 (#146). Neither got a reply. A Homey
owner asked the same and was told by the app author that the Homey
integration is Zigbee straight to the lock, because the gateway offers no
cloud path (Homey thread 141138, **relayed**). The technical reason is in
[docs/connect-bridge/hardware-gateway.md](connect-bridge/hardware-gateway.md):
no local API, no LAN discovery in the app, everything over MQTT to the cloud.

"Gateway or coordinator, not both" is the most-asked thing about the hub, and
a support reply quoted in the thread adds a twist: one home central at a
time, "but that people on forums had gotten it working" (#80, **relayed**).
Nobody in the archive has, and one Zigbee device joins one network, so read
that as support being vague, not as a hint.

## The Swedish forums

All four threads were read on 2026-09-20, by hand: 621 byggahus posts from
2023-08 to 2026-09, plus two on sweclockers. Neither site can be fetched by
script.

sweclockers thread 1713551 (April 2024) is two posts and no answers. A Touch
Pro owner tired of running a hub per brand asks whether Homey Pro gives him
Nimly's full feature set, meaning cloud control for remote unlock and code
management, and whether the lock can go into Apple's keys so a phone tap
opens the door (**anecdote**, both questions). A second member asks whether
Nimly's own gateway is needed at all next to a Homey. Nobody replied to
either in two and a half years.

byggahus 543716 (March 2025, 7 posts) is the Z2M against ZHA question. The
buyer has a Connect Module and a SkyConnect dongle and has been told the
module works with both bridges, "but not simultaneously" (**relayed**, source
not named, and it matches the one Zigbee network per device the rest of this
file describes). The answers are the usual preference argument. No frames, no
payloads, no firmware versions.

byggahus 497166 (592 posts over three years) and 573457 (22 posts, the Code
and Code Pro thread) are mostly doors: strike plates, the square spindle that
has to go in red-mark-up, emergency keys that will not turn until the
through-bolts are backed off, fingerprint readers in fog. The Zigbee content
is thin for the length, and it repeats what the Home Assistant and Homey
threads already say: modules that drop off, batteries gone in two weeks, a
replacement module from the vendor as the fix, one gateway per lock. What is
new or worth pinning down is below.

Somebody found this integration, once. On 2026-04-16 in 497166,
maskeradeproggaren posts the repo link with "en kille gjort en integration som
ska ha alla egenskaper såsom lösenordhantering för Nimly", adds that it runs
ZHA and not Zigbee2MQTT, and says he is weighing buying a second coordinator
for the door rather than migrating. Nobody answered him and he never returned
to it. That is the whole record: no report from anyone who installed it, no
bug, no praise (**anecdote**). The ZHA-only line is the friction worth
noticing, since he already had Z2M running. Three months earlier, on
2026-01-29, the same person posted `bharat/homeassistant-lockly` the same way
and got the same silence.

Lock firmware and module firmware are different numbers, and Z2M shows the
module's. tobor, 2024-10-27: "I z2m visas modulens byggdatum och
versionsnummer under enhetsinformationen. 20240625 har versionsnummer 4.7.79.
Det är firmwaren i modulen som visas, inte låsets" (**measured**, he is
reading his own device page). Walle85 and toka read 4.5.24 for the same
period out of Homey and take it for the lock's. Nobody has both numbers side
by side, so which one the 4.x ladder in
[hardware-generations.md](hardware-generations.md) belongs to rests on this
one reading.

A Code Pro reports mains power over Zigbee. Scuttle, 2026-07-15 in
573457, on Z2M: `Read result of 'genBasic': {"powerSource":4}`, and 4 is DC
source where a battery device owes 3 (**measured**, the log line is pasted).
This is the same defect the Z2M converter papers over with
`device.powerSource = "Battery"` in `configure`
([upstream-status.md](upstream-status.md)), now seen first-hand on a Code Pro
rather than inferred from the converter.

Standby current, measured with a meter. Walle85, 2024-02-06: about
1 mAh per day, roughly 40 µA, with the Zigbee module removed (**measured**,
photographed, though the photos are behind the forum's login wall). He never
posted the figure with the module fitted, which is the number that would
matter.

Two gateway hardware revisions. Balob got a dead gateway replaced in
January 2025 and the replacement "hade ett nytt utseende"; MangeSwe in July
2025 bought one with a grey top while nimly.se pictured an all-white one
(**anecdote**, both). Neither photographed it and nobody named a model, so
this is one more sighting of the two-hub family in
[app-architecture.md](nimly-connect-app/app-architecture.md), not evidence
about which is which.

Bluetooth: three questions, no answers, in three years. Asked 2023-08-23,
2024-08-17 and in passing in 2024-01. The only response is anis16 on
2023-10-11 relaying a support phone call: BLE is in the lock but not yet
supported by the app, and the app goes through the gateway only
(**relayed**). Nobody has scanned, paired or sniffed anything, and unloc is
not mentioned once in 621 posts.

Deleting a guest in the app does not delete their fingerprint. bjorsi,
2024-09-26, tested it deliberately: he enrolled a finger on a guest user, the
app claimed no fingerprint had been added, the finger opened the door anyway,
he deleted the user, and the finger kept working (**measured**, his own
test). Nobody replied. If that still holds it is a security hole in the
vendor's own credential handling, and it is the strongest single finding in
the thread.

The vendor's position on Home Assistant flipped. 2025-09-05,
maskeradeproggaren after contacting Nimly: they will neither document the
lock for the community nor build an integration themselves. 2025-12-08, the
same person: Nimly "verkar ändrat sig" and official HA support is coming
"i början av nästa år" (**relayed**, both). Nothing had arrived by the
thread's last post on 2026-09-18.

2FA is not two factors, confirmed by the vendor twice. Enabling it
requires a code alongside a fingerprint or tag, but any user code, the master
code included, still opens the door alone. Walle85 pasted his support ticket
in full on 2025-01-01 and the reply concedes the point without promising a
fix. PeMa82 got the same answer in November 2023. Certification for Code Pro
class 3 requires 2FA on, which makes the gap worth knowing about rather than
just an annoyance.

Programming is only possible from the outside panel, confirmed by support
2026-06-01 after a user could not change his master code from the inside
keypad. It is not in the manual.

The Code Pro has no thumbturn and the Code's is not mechanical. mrmlz
pulled the batteries and tested: with the lock dead the thumbturn moves but
does nothing, and the door stayed locked (**measured**, 2026-08-20).

Nothing in the three threads contradicts anything written in this repo.

## What does not exist anywhere

Listing this is as much the point of the sweep as the findings. None of the
following could be found in any forum, blog, video or comment thread:

- A BLE scan, advertisement dump or GATT listing of any lock in this family
  by anyone other than aridder/nimly-manager.
- A teardown photo showing the module's PCB at chip level. The closest is
  smartahemtest.se, which photographs the opened inside unit with the module
  fitted, at a distance that resolves nothing.
  <https://www.smartahemtest.se/djupgaende-tester/nimly-touch-pro-black>
- Any FCC internal photo set for ZMNC010.
- A first-hand account of using unloc with one of these locks. Documented
  only by unloc and by the vendor.
- Anyone with shell, UART or root on a Connect Bridge. Develco's MGW211
  material calls Squid.link an open Linux platform and mentions SSH, but no
  user has reported getting in.
- Any over-the-air firmware update.
- Anyone telling module generations apart by silkscreen, revision number or
  any visible mark. Users tell them apart by behaviour only, so the
  Ember/Datek against Nordic/E-Life split in `docs/hardware-generations.md`
  is ours alone.
- Anyone who has reached the Connect Gateway or Connect Bridge from Home
  Assistant, Homey, openHAB or Hubitat, by any route. Two asked, none
  answered.
- Anyone who has joined a non-Onesti Zigbee device to either hub, or tried.
  The app's own configuration allows it on the older hub, so the silence is a
  gap in the record rather than a no.
- A "pro" hub of any kind. Not on the vendor's sites, at a retailer, in a
  manual or in the app, which carries exactly two gateway models.
- Any Reddit discussion, in any subreddit, in any language.

## Sources

Every thread below is archived locally and dated, with 62 GitHub issues and
PRs and the vendor's pages. What exists, when it was read and how big it was
is the Living sources table in [docs/manuals/README.md](manuals/README.md);
the content is gitignored. Threads found and not quoted above are in that
table too, among them nine more Homey threads (auto-relock, child lock,
flows, PIN by flow, the gateway) and three smaller Home Assistant ones.

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
- byggahus.se, "Nimly Zigbee - Z2M eller ZHA?" (543716), 7 posts, 2-3 March
  2025, read in full on 2026-09-20,
  <https://www.byggahus.se/forum/threads/nimly-zigbee-z2m-eller-zha.543716/>
- byggahus.se, "Nimly Touch / Touch Pro -tråd" (497166), 592 posts over 40
  pages, 2023-08-21 to 2026-09-18, read in full on 2026-09-20,
  <https://www.byggahus.se/forum/threads/nimly-touch-touch-pro-trad.497166/>
- byggahus.se, "Nimly Code / Code Pro -tråd" (573457), 22 posts, 2026-04-08
  to 2026-09-20, read in full on 2026-09-20,
  <https://www.byggahus.se/forum/threads/nimly-code-code-pro-trad.573457/>
- sweclockers.com, "Homey Pro med Eufy och Nimly" (thread 1713551), 2 posts,
  April 2024, read in full on 2026-09-20,
  <https://www.sweclockers.com/forum/trad/1713551-homey-pro-med-eufy-och-nimly>
- nimly.se, Connect Module installation guide, file dated 2024-10-23,
  <https://nimly.se/wp-content/uploads/2024/10/EN-Connect-Module-Installation-Guide-231024-bluetooth-app-and-nimly-connect.pdf>
- App Store, nimly BLE, Easy Access AS, <https://apps.apple.com/no/app/nimly-ble/id6451232924>
- help.unloc.app, "How to install Nimly Touch Pro/Touch/Code/Indoor",
  updated 2024-10-11

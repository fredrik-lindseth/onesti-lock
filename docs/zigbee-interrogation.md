# Interrogating the lock over Zigbee

Almost everything this repo says about the lock's Zigbee side comes from a vendor document written in January 2021, from other people's locks, or from reading attributes we assumed were there. The device can be asked directly: ZCL has Discover Attributes (0x0C) and Discover Commands Received and Generated (0x11 and 0x13), and every cluster on endpoint 11 can list what it has.

This is the runbook for doing that in one sitting. `scripts/interrogate_lock.sh` runs it; this page says why each block exists, what its answer decides, and how the two blocks that bring back plaintext PIN codes are handled.

Nothing here writes to the lock. No Set PIN Code, no Clear PIN Code, no lock or unlock, and no command to the unknown 0xFEA2 cluster, whose command set nobody has seen and which would be fired blind.

## What it needs first

The lock has to answer at all. Unsolicited reports from the lock have not worked since the re-pairing; every Door Lock report in the log arrived as a side effect of a command from Home Assistant. That does not block this run, which is all commands from Home Assistant, but a lock that is off the network blocks it completely. `scripts/interrogate_lock.sh check` is the first step.

ZHA Toolkit. ZHA itself cannot send a Discover Attributes request, and its device dialog only offers the attributes the quirk declares, which is the guessing this run is meant to replace. [mdeweerd/zha-toolkit](https://github.com/mdeweerd/zha-toolkit) has it, as `zha_toolkit.scan_device`, along with `attr_read`, `zcl_cmd`, `binds_get` and `conf_report_read`. It is a HACS custom repository and a restart on the production Home Assistant, so installing it is a decision. Without it, only a small part of block B is possible by hand through ZHA's own dialog, and blocks A, C and D are not possible at all.

The quirk's PIN sensor off. `sensor.onesti_products_as_nimlypro_last_pin_code` belongs to the stock ZHA quirk and shows the last code in plaintext, in the state machine and in the recorder. Disable the entity before block A or C, and purge its history afterwards.

## Handling the answers

Two blocks bring back PIN codes in plaintext, for two different reasons, and both are planned for.

`scan_device` does not only discover: for every attribute it finds with the read bit set, it reads the value, in chunks of four, and writes them all into `/config/scans/<model>_..._scan_results.txt`. Attribute 0x0101 is the last PIN used, so the scan file is a PIN-bearing file, and `interrogate_lock.sh collect` blanks every `attribute_value` in it before printing. The scan is read for structure; the values we want come from the named reads in blocks B1 and B2, none of which touches 0x0101.

Get PIN Code answers with the code itself. `zcl_cmd` hands the response to the toolkit's event data, and the only way to see it is the zigpy debug log, so block C turns `zigpy.zcl` debug on for its own duration and off again at the end. That puts plaintext codes in `/config/home-assistant.log` and nowhere else: no state is written, so the recorder never sees them, and the toolkit's `event_done` and `state_id` options, which would put them on the bus or in a state, are unused on purpose. `collect` masks digit runs of four and up, the same floor as `redact.py`, before anything crosses the network.

Purging is part of the run: `interrogate_lock.sh purge` deletes the scans and the CSV, truncates `/config/home-assistant.log` and removes the rotated copy next to it, then greps what is left and says whether anything still matches. The whole log goes rather than the matching lines: Home Assistant holds the file open, so it can be truncated in place but not rewritten, and it is the file a backup takes and the one behind Download full log, so a routine backup right after a `pins` run would otherwise carry every code. Nothing raw is committed to this repo. What goes into `docs/zigbee-protocol/zigbee-captures.md` afterwards is frames and values with the PIN bytes scrubbed, as the existing captures there are.

## The blocks

Each block is meant to finish inside one awake window. The radio sleeps, the parent router throws queued frames away after 7.68 seconds, and the only way to keep the lock awake is someone at the door entering code + `#` every ten seconds, so the blocks are ordered cheapest first: if the window closes early, the cheap answers are already in.

| Block | Command | Frames | Awake time |
| ----- | ------- | ------ | ---------- |
| B1 Basic and OTA versions | `basic` | 7 reads | under a minute |
| D Bindings and reporting | `bindings` | 3 requests | under a minute |
| A Discovery | `discover` | 60-150, two passes | two to four minutes |
| B2 Door Lock attributes | `doorlock` | 13 reads | about a minute |
| C PIN walk | `pins` | one per slot, 21 by default | two to three minutes |

Retries are set with `tries` (default 10 in the script), so a frame lost between two keypresses is repeated rather than fatal. That is also why the frame counts above are a floor.

### B1: `interrogate_lock.sh basic`

Basic 0x0001 ApplicationVersion, 0x0002 StackVersion, 0x0003 HWVersion, 0x0006 DateCode, 0x0007 PowerSource and 0x4000 SWBuildID, then the OTA cluster's 0x0002 CurrentFileVersion.

SWBuildID is the one that matters: the date code cannot place the lock in the firmware ladder, because 20240625 covers 4.7.79, 4.7.98 and 4.8.01 alike. PowerSource is a claim from the Home Assistant forum that the lock presents itself as mains powered, which would explain both the missing battery percentage and a coordinator that does not queue for it. CurrentFileVersion is the number ZHA shows as `sw_version 0x00000000`; reading it raw says whether that zero is real.

OTA is a client cluster on the lock, so the read may come back unsupported. That is an answer too.

### D: `interrogate_lock.sh bindings`

A ZDO Mgmt_Bind_req for the lock's own binding table, and Read Reporting Configuration for `lock_state` (0x0000) and for the operation event (0x0100, with manufacturer code 0x1234).

The log already shows the coordinator binding the Door Lock cluster and the lock answering SUCCESS to Configure Reporting, three times, while no report followed. These three requests ask the lock what it thinks it stored. If the binding and the intervals are there and reports still do not arrive, the fault is in the firmware and no further reconfigure will help. If 0x0100 answers a reporting configuration at all, it is reportable and can be configured by hand, which ZHA never does.

### A: `interrogate_lock.sh discover`

`scan_device` over endpoint 11: 0x0000 Basic, 0x0001 Power Configuration, 0x0003 Identify, 0x0004 Groups, 0x0005 Scenes, 0x0101 Door Lock, 0xFEA2, and the outgoing 0x0019 OTA. Two passes, because 0x0100 and 0x0101 are manufacturer-specific and a plain discovery will not list them; the second pass sends manufacturer code 0x1234.

The toolkit walks the discovery in pages of 16 and asks for commands received and commands generated separately, which is the three requests this block is about. What comes back is, per attribute, the id, the data type and the access bits, and per command, the id and the argument list.

Both passes can come back empty or refused: plenty of small stacks answer Discover Attributes with a failure status. That is a finding, and should be written down as one.

### B2: `interrogate_lock.sh doorlock`

The Door Lock attributes the 2021 vendor spec documents: 0x0000 LockState, 0x0001 LockType, 0x0002 ActuatorEnabled, 0x0011 NumberOfTotalUsersSupported, 0x0012 NumberOfPINUsersSupported, 0x0013 NumberOfRFIDUsersSupported, 0x0017 MaxPINCodeLength, 0x0018 MinPINCodeLength, 0x0019 MaxRFIDCodeLength, 0x001A MinRFIDCodeLength, 0x0023 AutoRelockTime, 0x0024 SoundVolume, and 0x0100 with the manufacturer code. Not 0x0101.

If block A succeeded this block is partly redundant, since the scan read the values too. It is kept separate because it is short, survives a refused discovery, and its CSV is the one file with values in it that is safe to read without masking.

### C: `interrogate_lock.sh pins [slot...]`

Get PIN Code (0x06) for a sampled set of slots. Run one slot first, `interrogate_lock.sh pins 3`, and read the log before committing to the rest: the vendor spec lists only Lock, Unlock, Set PIN Code and Clear PIN Code as supported, so the lock may well answer UNSUP_CLUSTER_COMMAND. If block A worked, its command list has already said so, and this block can be skipped or confirmed in one frame.

The default walk is 0, 1, 2, 3, 4, 5, 10, 49, 50, 51, 99, 100, 255, 256, 300, 799, 800, 803, 899, 999, 1000. Not a sweep of 0-999: every slot is a round trip on a battery radio, and these are the slots that decide something. Note per slot the status byte and, without writing the code down, whether a code came back and how many digits it had.

## What each answer decides

| Reading | What it settles |
| ------- | --------------- |
| Discover Commands Received on 0x0101 | Whether Get PIN Code exists on this firmware, and whether the 2021 spec's command list still holds. Decides whether block C is possible |
| Discover Attributes on 0x0101, manufacturer pass | Whether the firmware declares 0x0100 and 0x0101, and with which access bits. A reportable 0x0100 would mean the missing reports can be configured by hand |
| Discover on 0xFEA2 | What "EA v2" contains. The vendor named the cluster and said nothing more, and nobody has read it |
| Basic 0x4000 SWBuildID (with 0x0001, 0x0003, 0x0006) | Places this lock in the firmware ladder collected from seven other users, which decides whether the BLE track is alive on it and whether the reporting trouble sits in a firmware range others call unusable |
| Basic 0x0007 PowerSource | Whether the lock claims to be mains powered, which would explain the missing battery percentage and how the coordinator treats it |
| OTA 0x0002 CurrentFileVersion | Whether ZHA's zero is the lock's own answer, and gives the OTA track its first real version number |
| Door Lock 0x0012 / 0x0017 / 0x0018 | Confirms the capability values the integration enforces, from the lock rather than the vendor document |
| Door Lock 0x0023 AutoRelockTime | Whether it is seconds, as ZCL says, or the boolean the vendor spec describes. Decides whether auto-relock is something the integration could expose |
| Binding table and reporting configuration | Whether the reporting that never arrives is stored on the lock or was forgotten, the difference between a configuration problem and a firmware problem |
| Get PIN Code on slots 0-5 | Where the master slots end on this model, today a per-lock setting the user has to guess |
| Get PIN Code on 49, 50, 51 | Whether the 50-user ceiling is real, and how the lock refuses a slot above it |
| Get PIN Code on 255, 256, 300 | Whether the slot number is 8-bit or 16-bit, which the capture file has flagged as an assumption since March |
| Get PIN Code on 799, 800, 803, 899 | Whether the BLE range and the ZCL range are the same storage. If slot 800 holds a code it is one store with an offset; if it is empty or refused it is not |
| Get PIN Code on 1000 | What an out-of-range slot answers, which the integration's own ceiling should mirror |

## Afterwards

Write the raw frames into `docs/zigbee-protocol/zigbee-captures.md` with the PIN bytes scrubbed, the firmware fields into `docs/hardware-generations.md`, and anything the discovery says about slots into `docs/slot-numbering.md`. If the discovery contradicts `docs/zigbee-protocol/elife-module-spec.md`, the measurement wins and the disagreement is noted there, as that page already says.

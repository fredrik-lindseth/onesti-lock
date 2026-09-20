# ESPHome BLE debug proxy

`ble-debug-proxy.yaml` is the firmware for an ESP32 Bluetooth proxy sitting by
the front door, next to the lock. It exists for two jobs in this project:

1. See whether the lock advertises at all. The lock broadcasts 8 bytes of
   service data under the 16-bit UUID `0xFD00`
   (`docs/nimly-ble-app/ble-library.md`, "Finding the lock"). The build logs
   every `0xFD00` frame with address, RSSI and hex payload, and publishes
   counters for them to Home Assistant, so "the lock is quiet" and "our
   listener never ran" can be told apart.
2. Later, carry real BLE sessions. `bluetooth_proxy` is active with three
   connection slots, so Home Assistant can reach the lock through this device
   instead of needing a Bluetooth adapter on the HA host. Nothing has connected
   to the lock through it yet.

It is a debug build, not the stock bluetooth-proxy firmware: it drops the
`http_request` update entity (which would offer the stock image and overwrite
this build), `improv_serial`, `dashboard_import` and the factory reset button,
and adds diagnostics, persistent counters and an ESP-IDF core dump partition.

## The board

Tested on an ESP32-C3 Super Mini. `esptool` reports a bare ESP32-C3 in QFN32,
revision v0.4, with embedded 4MB XMC flash, and the only USB port is the chip's
own USB-Serial/JTAG. A DevKitM-1 or DevKitC would carry an ESP32-C3-MINI-1
module and a second port on a CP2102N bridge, which does not enumerate here.

`output_power` is `8.5dB` rather than the 20dB default because of that board.
Cheap C3 boards with a chip antenna commonly brown out or detune at full
transmit power, and the device had been dropping off the network. On a board
with a proper module, 15dB is a reasonable value to try instead.

Two other settings follow from the C3 having one radio for both BLE and Wi-Fi:
`power_save_mode` stays at `light`, since ESP-IDF coexistence relies on modem
sleep, and the BLE scan uses `interval: 320ms` with `window: 120ms` rather than
a continuous scan, which starves Wi-Fi on this chip.

## secrets.yaml

The config reads four secrets, all under the standard ESPHome names:

```yaml
wifi_ssid: "..."
wifi_password: "..."
api_encryption_key: "..."   # base64, 32 bytes
ota_password: "..."
```

Home Assistant's own `/config/esphome/secrets.yaml` already has the Wi-Fi pair.
Do not commit a `secrets.yaml` here.

The board sits by the front door with a BLE scanner aimed at the lock, and the
ready-made firmware it replaces had neither key nor OTA password, so anyone on
the LAN could read it or reflash it. This build requires both.

Make the key once and put both into that `secrets.yaml`:

```bash
python3 -c 'import base64, os; print(base64.b64encode(os.urandom(32)).decode())'   # api_encryption_key
python3 -c 'import secrets; print(secrets.token_hex(16))'                          # ota_password
```

Then add both to `/config/esphome/secrets.yaml` on the Home Assistant box, so
the file the flash reads is the same one every ESPHome device there uses.

The first flash with the key is a normal OTA: the device is still running the
old firmware, which asks for no OTA password, so nothing is needed to get in.
Afterwards Home Assistant loses the connection and the ESPHome integration
raises "Device requires encryption key" or an Invalid authentication repair.
Open it and paste `api_encryption_key`. The config entry, the device and every
entity id survive, since the device name is unchanged. Later OTAs use
`ota_password`, which `esphome run` reads from the same `secrets.yaml`.

## Building and flashing

ESPHome is not a dependency of this repository. Built and flashed with 2026.9.0
last, and `min_version` in the YAML is only a floor. Use a throwaway virtualenv
and a throwaway working directory, because `secrets.yaml` has to sit next to
the config.

ESPHome 2026.9.0 requires Python 3.12 or newer and refuses 3.15 and up
(`Requires-Python: >=3.12,<3.15`). 3.11 was dropped in 2026.7.0. Built on 3.14
last, which is what a current Homebrew `python3` gives:

```bash
python3 --version     # must be 3.12, 3.13 or 3.14
python3 -m venv /tmp/esphome-venv
/tmp/esphome-venv/bin/pip install esphome==2026.9.0
mkdir -p /tmp/bleproxy-flash
cp tools/esphome/ble-debug-proxy.yaml /tmp/bleproxy-flash/proxy.yaml
# copy the Wi-Fi secrets from Home Assistant
scp ha-local:/config/esphome/secrets.yaml /tmp/bleproxy-flash/secrets.yaml
```

**The first flash has to go over USB.** This config adds a `coredump`
partition, and ESPHome shrinks `app0`/`app1` to pay for it. An OTA update only
writes an app slot, never the partition table, so an OTA from a build without
the partition would leave the table unchanged and the core dump would land
nowhere. Connect the board and:

```bash
ls /dev/cu.*      # find the port, e.g. /dev/cu.usbmodem2101
/tmp/esphome-venv/bin/esphome run /tmp/bleproxy-flash/proxy.yaml --device /dev/cu.usbmodem2101
```

Once the partition table is in place, later changes go over the air:

```bash
/tmp/esphome-venv/bin/esphome run /tmp/bleproxy-flash/proxy.yaml --device <the proxy's address>
```

The address is the board's DHCP reservation in UniFi.

`esphome upload` does not compile; only `esphome run` and `esphome compile` do.
Uploading after an edit without compiling flashes the previous firmware and
looks like the edit had no effect.

Delete `/tmp/bleproxy-flash` afterwards, since it holds the Wi-Fi password.

## Home Assistant: set scanning mode to Active

The config asks for an active scan, but Home Assistant overrides it at runtime.
Under Settings > Devices & Services > ESPHome > the proxy > Configure, set
**Bluetooth scanning mode** to **Active**. The default, Auto, scans passively
and only does active sweeps for four minutes after a connection and then every
twelve hours, which is not enough to say whether the lock advertises. The
change needs no reflash; the serial log confirms it with
`Setting scanner mode to active`.

## Seeing every advertisement during a session

At `DEBUG` the log shows our own `0xFD00` filter and nothing else, so a quiet
log does not mean a quiet radio. `esp32_ble_tracker`'s per-advertisement
`gap_scan_result` line moved from `DEBUG` to `VERY_VERBOSE` in ESPHome 2025.9.0
([esphome#10917](https://github.com/esphome/esphome/pull/10917)). The control
counters ("Service data 16-bit advertisements" and "Control 0xFCF1
advertisements") prove the scanner is alive, but they say nothing about what
the lock sends.

Two switches turn that on mid-session, no reflash, both off after every boot
and both turning themselves off again after six minutes (`log_window` in the
YAML). Flip a switch again to restart the countdown.

- **Raw advertisement log**: our own dump, one block per advertisement from
  every device in range, with address, address type, RSSI, advertised name,
  every service UUID, every service data payload in hex and every manufacturer
  data payload in hex. This is the one to use while the lock's battery is
  pulled. Its lines are tagged `raw_adv` at `DEBUG`.
- **BLE tracker verbose log**: raises the `esp32_ble_tracker` tag to
  `VERY_VERBOSE` at runtime through `logger.set_level`, which brings back
  `gap_scan_result` plus the scanner's internal state. Louder and harder to
  read than the switch above; reach for it when even the raw dump stays
  silent, to see whether the radio delivers anything at all.

On Fredrik's instance the entities are
`switch.stuen_esp32_c3_mini_bt_proxy_raw_advertisement_log` and
`switch.stuen_esp32_c3_mini_bt_proxy_ble_tracker_verbose_log`.

The runtime switch only works because `logger:` compiles `VERY_VERBOSE` into
the image (`level: VERY_VERBOSE`) while printing at `DEBUG`
(`initial_level: DEBUG`), with `runtime_tag_levels: true` so a single tag can
be raised later. Anything above `level:` is compiled out and can never be
switched on. The price is flash: 79.4 % against 77.5 % for the same config with
a `DEBUG` ceiling, roughly 34 KB. RAM is unchanged at 44.6 %. A suppressed log
call costs a level compare and returns before any formatting, so the ceiling
does not slow down the scan path.

Expect one warning line at every boot:

```
[W][logger:251]: VERY_VERBOSE logging is active — significant performance impact, short-term debugging only
```

That is about the compiled ceiling, not about what is being printed, and it is
the price of having the switch at all.

**What is safe to leave on.** Passive scanning with both switches on is fine;
that is what the session at the lock is for. A GATT session through the proxy
is not. Heavy logging with Home Assistant subscribed to the log stream is the
exact load that turned a 185 ms characteristic write into a 19 second failure
in [esphome#16036](https://github.com/esphome/esphome/pull/16036), on a chip
that shares one radio between BLE and Wi-Fi like this C3 does. Turn both off
before anything connects to the lock. If the log drowns
`home-assistant.log`, read it over USB or the API with `esphome logs` instead
and turn off the log subscription on the ESPHome entry in Home Assistant.

## Persistent counters

Diagnostics that only live in RAM are gone by the time anyone looks at an
outage. These globals are stored in NVS and restored at boot, each with its own
diagnostic entity in Home Assistant:

- **Lock FD00 total**: `0xFD00` advertisements across all boots. The separate
  "Lock FD00 advertisements" is the counter for the current boot.
- **Lock FD00 last** and **Lock FD00 RSSI**: the last sighting, put back on
  the live entities at boot so they are not `unknown` after a restart.
- **Lock FD00 age**: how long since the last sighting, measured in **Runtime
  total**, the seconds the device has been powered summed over every boot.
  There is no RTC and no time source that survives a power cut, so time spent
  powered off is not counted. It answers "did it go quiet before or after the
  outage", not "at what o'clock".
- **Boot count**, **Uptime before last reset**, **Reset reason before last**:
  a boot count that climbs without anyone pressing restart means unintended
  reboots, and the other two say how far the previous boot got and why it
  ended.
- **WiFi signal minimum**, **WiFi signal stored**, **WiFi disconnects**,
  **API disconnects**: the Wi-Fi counter only counts losing an established
  connection; a failed association during connect does not increment it.

Over USB, `esphome logs` prints one line tagged `persist` right after boot with
everything read back, for example:

```
restored: boots=9 fd00_total=0 last_rssi=0 runtime_total=137s prev_uptime=3s prev_reset=USB peripheral wifi_drops=0 api_drops=0 wifi_rssi_min=-60
```

Each persisted global is a polling component on a 60 s interval that writes
only when the value changed. Do not lower that interval: the hot path (every
BLE advertisement) writes to RAM and relies on the throttle to keep flash wear
down.

One trap worth knowing: the reset reason cannot be read in `on_boot`. The debug
component publishes it from `dump_config()`, which runs after every `on_boot`
trigger, so the state is still empty there. The config writes it from an
`on_value` hook on the reset reason text sensor instead.

## Core dumps

On a panic, ESP-IDF writes an ELF core dump to the `coredump` partition. Pull
it off the chip over USB and decode it:

```bash
python -m esptool --chip esp32c3 -p /dev/cu.usbmodem2101 read-flash 0x3E0000 0x10000 coredump.bin
esp-coredump --chip esp32c3 info_corefile -t raw -c coredump.bin \
    .esphome/build/<name>/.pioenvs/<name>/firmware.elf
```

The offset moves whenever a partition size changes. The device prints the whole
table at boot (`[C][debug:159]: Partition table:`), so read it there rather
than trusting the number above.

An erased partition reads back as all `0xFF`, and `esp-coredump` answers
`Core dump version "0xffff" is not supported`. That is the healthy case, and it
also proves the read path works.

Two requirements for decoding a real dump: the ELF has to be the exact build
that crashed, or the backtrace is fiction, and unwinding wants a RISC-V gdb on
`PATH`:

```bash
PATH=~/.platformio/packages/tool-riscv32-esp-elf-gdb/bin:$PATH
```

The ELF is 20 MB, so it is kept out of git: `tools/esphome/build/` is ignored,
and the ELF of whatever build is on the device lives there, named after the
build time (`firmware-<YYYYMMDD-HHMM>.elf`). ESPHome does not build
reproducibly, so rebuilding the same YAML later gives a different ELF, and a
dump from the flashed build can only be read with the ELF that was flashed.
Copy it out of `.esphome/build/<name>/.pioenvs/<name>/firmware.elf` right after
every flash, and delete the old one once nothing on any device matches it.

The PyPI package and its entry point are both called `esp-coredump`, not
`espcoredump.py`. Its other mode, reading straight off the serial port
(`esp-coredump -p <port> info_corefile <elf>`), refuses to run without a full
ESP-IDF environment, so the two-step route above is the one that works.

Erase a dump once it has been read, so the next crash is unambiguous:

```bash
python -m esptool --chip esp32c3 -p /dev/cu.usbmodem2101 erase-region 0x3E0000 0x10000
```

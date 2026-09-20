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

The config reads only two secrets, both the standard ESPHome names:

```yaml
wifi_ssid: "..."
wifi_password: "..."
```

Home Assistant's own `/config/esphome/secrets.yaml` already has them. There is
no API encryption key and no OTA password in this build, matching what the
device ran before. Do not commit a `secrets.yaml` here.

## Building and flashing

ESPHome is not a dependency of this repository. Built and flashed with 2026.9.0
last; nothing in the config has been renamed or deprecated since 2026.4.0, and
`min_version` in the YAML is only a floor. Use a throwaway virtualenv and
a throwaway working directory, because `secrets.yaml` has to sit next to the
config:

```bash
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
/tmp/esphome-venv/bin/esphome run /tmp/bleproxy-flash/proxy.yaml --device 192.168.3.125
```

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

The PyPI package and its entry point are both called `esp-coredump`, not
`espcoredump.py`. Its other mode, reading straight off the serial port
(`esp-coredump -p <port> info_corefile <elf>`), refuses to run without a full
ESP-IDF environment, so the two-step route above is the one that works.

Erase a dump once it has been read, so the next crash is unambiguous:

```bash
python -m esptool --chip esp32c3 -p /dev/cu.usbmodem2101 erase-region 0x3E0000 0x10000
```

#!/usr/bin/env bash
# Ask the lock what it actually has, over Zigbee, instead of reading the
# attributes we believe exist. Drives ZHA Toolkit on a running Home Assistant
# through the Supervisor API, one block per awake window.
#
#   scripts/interrogate_lock.sh check            prerequisites, sends nothing to the lock
#   scripts/interrogate_lock.sh basic            block B1: Basic + OTA version attributes
#   scripts/interrogate_lock.sh bindings         block D: binding table + reporting config
#   scripts/interrogate_lock.sh discover         block A: Discover Attributes/Commands, ep 11
#   scripts/interrogate_lock.sh doorlock         block B2: named Door Lock attributes
#   scripts/interrogate_lock.sh pins [slot...]   block C: Get PIN Code walk (plaintext PINs)
#   scripts/interrogate_lock.sh collect          print the results, digits masked
#   scripts/interrogate_lock.sh purge            delete every raw result on the box
#   scripts/interrogate_lock.sh --dry-run <cmd>  print the service calls, send nothing
#
# Blocks are ordered cheapest-first on purpose: the lock sleeps, and each block
# has to finish inside one awake window (someone at the door typing code + #
# every ten seconds). `basic` and `bindings` are a handful of frames each;
# `discover` is the long one. Nothing here writes to the lock: no Set PIN Code,
# no Clear PIN Code, no lock or unlock, and no command to the unknown 0xFEA2
# cluster, whose commands would be invoked blind.
#
# PIN WARNING. Two blocks bring back PIN codes in plaintext:
#   - `discover`, because ZHA Toolkit's scan reads the value of every readable
#     attribute it discovers, and attribute 0x0101 is the last PIN used.
#   - `pins`, because a Get PIN Code Response carries the code itself.
# Their results stay on the Home Assistant box, in /config/scans and in the
# core log, and are read back through `collect`, which masks digit runs the way
# custom_components/onesti_lock/redact.py does. Run `purge` in the same session.
# Both blocks are why the run needs the quirk's PIN sensor disabled first;
# `check` looks for it.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HA="$REPO/scripts/ha.sh"
IEEE="${LOCK_IEEE:-f4:ce:36:88:61:9c:f4:6f}"
ENDPOINT="${LOCK_ENDPOINT:-11}"
# 0x1234, the placeholder manufacturer code in the node descriptor. The custom
# attributes 0x0100 and 0x0101 are manufacturer-specific and stay invisible to
# a plain discovery, so the manufacturer pass is a separate call.
MANF="${LOCK_MANF:-4660}"
# The lock is an EndDevice that sleeps; a single try loses the frame between
# two keypresses at the door. ZHA Toolkit repeats the packet this many times.
TRIES="${LOCK_TRIES:-10}"
CSV="onesti-interrogation.csv"
DRY_RUN=0

QUIRK_PIN_SENSOR="${QUIRK_PIN_SENSOR:-sensor.onesti_products_as_nimlypro_last_pin_code}"

# Slots worth asking about. Not 0-999: every slot is one round trip on a
# battery radio. These are the boundaries that decide something. 0-5 is the
# master/user split, 49-51 the NumberOfPINUsersSupported ceiling, 255-256 the
# 8-bit boundary behind the 16-bit slot width question, 300 the slot the
# capture plan wants, 800-899 the BLE range, 1000 the first illegal slot.
DEFAULT_SLOTS=(0 1 2 3 4 5 10 49 50 51 99 100 255 256 300 799 800 803 899 999 1000)

usage() { grep '^#' "$0" | sed 's/^# \{0,1\}//'; }

say() { printf '\n== %s\n' "$*"; }

call() { # call <domain.service> <json> [label]
  local service="$1" json="$2" label="${3:-}"
  if [ "$DRY_RUN" = 1 ]; then
    printf 'CALL %s %s\n' "$service" "$json"
    return 0
  fi
  [ -n "$label" ] && printf -- '-> %s\n' "$label"
  "$HA" call "$service" "$json"
}

remote() { # remote <command>
  if [ "$DRY_RUN" = 1 ]; then
    printf 'SSH %s\n' "$1"
    return 0
  fi
  "$HA" sh "$1"
}

attr_read() { # attr_read <cluster> <attribute> <label> [manufacturer]
  local cluster="$1" attribute="$2" label="$3" manf="${4:-}"
  local extra=""
  [ -n "$manf" ] && extra=",\"manf\":$manf"
  call zha_toolkit.attr_read \
    "{\"ieee\":\"$IEEE\",\"endpoint\":$ENDPOINT,\"cluster\":$cluster,\"attribute\":$attribute$extra,\"tries\":$TRIES,\"use_cache\":false,\"csvout\":\"$CSV\",\"csvlabel\":\"$label\"}" \
    "read $label"
}

cmd_check() {
  say "ZHA Toolkit installed?"
  remote 'ls -d /config/custom_components/zha_toolkit 2>/dev/null || echo "MISSING: install mdeweerd/zha-toolkit as a HACS custom repository, then restart HA"'
  say "Does the lock answer at all? (ZHA device state)"
  if [ "$DRY_RUN" = 1 ]; then
    printf 'SSH ha.sh states dorlasen\n'
  else
    "$HA" states dorlasen
  fi
  say "The quirk's PIN sensor must be disabled before block A or C"
  if [ "$DRY_RUN" = 1 ]; then
    printf 'SSH ha.sh state %s\n' "$QUIRK_PIN_SENSOR"
  else
    "$HA" state "$QUIRK_PIN_SENSOR" || true
  fi
  say "Old results still on the box?"
  remote 'ls -l /config/scans /config/csv 2>/dev/null || echo "(none yet)"'
}

cmd_basic() {
  say "Block B1: Basic cluster versions and the OTA file version"
  # 0x0001 ApplicationVersion, 0x0002 StackVersion, 0x0003 HWVersion,
  # 0x0006 DateCode, 0x0007 PowerSource, 0x4000 SWBuildID.
  attr_read 0 1 basic_app_version
  attr_read 0 2 basic_stack_version
  attr_read 0 3 basic_hw_version
  attr_read 0 6 basic_date_code
  attr_read 0 7 basic_power_source
  attr_read 0 16384 basic_sw_build_id
  # OTA Upgrade (0x0019) is a client cluster on the lock; 0x0002 is
  # CurrentFileVersion, the number ZHA shows as sw_version 0x00000000.
  attr_read 25 2 ota_current_file_version
}

cmd_bindings() {
  say "Block D: what the lock itself says about bindings and reporting"
  call zha_toolkit.binds_get \
    "{\"ieee\":\"$IEEE\",\"tries\":$TRIES}" "read the binding table (ZDO Mgmt_Bind_req)"
  # Does the lock remember the lock_state intervals it answered SUCCESS to?
  call zha_toolkit.conf_report_read \
    "{\"ieee\":\"$IEEE\",\"endpoint\":$ENDPOINT,\"cluster\":257,\"attribute\":0,\"tries\":$TRIES}" \
    "read reporting configuration for lock_state"
  # And does it claim 0x0100 is reportable at all?
  call zha_toolkit.conf_report_read \
    "{\"ieee\":\"$IEEE\",\"endpoint\":$ENDPOINT,\"cluster\":257,\"attribute\":256,\"manf\":$MANF,\"tries\":$TRIES}" \
    "read reporting configuration for the operation event 0x0100"
}

cmd_discover() {
  say "Block A: Discover Attributes (0x0C) and Discover Commands (0x11/0x13)"
  echo "This is the long one: every cluster on endpoint $ENDPOINT, two passes."
  echo "Keep the lock awake for the whole run. The scan READS every attribute"
  echo "it finds, 0x0101 included, so its file holds a PIN in plaintext."
  call zha_toolkit.scan_device \
    "{\"ieee\":\"$IEEE\",\"endpoint\":$ENDPOINT,\"tries\":$TRIES}" \
    "discovery, plain pass"
  call zha_toolkit.scan_device \
    "{\"ieee\":\"$IEEE\",\"endpoint\":$ENDPOINT,\"manf\":$MANF,\"tries\":$TRIES}" \
    "discovery, manufacturer pass (0x$(printf '%04X' "$MANF"))"
}

cmd_doorlock() {
  say "Block B2: named Door Lock attributes from the vendor spec"
  attr_read 257 0 doorlock_lock_state
  attr_read 257 1 doorlock_lock_type
  attr_read 257 2 doorlock_actuator_enabled
  attr_read 257 17 doorlock_total_users
  attr_read 257 18 doorlock_pin_users
  attr_read 257 19 doorlock_rfid_users
  attr_read 257 23 doorlock_max_pin_length
  attr_read 257 24 doorlock_min_pin_length
  attr_read 257 25 doorlock_max_rfid_length
  attr_read 257 26 doorlock_min_rfid_length
  attr_read 257 35 doorlock_auto_relock_time
  attr_read 257 36 doorlock_sound_volume
  # The operation event's current value carries no PIN, only slot, action and
  # source, so it is safe to read. 0x0101 is deliberately not read here.
  attr_read 257 256 doorlock_operation_event "$MANF"
}

cmd_pins() {
  local slots=("$@")
  [ ${#slots[@]} -gt 0 ] || slots=("${DEFAULT_SLOTS[@]}")
  say "Block C: Get PIN Code (0x06) for ${#slots[@]} slots, read-only"
  echo "Nothing is written. The answers carry PIN codes in plaintext and the"
  echo "only place they can be read is the zigpy debug log, so this block turns"
  echo "that log on, and 'collect' and 'purge' are part of the block, not"
  echo "optional follow-ups."
  call logger.set_level '{"zigpy.zcl":"debug","zigpy":"debug"}' "zigpy debug on"
  local slot
  for slot in "${slots[@]}"; do
    call zha_toolkit.zcl_cmd \
      "{\"ieee\":\"$IEEE\",\"endpoint\":$ENDPOINT,\"cluster\":257,\"cmd\":6,\"args\":[$slot],\"tries\":$TRIES}" \
      "get_pin_code slot $slot"
  done
  call logger.set_level '{"zigpy.zcl":"warning","zigpy":"warning"}' "zigpy debug off"
  echo "Now: scripts/interrogate_lock.sh collect, then purge."
}

# Masking happens on the box, so no PIN ever crosses the network. Two rules,
# because the two sources need different ones:
#   - a scan holds the value of every attribute it discovered, 0x0101 included,
#     so every value is blanked and the file is read for structure only;
#   - a log line holds the Get PIN Code answer, so digit runs of four and up go,
#     the same floor as redact.py. Slot numbers up to 999 survive that; slot
#     1000 does not, which is the one place the masking costs us something.
MASK_SCAN='s/("attribute_value": ).*/\1"<masked>",/'
MASK_LOG="s/b'[^']*'/b'****'/g; s/[0-9]{4,}/****/g"

cmd_collect() {
  say "Attribute reads (/config/csv/$CSV)"
  # No masking here: every attribute this script reads was named by hand and
  # none of them is 0x0101, so the CSV is the one place a date code survives.
  remote "cat /config/csv/$CSV 2>/dev/null || echo '(no csv yet)'"
  say "Discovery scans (/config/scans), attribute values blanked"
  remote "for f in /config/scans/*; do echo \"--- \$f\"; sed -E '$MASK_SCAN' \"\$f\"; done 2>/dev/null || echo '(no scans yet)'"
  say "Get PIN Code answers in the core log, digit runs masked"
  remote "ha core logs 2>/dev/null | grep -iE 'get_pin_code|user_id=|user_status' | tail -60 | sed -E \"$MASK_LOG\" || echo '(nothing in the log)'"
}

cmd_purge() {
  say "Deleting the raw results on the box"
  remote "rm -f /config/csv/$CSV /config/scans/* 2>/dev/null; echo 'scans and csv removed'"
  echo "The core log still holds the plaintext answers from block C."
  echo "Restart HA to rotate it, then delete the rotated copy:"
  echo "  ssh ha-local 'ha core restart'"
  echo "  ssh ha-local 'rm -f /config/home-assistant.log.1'"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    *) break ;;
  esac
done

cmd="${1:-}"; shift || true
case "$cmd" in
  check) cmd_check ;;
  basic) cmd_basic ;;
  bindings) cmd_bindings ;;
  discover) cmd_discover ;;
  doorlock) cmd_doorlock ;;
  pins) cmd_pins "$@" ;;
  collect) cmd_collect ;;
  purge) cmd_purge ;;
  *) usage; exit 1 ;;
esac

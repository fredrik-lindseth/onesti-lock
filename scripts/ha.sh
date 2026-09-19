#!/usr/bin/env bash
# Helper for talking to a Home Assistant instance over SSH during hardware
# tests. Uses the `ha-local` SSH alias by default (override with HA_SSH).
# No secrets: host and key live in ~/.ssh/config, the Supervisor token is read
# on the box from $SUPERVISOR_TOKEN inside the SSH add-on.
#
#   scripts/ha.sh states [filter]        entity states, optionally grep'd
#   scripts/ha.sh state <entity_id>      one entity: state + last_changed
#   scripts/ha.sh logs <pattern> [secs]  follow logs matching pattern (default 30s)
#   scripts/ha.sh grep <pattern> [n]     last n log lines matching pattern (default 40)
#   scripts/ha.sh call <domain.service> <json>   call a service
#   scripts/ha.sh debug [domains]        logger.set_level debug (default onesti+zha+zigpy)
#   scripts/ha.sh sh '<command>'         run an arbitrary command on the box
set -euo pipefail

HA_SSH="${HA_SSH:-ha-local}"
ssh_ha() { ssh -o IdentitiesOnly=yes -o ConnectTimeout=10 "$HA_SSH" "$@" 2>&1 | grep -v "^Warning: Identity" || true; }
api() { # api METHOD PATH [json]
  # The header uses double quotes so the remote shell expands the token; single
  # quotes would send $SUPERVISOR_TOKEN literally and the API answers 401.
  local method="$1" path="$2" data="${3:-}"
  local auth='-H "Authorization: Bearer $SUPERVISOR_TOKEN"'
  if [ -n "$data" ]; then
    ssh_ha "curl -s -X $method $auth -H 'Content-Type: application/json' -d '$data' http://supervisor/core/api/$path"
  else
    ssh_ha "curl -s $auth http://supervisor/core/api/$path"
  fi
}

cmd="${1:-}"; shift || true
case "$cmd" in
  states)
    filter="${1:-}"
    api GET states | python3 -c '
import json,sys
f=sys.argv[1] if len(sys.argv)>1 else ""
for s in sorted(json.load(sys.stdin),key=lambda x:x["entity_id"]):
    e=s["entity_id"]
    if not f or f.lower() in e.lower():
        print(f'"'"'{s["state"]:16.16} {e}  ({s["last_changed"][11:19]})'"'"')
' "$filter"
    ;;
  state)
    api GET "states/$1" | python3 -c '
import json,sys
s=json.load(sys.stdin)
print(s["state"],"|",s["entity_id"],"| changed",s["last_changed"][11:19])
a=s.get("attributes",{})
for k in ("friendly_name",):
    a.pop(k,None)
if a: print("  attrs:",json.dumps(a,ensure_ascii=False))
'
    ;;
  logs)
    pat="${1:-.}"; secs="${2:-30}"
    ssh_ha "timeout $secs ha core logs -f 2>/dev/null | grep -iE '$pat' | grep -ivE 'ezsp_counters|em_poller|cluster_poller|polling for updated' | head -40"
    echo "(fulgte $secs s)"
    ;;
  grep)
    pat="${1:-.}"; n="${2:-40}"
    ssh_ha "ha core logs 2>/dev/null | grep -iE '$pat' | grep -ivE 'ezsp_counters|em_poller|polling for updated' | tail -$n"
    ;;
  call)
    api POST "services/${1/./\/}" "${2:-{}}"; echo
    ;;
  debug)
    dom="${1:-custom_components.onesti_lock,zha,zigpy,zigpy.zcl}"
    json=$(python3 -c 'import json,sys;print(json.dumps({d:"debug" for d in sys.argv[1].split(",")}))' "$dom")
    api POST services/logger/set_level "$json"; echo " (debug: $dom)"
    ;;
  sh)
    ssh_ha "$1"
    ;;
  *)
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
    ;;
esac

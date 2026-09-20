#!/usr/bin/env bash
# Deploy this working tree's integration to a running Home Assistant over SSH.
# Uses the `ha-local` SSH alias by default (override with HA_SSH).
#
#   scripts/deploy_ha.sh deploy              back up, copy, swap, check, restart, verify
#   scripts/deploy_ha.sh restore <tarball>   put a backup tarball back and restart
#   scripts/deploy_ha.sh --dry-run deploy    print every command, run none of them
#
# The order is the point: the backup tarball exists before anything on the box
# is touched, the new files are complete in a staging directory before the
# installed integration is removed, and the removal and the move are one
# command so a dropped connection cannot leave /config without the component.
set -euo pipefail

HA_SSH="${HA_SSH:-ha-local}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPONENT="onesti_lock"
LOCAL_DIR="$REPO/custom_components/$COMPONENT"
REMOTE_CC="/config/custom_components"
REMOTE_DIR="$REMOTE_CC/$COMPONENT"
STAGING="$REMOTE_DIR.new"
ENTITY_FILTER="${ENTITY_FILTER:-sensor.dorlasen_}"
DRY_RUN=0

# Same connection flags as scripts/ha.sh: IdentitiesOnly stops ssh from
# offering every key in the agent, which the box answers with "Too many
# authentication failures". Unlike ha.sh's wrapper this one keeps the exit
# status, because each step decides whether the next one may run at all.
ssh_ha() { ssh -o IdentitiesOnly=yes -o ConnectTimeout=10 "$HA_SSH" "$@"; }

die() { echo "deploy_ha: $*" >&2; exit 1; }

remote() { # remote <command>
  echo "+ ssh $HA_SSH '$1'"
  if [ "$DRY_RUN" = 0 ]; then
    ssh_ha "$1"
  fi
}

push_staging() { # tar the component over the wire, without __pycache__
  local cmd="tar czf - -C $REPO/custom_components --exclude __pycache__ --exclude '*.pyc' $COMPONENT"
  echo "+ $cmd | ssh $HA_SSH 'tar xzf - -C $STAGING --strip-components=1'"
  if [ "$DRY_RUN" = 0 ]; then
    tar czf - -C "$REPO/custom_components" --exclude __pycache__ --exclude '*.pyc' "$COMPONENT" \
      | ssh_ha "tar xzf - -C $STAGING --strip-components=1"
  fi
}

deploy() {
  [ -f "$LOCAL_DIR/manifest.json" ] || die "no integration at $LOCAL_DIR"
  local files
  files="$(find "$LOCAL_DIR" -name '*.py' -not -path '*/__pycache__/*' | wc -l | tr -d ' ')"
  local stamp backup
  stamp="$(date +%Y%m%d-%H%M%S)"
  backup="/config/$COMPONENT-backup-$stamp.tar.gz"

  echo "== backup"
  remote "cd $REMOTE_CC && tar czf $backup $COMPONENT"
  remote "test -s $backup && tar tzf $backup >/dev/null"

  echo "== staging (nothing installed is touched yet)"
  remote "rm -rf $STAGING && mkdir -p $STAGING"
  push_staging
  echo "== verify staging is complete before anything is removed"
  remote "test -f $STAGING/manifest.json && test -f $STAGING/__init__.py && [ \"\$(find $STAGING -name '*.py' | wc -l)\" -eq $files ]"

  echo "== swap"
  remote "rm -rf $REMOTE_DIR && mv $STAGING $REMOTE_DIR"

  echo "== check and restart"
  remote "ha core check"
  remote "ha core restart"

  echo "== entities ($ENTITY_FILTER)"
  verify

  echo
  echo "Backup kept at $backup on the box."
  echo "Restore it with: scripts/deploy_ha.sh restore $backup"
}

restore() { # restore <tarball>
  local backup="${1:-}"
  [ -n "$backup" ] || die "usage: deploy_ha.sh restore <tarball>"
  echo "== verify the tarball before removing anything"
  remote "test -s $backup && tar tzf $backup | grep -q '^$COMPONENT/'"
  echo "== restore"
  remote "cd $REMOTE_CC && rm -rf $COMPONENT && tar xzf $backup"
  remote "ha core check"
  remote "ha core restart"
  echo "== entities ($ENTITY_FILTER)"
  verify
}

verify() { # states grep through ha.sh, which reads the Supervisor proxy
  echo "+ $REPO/scripts/ha.sh states $ENTITY_FILTER"
  if [ "$DRY_RUN" = 0 ]; then
    "$REPO/scripts/ha.sh" states "$ENTITY_FILTER" || true
  fi
}

usage() { grep '^#' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    deploy) shift; deploy "$@"; exit 0 ;;
    restore) shift; restore "$@"; exit 0 ;;
    *) usage; exit 1 ;;
  esac
done
usage
exit 1

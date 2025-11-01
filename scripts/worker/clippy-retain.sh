#!/usr/bin/env bash
# clippy-retain.sh — prune archived artifacts to control disk usage
#
# Env vars:
#   ARTIFACTS_DIR   - root artifacts directory (default: /artifacts)
#   RETENTION_DAYS  - delete archived dirs older than this many days (default: 30)
#   RETAIN_INTERVAL - seconds between checks (default: 3600)
#   MIN_FREE_GB     - optional: ensure at least this many GB free by deleting oldest (default: unset)

set -Eeuo pipefail

: "${ARTIFACTS_DIR:=/artifacts}"
: "${RETENTION_DAYS:=30}"
: "${RETAIN_INTERVAL:=3600}"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }
warn() { printf '[%s] WARN: %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*" >&2; }

target_dir="$ARTIFACTS_DIR/_pushed"

terminate=false
trap 'terminate=true' TERM INT

prune_by_age() {
  [[ -d "$target_dir" ]] || return 0
  # Delete directories older than RETENTION_DAYS
  find "$target_dir" -mindepth 1 -maxdepth 1 -type d -mtime +"$RETENTION_DAYS" -print0 | while IFS= read -r -d '' d; do
    log "Pruning old artifact: $(basename "$d") (> ${RETENTION_DAYS}d)"
    rm -rf --one-file-system "$d" || warn "Failed to remove $d"
  done
}

free_space_gb() {
  # Return available space in GB on the filesystem holding ARTIFACTS_DIR
  local avail_k
  avail_k=$(df -Pk "$ARTIFACTS_DIR" | awk 'NR==2{print $4}')
  if [[ -z "$avail_k" ]]; then echo 0; return; fi
  awk -v k="$avail_k" 'BEGIN{printf "%.0f", k/1048576}'
}

prune_for_space() {
  [[ -n "${MIN_FREE_GB:-}" ]] || return 0
  [[ -d "$target_dir" ]] || return 0
  local free
  free=$(free_space_gb)
  while [[ "$free" -lt "${MIN_FREE_GB}" ]]; do
    # Delete oldest directory under _pushed
    local oldest
    oldest=$(find "$target_dir" -mindepth 1 -maxdepth 1 -type d -printf '%T@\t%p\n' | sort -n | head -n1 | cut -f2-)
    if [[ -z "$oldest" ]]; then
      warn "No directories left to prune but free=${free}GB < MIN_FREE_GB=${MIN_FREE_GB}GB"
      break
    fi
    log "Freeing space: removing oldest $(basename "$oldest") (free=${free}GB < ${MIN_FREE_GB}GB)"
    rm -rf --one-file-system "$oldest" || warn "Failed to remove $oldest"
    free=$(free_space_gb)
  done
}

log "Starting clippy retain loop — artifacts=$ARTIFACTS_DIR, retention=${RETENTION_DAYS}d, min_free=${MIN_FREE_GB:-unset}GB"

while true; do
  prune_by_age || true
  prune_for_space || true
  $terminate && exit 0
  sleep "$RETAIN_INTERVAL"

done

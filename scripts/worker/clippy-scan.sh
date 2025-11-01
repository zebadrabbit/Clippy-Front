#!/usr/bin/env bash
set -euo pipefail

# Env vars
WORKER_ID="${WORKER_ID:-worker-01}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-/artifacts}"
PUSH_INTERVAL="${PUSH_INTERVAL:-60}"
WATCH_MODE="${WATCH_MODE:-auto}"

log() { echo "[scan] $(date -u +"%Y-%m-%dT%H:%M:%SZ") $*"; }

# Resolve a secret payload whether mounted as a file or a directory containing a file
resolve_secret_file() {
  local path="$1"
  if [[ -f "$path" ]]; then
    echo "$path"; return 0
  fi
  if [[ -d "$path" ]]; then
    local base; base="$(basename "$path")"
    if [[ -f "$path/$base" ]]; then
      echo "$path/$base"; return 0
    fi
    local f
    for f in "$path"/*; do
      [[ -f "$f" ]] && { echo "$f"; return 0; }
    done
  fi
  return 1
}

ensure_ready() {
  local d="$1"
  # Promote .DONE to .READY if present
  if [[ -f "$d/.DONE" && ! -f "$d/.READY" ]]; then
    log "Promoting $(basename "$d") .DONE -> .READY"
    : > "$d/.READY"
  fi
}

preflight() {
  local ok=1
  if [[ -z "${INGEST_HOST:-}" || -z "${INGEST_USER:-}" || -z "${INGEST_PATH:-}" ]]; then
    log "WARNING: Missing INGEST_HOST/INGEST_USER/INGEST_PATH; pushes will be skipped"
    ok=0
  fi
  # Accept secrets that are regular files or directories containing at least one file
  if [[ -f "/run/secrets/rsync_key" ]]; then :; elif [[ -d "/run/secrets/rsync_key" && -n "$(ls -A /run/secrets/rsync_key 2>/dev/null)" ]]; then :; else
    log "WARNING: Missing Docker secret rsync_key (file or non-empty dir) at /run/secrets/rsync_key; pushes will fail"
    ok=0
  fi
  if [[ -f "/run/secrets/known_hosts" ]]; then :; elif [[ -d "/run/secrets/known_hosts" && -n "$(ls -A /run/secrets/known_hosts 2>/dev/null)" ]]; then :; else
    log "WARNING: Missing Docker secret known_hosts (file or non-empty dir) at /run/secrets/known_hosts; SSH host verification will fail"
    ok=0
  fi

  # Best-effort SSH probe (non-fatal): log host key type and auth viability
  local known
  known="$(resolve_secret_file "${KNOWN_HOSTS_FILE:-/run/secrets/known_hosts}" || true)"
  local key
  key="$(resolve_secret_file "${RSYNC_KEY_FILE:-/run/secrets/rsync_key}" || true)"
  if [[ -n "$known" ]]; then
    local first
    first="$(head -n1 "$known" 2>/dev/null || true)"
    if [[ -n "$first" ]]; then
      case "$first" in
        *ssh-ed25519*) log "Probe: known_hosts[0] type=ssh-ed25519";;
        *ssh-rsa*) log "Probe: known_hosts[0] type=ssh-rsa";;
        *ecdsa-*) log "Probe: known_hosts[0] type=ecdsa";;
        *) log "Probe: known_hosts[0] unrecognized";;
      esac
    fi
  fi
  if [[ -n "$known" && -n "$key" && -n "${INGEST_HOST:-}" && -n "${INGEST_USER:-}" ]]; then
    local tmp_key
    tmp_key="$(mktemp -p /tmp rsync_key.XXXXXX)"
    cat "$key" > "$tmp_key" && chmod 600 "$tmp_key" || true
    # 5s timeouts, batch mode, strict host key checking
    if ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known" -i "$tmp_key" -p "${INGEST_PORT:-22}" "${INGEST_USER}@${INGEST_HOST}" echo ok >/dev/null 2>&1; then
      log "Probe: ssh auth OK to ${INGEST_USER}@${INGEST_HOST}:${INGEST_PORT:-22}"
    else
      log "Probe: ssh auth FAILED to ${INGEST_USER:-?}@${INGEST_HOST:-?}:${INGEST_PORT:-22} (non-fatal)"
    fi
    rm -f "$tmp_key" || true
  fi
  return $ok
}

sweep_once() {
  # Iterate through top-level directories in ARTIFACTS_DIR
  shopt -s nullglob
  for d in "$ARTIFACTS_DIR"/*/ ; do
    local base
    base="$(basename "$d")"
    [[ "$base" = _* ]] && continue
    [[ -d "$d" ]] || continue
    [[ -f "$d/.PUSHING" ]] && continue
    [[ -f "$d/.PUSHED" ]] && continue

    ensure_ready "$d"

    if [[ -f "$d/.READY" ]]; then
      log "Queueing push for $base"
      /scripts/worker/clippy-push.sh "$d" || log "Push failed for $base"
    fi
  done
}

handle_event() {
  local path="$1"
  # If a sentinel was created or moved into place, act immediately
  case "$path" in
    */.DONE)
      local dir
      dir="${path%/.DONE}"
      [[ -d "$dir" ]] || return 0
      ensure_ready "$dir"
      ;;
    */.READY)
      local dir
      dir="${path%/.READY}"
      [[ -d "$dir" ]] || return 0
      ;;
    *)
      return 0
      ;;
  esac
  local base
  base="$(basename "$dir")"
  [[ -f "$dir/.PUSHED" ]] && return 0
  [[ -f "$dir/.PUSHING" ]] && return 0
  if [[ -f "$dir/.READY" ]]; then
    log "Event-driven push for $base"
    /scripts/worker/clippy-push.sh "$dir" || log "Push failed for $base"
  fi
}

run_inotify_loop() {
  log "Watcher ready (mode=inotify, interval sweeps=${PUSH_INTERVAL}s, worker_id=${WORKER_ID})"
  preflight || true
  # Initial sweep to catch any existing artifacts
  sweep_once
  # Watch recursively for creation/move/close_write of sentinel files
  inotifywait -m -r -e create -e moved_to -e close_write --format '%w%f' "$ARTIFACTS_DIR" \
    | while read -r path; do
        case "$path" in
          */.READY|*/.DONE)
            handle_event "$path"
            ;;
          *) ;;
        esac
      done &

  local watcher_pid=$!
  # Periodic sweep as a safety net
  while kill -0 "$watcher_pid" 2>/dev/null; do
    sleep "$PUSH_INTERVAL" || true
    sweep_once || true
  done
}

main() {
  mkdir -p "$ARTIFACTS_DIR"
  case "$WATCH_MODE" in
    inotify)
      if command -v inotifywait >/dev/null 2>&1; then
        run_inotify_loop
      else
        log "inotify requested but inotifywait not found; falling back to polling"
        # fall through to poll
        WATCH_MODE=poll
      fi
      ;;
    auto)
      if command -v inotifywait >/dev/null 2>&1; then
        run_inotify_loop
        return 0
      else
        WATCH_MODE=poll
      fi
      ;;
  esac

  # Poll mode (default or fallback)
  log "Watcher ready (mode=poll, interval=${PUSH_INTERVAL}s, worker_id=${WORKER_ID})"
  preflight || true
  while true; do
    sweep_once
    sleep "$PUSH_INTERVAL"
  done
}

main "$@"

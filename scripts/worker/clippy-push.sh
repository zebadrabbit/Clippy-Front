#!/usr/bin/env bash
set -euo pipefail

# Push a single artifact directory to the ingest host via rsync over SSH.
# Required env: WORKER_ID, INGEST_HOST, INGEST_USER, INGEST_PATH
# Optional env: INGEST_PORT (default 22), RSYNC_KEY_FILE, KNOWN_HOSTS_FILE

ARTIFACT_DIR="${1:-}"
if [[ -z "${ARTIFACT_DIR}" || ! -d "${ARTIFACT_DIR}" ]]; then
  echo "[push] Usage: $0 /artifacts/<artifact_dir>" >&2
  exit 2
fi

WORKER_ID=${WORKER_ID:-worker-01}
INGEST_HOST=${INGEST_HOST:-}
INGEST_USER=${INGEST_USER:-}
INGEST_PATH=${INGEST_PATH:-}
INGEST_PORT=${INGEST_PORT:-22}

if [[ -z "$INGEST_HOST" || -z "$INGEST_USER" || -z "$INGEST_PATH" ]]; then
  echo "[push] Missing INGEST_HOST/INGEST_USER/INGEST_PATH env; cannot push" >&2
  exit 1
fi

# Allow override via env, default to Docker secrets paths
RSYNC_KEY_FILE=${RSYNC_KEY_FILE:-/run/secrets/rsync_key}
KNOWN_HOSTS_FILE=${KNOWN_HOSTS_FILE:-/run/secrets/known_hosts}

resolve_secret_file() {
  # $1: path (file or dir)
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

KEY_SRC="$(resolve_secret_file "$RSYNC_KEY_FILE" || true)"
KNOWN_SRC="$(resolve_secret_file "$KNOWN_HOSTS_FILE" || true)"

if [[ -z "${KEY_SRC:-}" || ! -s "$KEY_SRC" ]]; then
  echo "[push] ERROR: Missing rsync private key. Checked $RSYNC_KEY_FILE" >&2
  ls -la "$RSYNC_KEY_FILE" 2>/dev/null || true
  exit 65
fi
if [[ -z "${KNOWN_SRC:-}" || ! -s "$KNOWN_SRC" ]]; then
  # Fallback to system known_hosts if explicitly provided file is missing
  if [[ -f "/etc/ssh/ssh_known_hosts" && -s "/etc/ssh/ssh_known_hosts" ]]; then
    KNOWN_SRC="/etc/ssh/ssh_known_hosts"
  else
    echo "[push] ERROR: Missing known_hosts. Checked $KNOWN_HOSTS_FILE" >&2
    ls -la "$KNOWN_HOSTS_FILE" 2>/dev/null || true
    exit 66
  fi
fi

BASE="$(basename "$ARTIFACT_DIR")"
READY_FILE="$ARTIFACT_DIR/.READY"
LOCKFILE="$ARTIFACT_DIR/.PUSHING"

if [[ ! -f "$READY_FILE" ]]; then
  echo "[push] $BASE is not marked .READY; skipping" >&2
  exit 0
fi
if [[ -f "$ARTIFACT_DIR/.PUSHED" ]]; then
  echo "[push] $BASE already pushed; skipping" >&2
  exit 0
fi
if [[ -f "$LOCKFILE" ]]; then
  echo "[push] $BASE is already being pushed; skipping" >&2
  exit 0
fi

date -u +"%Y-%m-%dT%H:%M:%SZ" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE" "$TMP_KEY"' EXIT

# Ensure SSH private key has safe permissions (some runtimes mount secrets too permissively)
TMP_KEY="$(mktemp -p /tmp rsync_key.XXXXXX)"
cat "$KEY_SRC" > "$TMP_KEY"
chmod 600 "$TMP_KEY" || true

# SSH command used by rsync; point directly at the mounted known_hosts
SSH_CMD=("ssh" "-i" "$TMP_KEY" "-o" "StrictHostKeyChecking=yes" "-o" "UserKnownHostsFile=$KNOWN_SRC" "-p" "$INGEST_PORT")

REMOTE_DIR="${INGEST_PATH%/}/${WORKER_ID}/${BASE}"
echo "[push] Using known_hosts: $KNOWN_SRC"

# Ensure remote target directory exists (including parents)
if ! "${SSH_CMD[@]}" "${INGEST_USER}@${INGEST_HOST}" "mkdir -p '${REMOTE_DIR}'"; then
  echo "[push] ERROR: Failed to create remote dir ${REMOTE_DIR}" >&2
  exit 67
fi

echo "[push] Pushing $BASE -> ${INGEST_USER}@${INGEST_HOST}:${REMOTE_DIR}"
export RSYNC_RSH="${SSH_CMD[*]}"

rsync -az --delete \
  --chmod=F644,D755 \
  --exclude ".PUSHING" --exclude ".READY" --exclude ".DONE" \
  "$ARTIFACT_DIR"/ "${INGEST_USER}@${INGEST_HOST}:${REMOTE_DIR}/"

# Create .READY sentinel on the remote side to signal transfer completion
"${SSH_CMD[@]}" "${INGEST_USER}@${INGEST_HOST}" "date -u +'%Y-%m-%dT%H:%M:%SZ' > '${REMOTE_DIR}/.READY'"

# Mark as pushed
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$ARTIFACT_DIR/.PUSHED"
rm -f "$LOCKFILE" "$TMP_KEY"
trap - EXIT

# Optional cleanup policy after successful push
case "${CLEANUP_MODE:-none}" in
  delete)
    echo "[push] Cleaning up (delete) $(basename "$ARTIFACT_DIR") from local artifacts"
    rm -rf "$ARTIFACT_DIR" || true
    ;;
  archive)
    arch_root="${ARCHIVE_DIR:-${ARTIFACTS_DIR:-/artifacts}/_pushed}"
    mkdir -p "$arch_root" || true
    ts="$(date -u +%Y%m%dT%H%M%SZ)"
    dest="$arch_root/$(basename "$ARTIFACT_DIR")_${ts}"
    echo "[push] Archiving to $dest"
    mv "$ARTIFACT_DIR" "$dest" || true
    ;;
  *) ;;
esac

echo "[push] Done $BASE"
exit 0

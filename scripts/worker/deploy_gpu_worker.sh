#!/usr/bin/env bash
# deploy_gpu_worker.sh — provision a GPU worker deployment with unique WORKER_ID and keys
#
# This script creates a per-worker deployment scaffold, generates an ED25519 keypair,
# captures known_hosts for the ingest host, records a registry entry, and optionally
# brings up the artifact-sync + worker stack with proper overrides so each worker
# uses its own secrets.
#
# It does NOT mutate your repository files; it writes to ./deployments/<WORKER_ID>/
# and uses environment variable overrides RSYNC_KEY_FILE/KNOWN_HOSTS_FILE plus
# WORKER_ID/INGEST_* when invoking docker compose from the repo root.
#
# Usage:
#   scripts/worker/deploy_gpu_worker.sh \
#     --ingest-host 10.8.0.1 --ingest-user ingest [--ingest-port 22] \
#     --ingest-path /srv/ingest [--project local|default] [--no-up]
#
# Examples:
#   scripts/worker/deploy_gpu_worker.sh --ingest-host 10.8.0.1 \
#     --ingest-user ingest --ingest-path /srv/ingest
#
#   # Build locally and run the local worker profile
#   scripts/worker/deploy_gpu_worker.sh --ingest-host 10.8.0.1 \
#     --ingest-user ingest --ingest-path /srv/ingest --project local
#
set -Eeuo pipefail

# Defaults
INGEST_HOST=""
INGEST_USER=""
INGEST_PORT="22"
INGEST_PATH=""
PROJECT="default"    # default | local
RUN_UP=1              # set to 0 via --no-up
DEPLOY_ROOT="deployments"

usage() {
  sed -n '1,80p' "$0" | sed -n '1,60p'
}

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ingest-host) INGEST_HOST="$2"; shift 2;;
    --ingest-user) INGEST_USER="$2"; shift 2;;
    --ingest-port) INGEST_PORT="$2"; shift 2;;
    --ingest-path) INGEST_PATH="$2"; shift 2;;
    --project) PROJECT="$2"; shift 2;;
    --no-up) RUN_UP=0; shift;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2;;
  esac
done

if [[ -z "$INGEST_HOST" || -z "$INGEST_USER" || -z "$INGEST_PATH" ]]; then
  echo "Missing required args. Use --ingest-host, --ingest-user, --ingest-path." >&2
  usage; exit 2
fi

# Determine next worker id gpu-worker-XX
mkdir -p "$DEPLOY_ROOT"
next_index=1
if compgen -G "$DEPLOY_ROOT/gpu-worker-*" > /dev/null; then
  max=0
  for d in "$DEPLOY_ROOT"/gpu-worker-*; do
    b="$(basename "$d")"
    n="${b##gpu-worker-}"
    if [[ "$n" =~ ^[0-9]+$ ]]; then
      (( n>max )) && max=$n || true
    fi
  done
  next_index=$((max+1))
fi
WORKER_ID=$(printf "gpu-worker-%02d" "$next_index")

# Create deployment dir and secrets
DEPLOY_DIR="$DEPLOY_ROOT/$WORKER_ID"
SECRETS_DIR="$DEPLOY_DIR/secrets"
mkdir -p "$SECRETS_DIR"

# Generate ED25519 keypair
KEY_PATH="$SECRETS_DIR/rsync_key"
if [[ -f "$KEY_PATH" ]]; then
  echo "Key already exists at $KEY_PATH; refusing to overwrite" >&2
  exit 3
fi
ssh-keygen -t ed25519 -N "" -f "$KEY_PATH" >/dev/null

# Capture known_hosts (ED25519)
KH_PATH="$SECRETS_DIR/known_hosts"
ssh-keyscan -p "$INGEST_PORT" -t ed25519 -H "$INGEST_HOST" > "$KH_PATH"

# Write a minimal .env for this worker
cat > "$DEPLOY_DIR/.env" <<EOF
WORKER_ID=$WORKER_ID
INGEST_HOST=$INGEST_HOST
INGEST_USER=$INGEST_USER
INGEST_PORT=$INGEST_PORT
INGEST_PATH=$INGEST_PATH
# Optional tuning
WATCH_MODE=auto
PUSH_INTERVAL=60
STABLE_MINUTES=1
CLEANUP_MODE=none
RSYNC_BWLIMIT=
RSYNC_EXTRA_FLAGS=--chmod=F644,D755
EOF

# Update registry file
REGISTRY="$DEPLOY_ROOT/workers_registry.json"
            --arg kh "$KH_PATH" \
            --arg host "$INGEST_HOST" \
            --arg user "$INGEST_USER" \
            --arg port "$INGEST_PORT" \
            --arg path "$INGEST_PATH" \
            --arg created "$(date -u +%FT%TZ)" \
            '{worker_id:$id, key:$key, pub:$pub, known_hosts:$kh, ingest:{host:$host,user:$user,port:$port,path:$path}, created_at:$created}')
if [[ -s "$REGISTRY" ]]; then
  tmp=$(mktemp)
  jq ".workers += [ $entry ]" "$REGISTRY" > "$tmp" && mv "$tmp" "$REGISTRY"
else
  printf '{"workers":[%s]}
' "$entry" > "$REGISTRY"
fi

# Emit next steps and optionally bring up stack
cat <<MSG
Provisioned $WORKER_ID
- Secrets: $SECRETS_DIR
- Env:     $DEPLOY_DIR/.env
- Registry updated: $REGISTRY

To run this worker+sync stack now from the repo root:

  RSYNC_KEY_FILE="$KEY_PATH" \\
  KNOWN_HOSTS_FILE="$KH_PATH" \\
  WORKER_ID="$WORKER_ID" INGEST_HOST="$INGEST_HOST" INGEST_USER="$INGEST_USER" INGEST_PORT="$INGEST_PORT" INGEST_PATH="$INGEST_PATH" \\
  docker compose -f compose.worker.yaml up -d --build artifact-sync ${PROJECT:+--profile "$PROJECT"} ${PROJECT:+= worker-local}

Or override the worker image explicitly:

  RSYNC_KEY_FILE="$KEY_PATH" \\
  KNOWN_HOSTS_FILE="$KH_PATH" \\
  WORKER_ID="$WORKER_ID" INGEST_HOST="$INGEST_HOST" INGEST_USER="$INGEST_USER" INGEST_PORT="$INGEST_PORT" INGEST_PATH="$INGEST_PATH" \\
  WORKER_IMAGE=clippyfront-worker:local docker compose -f compose.worker.yaml up -d --build worker artifact-sync
MSG

if [[ "$RUN_UP" -eq 1 ]]; then
  echo "Bringing up $WORKER_ID stack..."
  RSYNC_KEY_FILE="$KEY_PATH" \
  KNOWN_HOSTS_FILE="$KH_PATH" \
  WORKER_ID="$WORKER_ID" INGEST_HOST="$INGEST_HOST" INGEST_USER="$INGEST_USER" INGEST_PORT="$INGEST_PORT" INGEST_PATH="$INGEST_PATH" \
  docker compose -f compose.worker.yaml up -d --build artifact-sync ${PROJECT:+--profile "$PROJECT"} ${PROJECT:+= worker-local}
fi

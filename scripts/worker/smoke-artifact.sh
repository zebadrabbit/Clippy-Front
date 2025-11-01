#!/usr/bin/env bash
set -euo pipefail

ARTIFACTS_DIR=${ARTIFACTS_DIR:-/artifacts}
name="smoke_$(date -u +%Y%m%d_%H%M%S)"
dir="${ARTIFACTS_DIR%/}/${name}"

mkdir -p "${dir}"
echo "hello" > "${dir}/example.txt"
date -u +"%Y-%m-%dT%H:%M:%SZ" > "${dir}/.READY"

echo "[smoke] Created ${dir} with .READY sentinel"
#!/usr/bin/env bash
# smoke-artifact.sh — create a dummy artifact with a .DONE sentinel for pipeline validation
# Usage: ./scripts/worker/smoke-artifact.sh [name]
set -Eeuo pipefail

: "${ARTIFACTS_DIR:=/artifacts}"

name=${1:-"smoke_$(date -u +%Y%m%d_%H%M%S)"}
adir="${ARTIFACTS_DIR%/}/${name}"
mkdir -p "$adir"

echo "hello $(date -u +%FT%TZ)" > "$adir/sample.txt"
: > "$adir/.DONE"

echo "Created dummy artifact at: $adir"
ls -la "$adir"

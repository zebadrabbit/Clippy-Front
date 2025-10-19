#!/usr/bin/env bash
set -euo pipefail

# Fetch third-party frontend assets to serve locally via Flask static.
# This avoids CDN MIME / nosniff issues in some environments.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR_DIR="$ROOT_DIR/app/static/vendor"
DZ_DIR="$VENDOR_DIR/dropzone"
VJS_DIR="$VENDOR_DIR/videojs"

mkdir -p "$DZ_DIR" "$VJS_DIR"

# Dropzone 5.9.3
DZ_JS_URL="https://cdn.jsdelivr.net/npm/dropzone@5.9.3/dist/min/dropzone.min.js"
DZ_CSS_URL="https://cdn.jsdelivr.net/npm/dropzone@5.9.3/dist/dropzone.css"

echo "Fetching Dropzone JS..."
curl -fsSL "$DZ_JS_URL" -o "$DZ_DIR/dropzone.min.js"

echo "Fetching Dropzone CSS..."
curl -fsSL "$DZ_CSS_URL" -o "$DZ_DIR/dropzone.css"

echo "Vendor assets fetched to: $DZ_DIR"

# Video.js 8.10.0
VJS_JS_URL="https://vjs.zencdn.net/8.10.0/video.min.js"
VJS_CSS_URL="https://vjs.zencdn.net/8.10.0/video-js.css"

echo "Fetching Video.js JS..."
curl -fsSL "$VJS_JS_URL" -o "$VJS_DIR/video.min.js"

echo "Fetching Video.js CSS..."
curl -fsSL "$VJS_CSS_URL" -o "$VJS_DIR/video-js.css"

echo "Vendor assets fetched to: $VJS_DIR"

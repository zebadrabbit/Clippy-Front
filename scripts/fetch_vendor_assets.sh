#!/usr/bin/env bash
set -euo pipefail

# Fetch third-party frontend assets to serve locally via Flask static.
# This avoids CDN MIME / nosniff issues in some environments.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR_DIR="$ROOT_DIR/app/static/vendor"
DZ_DIR="$VENDOR_DIR/dropzone"
VJS_DIR="$VENDOR_DIR/videojs"
JQ_DIR="$VENDOR_DIR/jquery"
BCP_DIR="$VENDOR_DIR/bootstrap-colorpicker"
LDBAR_DIR="$VENDOR_DIR/ldbar"

mkdir -p "$DZ_DIR" "$VJS_DIR" "$JQ_DIR" "$BCP_DIR/css" "$BCP_DIR/js" "$LDBAR_DIR"

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

# jQuery 3.7.1
JQ_JS_URL="https://code.jquery.com/jquery-3.7.1.min.js"
echo "Fetching jQuery JS..."
curl -fsSL "$JQ_JS_URL" -o "$JQ_DIR/jquery.min.js"
echo "Vendor assets fetched to: $JQ_DIR"

# Bootstrap Colorpicker 3.4.0
BCP_JS_URL="https://cdn.jsdelivr.net/npm/bootstrap-colorpicker@3.4.0/dist/js/bootstrap-colorpicker.min.js"
BCP_CSS_URL="https://cdn.jsdelivr.net/npm/bootstrap-colorpicker@3.4.0/dist/css/bootstrap-colorpicker.min.css"
echo "Fetching Bootstrap Colorpicker JS..."
curl -fsSL "$BCP_JS_URL" -o "$BCP_DIR/js/bootstrap-colorpicker.min.js"
echo "Fetching Bootstrap Colorpicker CSS..."
curl -fsSL "$BCP_CSS_URL" -o "$BCP_DIR/css/bootstrap-colorpicker.min.css"
echo "Vendor assets fetched to: $BCP_DIR"

# loading-bar (loading.io) - correct repo
LDBAR_JS_URL="https://cdn.jsdelivr.net/gh/loadingio/loading-bar@master/dist/loading-bar.min.js"
LDBAR_CSS_URL="https://cdn.jsdelivr.net/gh/loadingio/loading-bar@master/dist/loading-bar.min.css"
echo "Fetching loading-bar JS..."
curl -fsSL "$LDBAR_JS_URL" -o "$LDBAR_DIR/ldBar.min.js"
echo "Fetching loading-bar CSS..."
curl -fsSL "$LDBAR_CSS_URL" -o "$LDBAR_DIR/ldBar.min.css"
echo "Vendor assets fetched to: $LDBAR_DIR"

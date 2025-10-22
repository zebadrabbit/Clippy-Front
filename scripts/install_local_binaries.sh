#!/usr/bin/env bash
set -euo pipefail

# Install ffmpeg (static) and yt-dlp into a local ./bin directory for use by the app
# This script targets Linux x86_64 by default. Adjust URLs for ARM if needed.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
BIN_DIR="$PROJECT_ROOT/bin"
mkdir -p "$BIN_DIR"

echo "Installing local binaries into: $BIN_DIR"

install_ffmpeg() {
  echo "Downloading ffmpeg static build (Linux x86_64)..."
  # Using BtbN unofficial FFmpeg builds (popular CI builds). For official source tags, build from source.
  # Latest release tag reference: https://github.com/BtbN/FFmpeg-Builds/releases
  # Choose a recent build; to pin, replace 'latest' with a specific tag.
  API_URL="https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
  ASSET_URL=$(curl -sSL "$API_URL" | grep browser_download_url | grep linux64-gpl | grep tar.xz | cut -d '"' -f4 | head -n1)
  if [[ -z "$ASSET_URL" ]]; then
    echo "Could not find ffmpeg linux64-gpl asset in latest release."
    exit 1
  fi
  TMP_DIR=$(mktemp -d)
  echo "Downloading: $ASSET_URL"
  curl -L "$ASSET_URL" -o "$TMP_DIR/ffmpeg.tar.xz"
  echo "Extracting..."
  tar -xJf "$TMP_DIR/ffmpeg.tar.xz" -C "$TMP_DIR"
  # Find extracted folder and copy ffmpeg/ffprobe
  EXTRACTED_DIR=$(find "$TMP_DIR" -maxdepth 1 -type d -name "ffmpeg-*" | head -n1)
  if [[ -z "$EXTRACTED_DIR" ]]; then
    echo "Extraction failed to produce ffmpeg-* dir."
    exit 1
  fi
  install -m 0755 "$EXTRACTED_DIR/bin/ffmpeg" "$BIN_DIR/ffmpeg"
  install -m 0755 "$EXTRACTED_DIR/bin/ffprobe" "$BIN_DIR/ffprobe" || true
  echo "ffmpeg installed to $BIN_DIR/ffmpeg"
}

install_yt_dlp() {
  echo "Downloading yt-dlp binary..."
  # Official releases publish linux binary
  YT_URL="https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux"
  curl -L "$YT_URL" -o "$BIN_DIR/yt-dlp"
  chmod +x "$BIN_DIR/yt-dlp"
  echo "yt-dlp installed to $BIN_DIR/yt-dlp"
}

install_ffmpeg
install_yt_dlp

echo "Done. Ensure your app sees these binaries by either:\n- Prepending $BIN_DIR to PATH\n- Or setting FFMPEG_BINARY and YT_DLP_BINARY in environment/config."

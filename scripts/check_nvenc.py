#!/usr/bin/env python3
"""
Quick NVENC capability check and diagnostics.

- Prefers ffmpeg from the Flask app config if available, otherwise falls back to
        environment (FFMPEG_BINARY) or system PATH.
- Prints whether NVENC is usable and a reason string.
- Exits with 0 if NVENC usable or if disabled explicitly via env; 1 otherwise.

Notes:
- The probe encodes a tiny 320x180 yuv420p frame with h264_nvenc to exercise the encoder
    without tripping minimum-dimension restrictions.
- On WSL2 host shells (outside Docker), you may need:
        export LD_LIBRARY_PATH=/usr/lib/wsl/lib:${LD_LIBRARY_PATH}
    to avoid "Cannot load libcuda.so.1" when ffmpeg accesses NVENC.

This script can run even if Flask isn't installed; in that case it skips
`create_app()` and uses PATH/env resolution only.
"""
import os
import sys

# Make app importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _detect_nvenc_raw(ffmpeg_bin: str) -> tuple[bool, str]:
    try:
        import subprocess

        # List encoders first
        enc = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
        )
        if "h264_nvenc" not in (enc.stdout or ""):
            return False, "h264_nvenc encoder not listed by ffmpeg"
        # Try a small but valid encode
        import tempfile

        fd, tmp = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        try:
            test = subprocess.run(
                [
                    ffmpeg_bin,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    # Use a resolution above NVENC minimums
                    "color=size=320x180:rate=30:color=black",
                    "-frames:v",
                    "1",
                    "-c:v",
                    "h264_nvenc",
                    "-pix_fmt",
                    "yuv420p",
                    tmp,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,
            )
            return (test.returncode == 0), (
                "ok" if test.returncode == 0 else (test.stdout or "unknown error")
            )
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
    except Exception as e:
        return False, f"exception: {e}"


def main() -> int:
    # First, honor explicit disable flags
    disabled = str(os.getenv("FFMPEG_DISABLE_NVENC", "")).lower() in {
        "1",
        "true",
        "yes",
    } or str(os.getenv("CLIPPY_DISABLE_NVENC", "")).lower() in {"1", "true", "yes"}
    if disabled:
        print("NVENC check: disabled via environment")
        return 0

    ffmpeg_bin = None
    # Try to use the app resolver if Flask is present
    try:
        from app import create_app  # type: ignore
        from app.tasks.video_processing import resolve_binary  # type: ignore

        app = create_app()
        with app.app_context():
            ffmpeg_bin = resolve_binary(app, "ffmpeg")
    except Exception:
        # Fallbacks without Flask
        ffmpeg_bin = os.getenv("FFMPEG_BINARY") or "ffmpeg"

    # Try using app.ffmpeg_config.detect_nvenc if available for parity
    try:
        from app.ffmpeg_config import detect_nvenc  # type: ignore

        ok, reason = detect_nvenc(ffmpeg_bin)  # type: ignore[arg-type]
        print(f"NVENC usable: {ok} | reason: {reason} | ffmpeg='{ffmpeg_bin}'")
        return 0 if ok else 1
    except Exception:
        # Pure raw detection
        ok, reason = _detect_nvenc_raw(str(ffmpeg_bin))
        print(f"NVENC usable: {ok} | reason: {reason} | ffmpeg='{ffmpeg_bin}'")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Quick NVENC capability check and diagnostics.

- Verifies ffmpeg binary from app config or PATH
- Prints whether NVENC is usable and a reason string
- Exits with 0 if NVENC usable or if disabled explicitly via env; 1 otherwise
"""
import os
import sys

# Make app importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    # Deferred imports to allow sys.path adjustment above
    from app import create_app  # type: ignore
    from app.ffmpeg_config import detect_nvenc  # type: ignore
    from app.tasks.video_processing import resolve_binary  # type: ignore

    app = create_app()
    with app.app_context():
        ffmpeg_bin = resolve_binary(app, "ffmpeg")
        ok, reason = detect_nvenc(ffmpeg_bin)
        disabled = str(os.getenv("FFMPEG_DISABLE_NVENC", "")).lower() in {
            "1",
            "true",
            "yes",
        } or str(os.getenv("CLIPPY_DISABLE_NVENC", "")).lower() in {"1", "true", "yes"}
        if disabled:
            print("NVENC check: disabled via environment")
            return 0
        print(f"NVENC usable: {ok} | reason: {reason}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

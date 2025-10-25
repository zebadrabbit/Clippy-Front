"""
Centralized ffmpeg settings and helpers, adapted from the CLI version config.

Exposes quality parameters, overlay construction, and font/binary resolution.
"""
from __future__ import annotations

import os
import shlex
from typing import Any

# Defaults inspired by CLI config
DEFAULTS: dict[str, Any] = {
    "bitrate": "12M",
    "audio_bitrate": "192k",
    "fps": None,  # leave None to respect source unless explicitly set
    "resolution": "1920x1080",
    "nvenc_preset": "slow",
    "cq": "19",
    "gop": "120",
    "rc_lookahead": "20",
    "aq_strength": "8",
    "spatial_aq": "1",
    "temporal_aq": "1",
    "enable_overlay": True,
    "fontfile": "assets/fonts/Roboto-Medium.ttf",
}


def parse_cli_args(val: str | None) -> list[str]:
    """Parse a shell-like string into argv list using shlex.split.

    Returns [] when val is falsy.
    """
    if not val:
        return []
    try:
        return shlex.split(str(val))
    except Exception:
        # Fallback: naive split
        return str(val).split()


def config_args(app, tool: str, context: str | None = None) -> list[str]:
    """Return extra CLI args from app.config for a given tool/context.

    tool: 'ffmpeg' | 'ffprobe' | 'yt-dlp'
    context (for ffmpeg): 'encode' | 'thumbnail' | 'concat' | None
    """
    t = (tool or "").lower()
    if t == "ffprobe":
        return parse_cli_args(app.config.get("FFPROBE_ARGS"))
    if t in {"yt-dlp", "ytdlp"}:
        return parse_cli_args(app.config.get("YT_DLP_ARGS"))
    if t == "ffmpeg":
        args: list[str] = []
        args += parse_cli_args(app.config.get("FFMPEG_GLOBAL_ARGS"))
        if context == "encode":
            args += parse_cli_args(app.config.get("FFMPEG_ENCODE_ARGS"))
        elif context == "thumbnail":
            args += parse_cli_args(app.config.get("FFMPEG_THUMBNAIL_ARGS"))
        elif context == "concat":
            args += parse_cli_args(app.config.get("FFMPEG_CONCAT_ARGS"))
        return args
    return []


def _repo_root() -> str:
    # app/ is this module's parent dir
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, os.pardir))


def resolve_fontfile() -> str | None:
    """Resolve a usable font file for drawtext, with safe fallbacks."""
    # Prefer repo asset
    repo = _repo_root()
    rel = DEFAULTS.get("fontfile") or "assets/fonts/Roboto-Medium.ttf"
    if isinstance(rel, str):
        cand = rel if os.path.isabs(rel) else os.path.join(repo, rel)
        if os.path.exists(cand):
            return cand
        # Fallback locations
        fb = os.path.join(repo, "assets", "fonts", "Roboto-Medium.ttf")
        if os.path.exists(fb):
            return fb
    # System fallback (Debian/Ubuntu)
    sys1 = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if os.path.exists(sys1):
        return sys1
    # As last resort, return None (overlay will be disabled)
    return None


def parse_resolution(res_str: str | None, project_res: str | None) -> str:
    """Return WxH string from either explicit resolution or project setting.

    project_res may be values like '720p', '1080p', '1440p', '2160p'.
    """
    if res_str and "x" in res_str:
        return res_str
    pr = (project_res or "").lower()
    if pr == "720p":
        return "1280x720"
    if pr == "1080p":
        return "1920x1080"
    if pr in ("1440p", "2k"):
        return "2560x1440"
    if pr in ("2160p", "4k"):
        return "3840x2160"
    # default
    return DEFAULTS["resolution"]


def build_overlay_filter(author: str | None, game: str | None, fontfile: str) -> str:
    """Compose a filter chain that draws a box and two text lines.

    Draws between t=3 and t=10 seconds to match CLI behavior. If author is empty,
    we still render the box to provide a subtle branded area; game is drawn below
    the author in a muted color when provided.
    """
    # Base drawbox at bottom area
    chain = [
        "drawbox=enable='between(t,3,10)':x=0:y=(ih)-268:h=157:w=1000:color=black@0.7:t=fill",
    ]
    # 'clip by' label
    chain.append(
        f"drawtext=enable='between(t,3,10)':x=198:y=(h)-250:fontfile='{fontfile}':fontsize=28:fontcolor=white@0.4:text='clip by'"
    )
    # Author (bold/brighter)
    author_text = (author or "").replace("'", "'")
    chain.append(
        f"drawtext=enable='between(t,3,10)':x=198:y=(h)-210:fontfile='{fontfile}':fontsize=48:fontcolor=white@0.9:text='{author_text}'"
    )
    # Game line (muted beneath author)
    if game:
        game_text = game.replace("'", "'")
        chain.append(
            f"drawtext=enable='between(t,3,10)':x=198:y=(h)-160:fontfile='{fontfile}':fontsize=26:fontcolor=white@0.5:text='{game_text}'"
        )
    # Merge to a single filter_complex [0:v]... -> [v]
    return "[0:v]" + ",".join(chain) + "[v]"


_NVENC_AVAILABLE: bool | None = None
_NVENC_REASON: str = ""


def _env_nvenc_disabled() -> bool:
    """Return True if NVENC usage is disabled via environment."""
    return str(os.getenv("FFMPEG_DISABLE_NVENC", "")).lower() in {
        "1",
        "true",
        "yes",
    } or str(os.getenv("CLIPPY_DISABLE_NVENC", "")).lower() in {"1", "true", "yes"}


def _detect_nvenc(ffmpeg_bin: str) -> bool:
    global _NVENC_AVAILABLE
    global _NVENC_REASON
    if _NVENC_AVAILABLE is not None:
        return _NVENC_AVAILABLE
    if _env_nvenc_disabled():
        _NVENC_AVAILABLE = False
        _NVENC_REASON = "Disabled via environment"
        return _NVENC_AVAILABLE
    try:
        import subprocess
        import tempfile

        res = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
        )
        if "h264_nvenc" not in (res.stdout or ""):
            _NVENC_AVAILABLE = False
            _NVENC_REASON = "h264_nvenc encoder not listed by ffmpeg"
            return _NVENC_AVAILABLE

        # Try a small but valid encode to verify CUDA/driver availability
        fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
        try:
            os.close(fd)
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
                    # Use a resolution above NVENC minimums and common 4:2:0
                    "color=size=320x180:rate=30:color=black",
                    "-frames:v",
                    "1",
                    "-c:v",
                    "h264_nvenc",
                    "-pix_fmt",
                    "yuv420p",
                    tmp_path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,
            )
            _NVENC_AVAILABLE = test.returncode == 0
            _NVENC_REASON = (
                "ok" if _NVENC_AVAILABLE else (test.stdout or "unknown error")
            )
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    except Exception:
        _NVENC_AVAILABLE = False
        _NVENC_REASON = "exception during detection"
    return _NVENC_AVAILABLE


def detect_nvenc(ffmpeg_bin: str) -> tuple[bool, str]:
    """Public detection API returning availability and a reason string."""
    available = _detect_nvenc(ffmpeg_bin)
    return available, (_NVENC_REASON or ("ok" if available else "unavailable"))


def _env_nvenc_preset() -> str:
    """Return NVENC preset honoring environment override if provided."""
    p = os.getenv("FFMPEG_NVENC_PRESET")
    if p:
        return p
    return str(DEFAULTS.get("nvenc_preset", "slow"))


def overlay_enabled() -> bool:
    """Return True if overlay is enabled (default) and not disabled via env.

    Recognizes DISABLE_OVERLAY as a truthy flag to disable overlays.
    """
    if str(os.getenv("DISABLE_OVERLAY", "")).lower() in {"1", "true", "yes"}:
        return False
    return bool(DEFAULTS.get("enable_overlay", True))


def encoder_args(ffmpeg_bin: str) -> list[str]:
    """Return encoder argument list favoring NVENC when available."""
    if _detect_nvenc(ffmpeg_bin):
        return [
            "-c:v",
            "h264_nvenc",
            "-preset",
            _env_nvenc_preset(),
            "-rc",
            "vbr",
            "-cq",
            str(DEFAULTS["cq"]),
            "-b:v",
            str(DEFAULTS["bitrate"]),
            "-maxrate",
            str(DEFAULTS["bitrate"]),
            "-bufsize",
            str(DEFAULTS["bitrate"]),
            "-profile:v",
            "high",
            "-level",
            "4.2",
            "-g",
            str(DEFAULTS["gop"]),
            "-bf",
            "3",
            "-rc-lookahead",
            str(DEFAULTS["rc_lookahead"]),
            "-spatial_aq",
            str(DEFAULTS["spatial_aq"]),
            "-aq-strength",
            str(DEFAULTS["aq_strength"]),
            "-temporal-aq",
            str(DEFAULTS["temporal_aq"]),
            "-pix_fmt",
            "yuv420p",
        ]
    # libx264 fallback (CRF mode similar quality)
    return [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(DEFAULTS["cq"]),
        "-pix_fmt",
        "yuv420p",
    ]


def cpu_encoder_args() -> list[str]:
    """Explicit CPU encoder args for fallback retries."""
    return [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(DEFAULTS["cq"]),
        "-pix_fmt",
        "yuv420p",
    ]


def audio_args() -> list[str]:
    return [
        "-c:a",
        "aac",
        "-b:a",
        str(DEFAULTS["audio_bitrate"]),
        "-ar",
        "48000",
        "-ac",
        "2",
    ]

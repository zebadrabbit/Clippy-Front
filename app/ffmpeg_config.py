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

    project_res may be values like '720p', '1080p', '1440p', '2160p', or explicit 'WxH'.
    """
    if res_str and "x" in res_str:
        return res_str
    pr = (project_res or "").lower()
    # Check if project_res is already in WxH format
    if pr and "x" in pr:
        return pr
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


def build_overlay_filter(
    author: str | None,
    game: str | None,
    fontfile: str,
    avatar_path: str | None = None,
) -> tuple[bool, str]:
    """Compose a filter chain that draws a box, avatar image, and text lines.

    Draws between t=3 and t=10 seconds to match CLI behavior. If author is empty,
    we still render the box to provide a subtle branded area; game is drawn below
    the author in a muted color when provided.

    Args:
        author: Creator/author name to display
        game: Game name to display below author
        fontfile: Path to font file for text rendering
        avatar_path: Optional path to avatar image file (will be overlaid as circle)

    Returns:
        Tuple of (has_avatar: bool, filter_chain: str)
        - If has_avatar is True, filter_chain is: "movie='...':...[avatar];drawbox=...,[base];[base][avatar]overlay=...,drawtext=..."
        - If has_avatar is False, filter_chain is: "drawbox=...,drawtext=..."
        Does NOT include [0:v] prefix or [v] suffix - caller adds those with scale.
    """
    has_avatar = False
    avatar_prefix = ""

    # Avatar overlay (square) if provided - must be first in filter_complex
    # Note: Using square for performance. The geq filter for circular mask is too slow.
    if avatar_path and os.path.isfile(avatar_path):
        has_avatar = True
        # Escape path for ffmpeg
        escaped_avatar = avatar_path.replace("\\", "/").replace(":", "\\:")
        # Movie filter loads avatar, scales to 128x128
        avatar_prefix = (
            f"movie='{escaped_avatar}':loop=0,setpts=N/(FRAME_RATE*TB),"
            f"scale=128:128,format=yuva420p[avatar];"
        )

    # Build main video filter chain
    chain = []

    # Base drawbox at bottom area
    chain.append(
        "drawbox=enable='between(t,3,10)':x=0:y=(ih)-268:h=157:w=1000:color=black@0.7:t=fill"
    )

    # If we have avatar, we need to split: output as [base], then overlay [avatar] onto [base]
    if has_avatar:
        # Complete the drawbox output as [base], then start overlay filter
        # This will produce: drawbox=...[base];[base][avatar]overlay=...
        chain[
            -1
        ] += "[base];[base][avatar]overlay=enable='between(t,3,10)':x=50:y=(h)-250"

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

    # Return avatar flag and complete filter (movie prefix + main chain)
    return has_avatar, avatar_prefix + ",".join(chain)


# Cache NVENC availability per ffmpeg binary path. This avoids stale results
# when the resolved binary changes (e.g., local ./bin/ffmpeg vs system ffmpeg).
_NVENC_CACHE: dict[str, tuple[bool, str]] = {}


def _env_nvenc_disabled() -> bool:
    """Return True if NVENC usage is disabled via environment."""
    return str(os.getenv("FFMPEG_DISABLE_NVENC", "")).lower() in {
        "1",
        "true",
        "yes",
    } or str(os.getenv("CLIPPY_DISABLE_NVENC", "")).lower() in {"1", "true", "yes"}


def _detect_nvenc(ffmpeg_bin: str) -> bool:
    global _NVENC_CACHE
    key = str(ffmpeg_bin or "ffmpeg")
    if key in _NVENC_CACHE:
        return _NVENC_CACHE[key][0]
    if _env_nvenc_disabled():
        _NVENC_CACHE[key] = (False, "Disabled via environment")
        return False
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
            _NVENC_CACHE[key] = (False, "h264_nvenc encoder not listed by ffmpeg")
            return False

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
            ok = test.returncode == 0
            reason = "ok" if ok else (test.stdout or "unknown error")
            _NVENC_CACHE[key] = (ok, reason)
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    except Exception:
        _NVENC_CACHE[key] = (False, "exception during detection")
    return _NVENC_CACHE[key][0]


def detect_nvenc(ffmpeg_bin: str) -> tuple[bool, str]:
    """Public detection API returning availability and a reason string.

    Results are cached per-binary path.
    """
    key = str(ffmpeg_bin or "ffmpeg")
    available = _detect_nvenc(ffmpeg_bin)
    reason = _NVENC_CACHE.get(key, (available, "ok" if available else "unavailable"))[1]
    return available, reason


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


def _resolve_binary(app, name: str) -> str:
    """Resolve a binary path using app config or local ./bin vs system smart fallback.

    Order of precedence:
      1) Explicit app.config override (FFMPEG_BINARY, YT_DLP_BINARY, FFPROBE_BINARY)
      2) For ffmpeg only: if PREFER_SYSTEM_FFMPEG=1, prefer system 'ffmpeg'
      3) Project-local ./bin/<name> if present
         - For ffmpeg: if local ffmpeg lacks NVENC but system ffmpeg has NVENC, prefer system
      4) Fallback to executable name (resolved via PATH)
    """
    import subprocess

    cfg_key = None
    lname = name.lower()
    if lname == "ffmpeg":
        cfg_key = "FFMPEG_BINARY"
    elif lname in ("yt-dlp", "ytdlp"):
        cfg_key = "YT_DLP_BINARY"
    elif lname == "ffprobe":
        cfg_key = "FFPROBE_BINARY"

    if cfg_key:
        path = app.config.get(cfg_key)
        if path:
            return path

    proj_root = os.path.dirname(app.root_path)
    local_bin = os.path.join(proj_root, "bin", name)

    # For ffmpeg specifically, allow preferring system binary (useful in GPU containers)
    if lname == "ffmpeg":
        prefer_system = str(
            os.getenv(
                "PREFER_SYSTEM_FFMPEG", app.config.get("PREFER_SYSTEM_FFMPEG", "")
            )
        ).lower() in {"1", "true", "yes", "on"}
        if prefer_system:
            if os.getenv("FFMPEG_DEBUG"):
                try:
                    print("[ffmpeg] prefer system ffmpeg via PREFER_SYSTEM_FFMPEG=1")
                except Exception:
                    pass
            return "ffmpeg"

        # If local exists, but we're in a GPU context, pick the one that supports NVENC
        def _has_nvenc(bin_path: str) -> bool:
            try:
                res = subprocess.run(
                    [bin_path, "-hide_banner", "-encoders"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=5,
                )
                return "h264_nvenc" in (res.stdout or "")
            except Exception:
                return False

        gpu_context = (
            str(os.getenv("USE_GPU_QUEUE", app.config.get("USE_GPU_QUEUE", ""))).lower()
            in {
                "1",
                "true",
                "yes",
                "on",
            }
            or os.getenv("NVIDIA_VISIBLE_DEVICES")
            or os.getenv("CUDA_VISIBLE_DEVICES")
        )

        if os.path.exists(local_bin):
            if gpu_context:
                # Prefer the binary that actually has NVENC
                local_has = _has_nvenc(local_bin)
                sys_has = _has_nvenc("ffmpeg")
                if os.getenv("FFMPEG_DEBUG"):
                    try:
                        print(
                            f"[ffmpeg] gpu_context=1 local_bin='{local_bin}' local_nvenc={local_has} system_nvenc={sys_has}"
                        )
                    except Exception:
                        pass
                if sys_has and not local_has:
                    if os.getenv("FFMPEG_DEBUG"):
                        try:
                            print("[ffmpeg] selecting system ffmpeg (has NVENC)")
                        except Exception:
                            pass
                    return "ffmpeg"
            if os.getenv("FFMPEG_DEBUG"):
                try:
                    print(f"[ffmpeg] selecting local ffmpeg: {local_bin}")
                except Exception:
                    pass
            return local_bin
        # No local bin; system
        if os.getenv("FFMPEG_DEBUG"):
            try:
                print("[ffmpeg] no local ffmpeg; using system 'ffmpeg'")
            except Exception:
                pass
        return "ffmpeg"

    # Non-ffmpeg tools: prefer project-local if present, else PATH
    if os.path.exists(local_bin):
        return local_bin
    return name

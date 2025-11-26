"""
Video processing tasks for Clippy platform.

This module contains Celery tasks for video compilation, clip downloading,
and media processing using ffmpeg and yt-dlp.
"""
import json
import os
import subprocess
from typing import Any

from app import storage as storage_lib
from app.models import (
    Clip,
    Project,
    User,
    db,
)
from app.tasks.celery_app import celery_app

# Reuse a single Flask app per worker process to avoid repeatedly opening
# DB connections and re-applying runtime settings on every helper call.
_WORKER_APP = None


def _get_app():
    global _WORKER_APP
    if _WORKER_APP is None:
        from app import create_app as _create_app

        _WORKER_APP = _create_app()
    return _WORKER_APP


# ----- Tier limit helpers -----
def _normalize_res_label(val: str | None) -> str | None:
    """Normalize a resolution label from various inputs.

    Accepts labels like '720p', '1080p', '1440p' ('2k'), '2160p' ('4k'), or WxH strings.
    Returns one of: '720p' | '1080p' | '1440p' | '2160p' | 'WxH' or None if unknown.
    """
    if not val:
        return None
    s = str(val).strip().lower()
    if s in {"720p", "1080p", "1440p", "2160p"}:
        return s
    if s in {"2k"}:
        return "1440p"
    if s in {"4k"}:
        return "2160p"
    # Pass through explicit WxH strings without normalization
    if "x" in s:
        try:
            parts = s.split("x")
            w = int(parts[0]) if len(parts) > 0 else None
            h = int(parts[1]) if len(parts) > 1 else None
            if w and h:
                return f"{w}x{h}"
        except Exception:
            return None
    return None


def _res_rank(label: str | None) -> int:
    """Return ranking for resolution comparison. Higher = better quality.

    Handles both label format ('720p', '1080p') and explicit WxH format.
    For WxH, ranks by pixel count (width * height).
    """
    order = {None: -1, "720p": 0, "1080p": 1, "1440p": 2, "2160p": 3}
    if label in order:
        return order[label]
    # Handle explicit WxH format by calculating pixel count
    if label and "x" in str(label):
        try:
            parts = str(label).split("x")
            w = int(parts[0])
            h = int(parts[1])
            pixels = w * h
            # Map to equivalent label ranks for comparison
            # 720p = 1280x720 = 921,600
            # 1080p = 1920x1080 = 2,073,600
            # 1440p = 2560x1440 = 3,686,400
            # 2160p = 3840x2160 = 8,294,400
            if pixels <= 921600:
                return 0  # 720p equivalent
            elif pixels <= 2073600:
                return 1  # 1080p equivalent
            elif pixels <= 3686400:
                return 2  # 1440p equivalent
            else:
                return 3  # 2160p+ equivalent
        except Exception:
            return -1
    return -1


def _cap_resolution_label(
    project_val: str | None, tier_max_label: str | None
) -> str | None:
    p = _normalize_res_label(project_val)
    t = _normalize_res_label(tier_max_label)
    if not t:
        return p  # no cap
    if not p:
        return t  # default to tier when project undefined
    return p if _res_rank(p) <= _res_rank(t) else t


def _get_user_tier_limits(session, user_id: int) -> dict[str, Any]:
    """Fetch effective tier limits for the user.

    Returns dict with keys: max_res_label, max_fps, max_clips. None means unlimited.
    """
    try:
        u = session.get(User, user_id)
        if not u or not getattr(u, "tier", None) or u.tier.is_unlimited:
            return {"max_res_label": None, "max_fps": None, "max_clips": None}
        return {
            "max_res_label": _normalize_res_label(
                getattr(u.tier, "max_output_resolution", None)
            ),
            "max_fps": getattr(u.tier, "max_fps", None),
            "max_clips": getattr(u.tier, "max_clips_per_project", None),
        }
    except Exception:
        return {"max_res_label": None, "max_fps": None, "max_clips": None}


# get_db_session() removed - workers no longer use direct database access
# See docs/WORKER_API_MIGRATION.md for migration details


def _resolve_media_input_path(orig_path: str) -> str:
    """Resolve a media input path that may have been created on a different host.

    Handles two strategies:
      1) Explicit env alias: MEDIA_PATH_ALIAS_FROM + MEDIA_PATH_ALIAS_TO
         If orig_path startswith FROM, replace with TO and use if it exists.
      2) Automatic instance path remap: if the path contains '/instance/',
         rebuild path under this process's app.instance_path preserving the suffix.

    Returns the first existing candidate, else the original path.
    """
    try:
        debug = os.getenv("MEDIA_PATH_DEBUG", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if orig_path and os.path.exists(orig_path):
            if debug:
                print(f"[media-path] using original path (exists): {orig_path}")
            return orig_path
        ap = (orig_path or "").strip()
        if not ap:
            return orig_path
        # 1) Explicit alias
        alias_from = os.getenv("MEDIA_PATH_ALIAS_FROM")
        alias_to = os.getenv("MEDIA_PATH_ALIAS_TO")
        if alias_from and alias_to and ap.startswith(alias_from):
            cand = alias_to + ap[len(alias_from) :]
            if debug:
                print(
                    f"[media-path] alias candidate: FROM='{alias_from}' TO='{alias_to}' -> '{cand}' (exists={os.path.exists(cand)})"
                )
            if os.path.exists(cand):
                return cand
        # 2) Automatic '/instance/' remap
        marker = "/instance/"
        if marker in ap:
            try:
                app = _get_app()
                suffix = ap.split(marker, 1)[1]
                cand = os.path.join(app.instance_path, suffix)
                if debug:
                    print(
                        f"[media-path] instance remap candidate: base='{app.instance_path}' suffix='/{suffix}' -> '{cand}' (exists={os.path.exists(cand)})"
                    )
                if os.path.exists(cand):
                    return cand
                # Heuristic: if we're running in a different host (e.g., container), prefer
                # remapped app.instance_path even if the file existence check fails here.
                # This avoids trying to use the original host path inside the worker.
                try:
                    base_before_marker = ap.split(marker, 1)[0]
                except Exception:
                    base_before_marker = ""
                # If the base differs from our instance_path and our instance_path exists, we may be inside a container
                # where existence checks on host paths fail; in that case, the remap to app.instance_path is correct.
                # Only trust this path when running in a container; otherwise continue to alternate strategies.
                running_in_container = bool(
                    os.getenv("RUNNING_IN_CONTAINER")
                    or os.getenv("IN_CONTAINER")
                    or os.path.exists("/.dockerenv")
                )
                if (
                    base_before_marker.rstrip("/") != str(app.instance_path).rstrip("/")
                    and os.path.isdir(app.instance_path)
                    and running_in_container
                ):
                    if debug:
                        print(
                            f"[media-path] using remap path (container context) despite exists=False: '{cand}'"
                        )
                    return cand
            except Exception:
                pass
        # 2b) Automatic data-root remap: if path contains '/<DATA_FOLDER>/' under a different root,
        # rebuild under this process's app.instance_path/<DATA_FOLDER>/...
        try:
            app2 = _get_app()
            with app2.app_context():
                data_folder = (app2.config.get("DATA_FOLDER") or "data").strip("/")
                marker2 = f"/{data_folder}/"
                if marker2 in ap and not ap.startswith(str(app2.instance_path)):
                    suffix = ap.split(marker2, 1)[1]
                    cand2 = os.path.join(app2.instance_path, data_folder, suffix)
                    if debug:
                        try:
                            print(
                                f"[media-path] data-root remap candidate: base='{app2.instance_path}' folder='{data_folder}' suffix='/{suffix}' -> '{cand2}' (exists={os.path.exists(cand2)})"
                            )
                        except Exception:
                            pass
                    if os.path.exists(cand2):
                        return cand2
                    # Container heuristic as above: if roots differ, allow remap even if exists check fails
                    base_before_marker2 = ap.split(marker2, 1)[0]
                    running_in_container = bool(
                        os.getenv("RUNNING_IN_CONTAINER")
                        or os.getenv("IN_CONTAINER")
                        or os.path.exists("/.dockerenv")
                    )
                    if (
                        base_before_marker2.rstrip("/")
                        != str(app2.instance_path).rstrip("/")
                        and os.path.isdir(app2.instance_path)
                        and running_in_container
                    ):
                        if debug:
                            try:
                                print(
                                    f"[media-path] using data-root remap (container context) despite exists=False: '{cand2}'"
                                )
                            except Exception:
                                pass
                        return cand2
        except Exception:
            pass
    except Exception:
        pass
    return orig_path


@celery_app.task(bind=True)

# ============================================================================
# DEPRECATED TASKS REMOVED (Phase 5 - Worker API Migration)
# ============================================================================
# The following tasks and their helper functions have been removed:
# - compile_video_task (replaced by compile_video_task_v2 in compile_video_v2.py)
# - download_clip_task (replaced by download_clip_task_v2 in download_clip_v2.py)
# - Helper functions: process_clip, build_timeline_with_transitions,
#   process_media_file, compile_final_video, save_final_video
#
# Workers now communicate exclusively via REST API endpoints.
# See docs/WORKER_API_MIGRATION.md for migration details.
# ============================================================================


def _export_artifact_if_configured(
    final_output_path: str, project: Project
) -> str | None:
    """DEPRECATED: Artifact export is no longer used.

    Workers now upload files directly via HTTP during task execution.
    This function is kept for backwards compatibility but does nothing.

    Returns None always.
    """
    return None


def download_with_yt_dlp(
    url: str,
    clip: Clip,
    max_bytes: int | None = None,
    download_dir: str | None = None,
) -> str:
    """
    Download video using yt-dlp directly into the project clips directory
    using a slug-based filename '<slug>.<ext>'.

    Returns:
        str: Path to downloaded file
    """
    app = _get_app()

    # Resolve target download directory (project-aware)
    if not download_dir:
        with app.app_context():
            try:
                user = db.session.query(User).get(clip.project.user_id)
            except Exception:
                user = None
            download_dir = storage_lib.clips_dir(
                user or clip.project.owner, clip.project.name
            )
    os.makedirs(download_dir, exist_ok=True)

    # Compute sanitized slug for output filename
    slug = (getattr(clip, "source_id", None) or "").strip()
    if not slug:
        raise RuntimeError("Missing clip slug (clip.source_id) for output filename")
    import re as _re

    safe_slug = _re.sub(r"[^A-Za-z0-9._-]+", "_", slug)
    safe_slug = _re.sub(r"_+", "_", safe_slug).strip("._-") or "clip"

    # Build yt-dlp command (ignore path-affecting config/options)
    yt_bin = resolve_binary(app, "yt-dlp")
    from app.ffmpeg_config import config_args as _cfg_args

    def _sanitize_ytdlp_args(args: list[str]) -> list[str]:
        cleaned: list[str] = []
        skip_next = False
        for tok in args:
            if skip_next:
                skip_next = False
                continue
            if tok in {
                "-r",
                "--limit-rate",
                "-o",
                "--output",
                "-P",
                "--paths",
                "--paths-home",
                "--paths-temp",
                "--paths-subdirs",
            }:
                skip_next = True
                continue
            if (
                tok.startswith("--output=")
                or tok.startswith("-P=")
                or tok.startswith("--paths=")
            ):
                continue
            cleaned.append(tok)
        return cleaned

    base_args = _sanitize_ytdlp_args(_cfg_args(app, "yt-dlp"))
    output_template = os.path.join(download_dir, f"{safe_slug}.%(ext)s")
    cmd = [
        yt_bin,
        *base_args,
        "--no-config",
        "--format",
        "best[ext=mp4]/best",
        "--output",
        output_template,
        "--no-playlist",
        url,
    ]
    if max_bytes is not None and max_bytes > 0:
        cmd.extend(["--max-filesize", str(int(max_bytes))])
    if os.getenv("YT_DLP_DEBUG"):
        try:
            print("[yt-dlp] cmd:", " ".join(cmd[:-1]), "<URL>")
        except Exception:
            pass

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp error downloading {url}: {result.stderr}")

    # Determine path of downloaded file (prefer .mp4)
    downloaded_path: str | None = None
    try:
        mp4 = os.path.join(download_dir, f"{safe_slug}.mp4")
        if os.path.exists(mp4):
            downloaded_path = mp4
        else:
            for f in os.listdir(download_dir):
                if f.startswith(f"{safe_slug}."):
                    downloaded_path = os.path.join(download_dir, f)
                    break
    except Exception:
        downloaded_path = None

    if not downloaded_path:
        raise RuntimeError("Downloaded file not found")

    # Cleanup: remove any legacy clip_<id>_* files from instance/downloads to keep it empty
    try:
        _app3 = _get_app()
        with _app3.app_context():
            legacy_dir2 = os.path.join(_app3.instance_path, "downloads")
        if os.path.isdir(legacy_dir2):
            prefix = f"clip_{clip.id}_"
            for fname in list(os.listdir(legacy_dir2)):
                if fname.startswith(prefix):
                    try:
                        os.remove(os.path.join(legacy_dir2, fname))
                    except Exception:
                        pass
            # Remove the directory if now empty
            try:
                if not os.listdir(legacy_dir2):
                    os.rmdir(legacy_dir2)
            except Exception:
                pass
    except Exception:
        pass

    return downloaded_path


def extract_video_metadata(file_path: str) -> dict[str, Any]:
    """
    Extract video metadata using ffprobe.

    Args:
        file_path: Path to video file

    Returns:
        Dict: Video metadata
    """
    app = _get_app()
    ffprobe_bin = resolve_binary(app, "ffprobe")
    from app.ffmpeg_config import config_args as _cfg_args

    cmd = [
        ffprobe_bin,
        *_cfg_args(app, "ffprobe"),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        file_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            data = json.loads(result.stdout)

            # Find video stream
            video_stream = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break

            if video_stream:
                # Parse framerate safely (e.g., "30000/1001")
                fr_raw = video_stream.get("r_frame_rate", "0/1")
                try:
                    num, den = fr_raw.split("/")
                    fr_val = float(num) / float(den) if float(den or 0) else 0.0
                except Exception:
                    try:
                        fr_val = float(fr_raw)
                    except Exception:
                        fr_val = 0.0

                return {
                    "duration": float(data.get("format", {}).get("duration", 0)),
                    "width": int(video_stream.get("width", 0)),
                    "height": int(video_stream.get("height", 0)),
                    "framerate": fr_val,
                }

    except Exception:
        pass

    return {}


def resolve_binary(app, name: str) -> str:
    """Resolve a binary path using app config or local ./bin vs system smart fallback.

    Order of precedence:
      1) Explicit app.config override (FFMPEG_BINARY, YT_DLP_BINARY, FFPROBE_BINARY)
      2) For ffmpeg only: if PREFER_SYSTEM_FFMPEG=1, prefer system 'ffmpeg'
      3) Project-local ./bin/<name> if present
         - For ffmpeg: if local ffmpeg lacks NVENC but system ffmpeg has NVENC, prefer system
      4) Fallback to executable name (resolved via PATH)
    """
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
                import subprocess

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


def ffmpeg_render_preview(input_path, output_path):
    """
    Render a low-res preview video (480p, 10fps) from input_path to output_path.
    """
    import subprocess

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        "scale=480:-2,fps=10",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "32",
        "-an",
        output_path,
    ]
    subprocess.run(cmd, check=True)

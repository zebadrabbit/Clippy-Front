"""
Binary update checking tasks for ffmpeg, ffprobe, and yt-dlp.
"""
import re
import subprocess
from datetime import datetime

import structlog

from app.models import SystemSetting, User, db
from app.notifications import create_notification
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


def _get_db_session():
    from app import create_app

    app = create_app()
    with app.app_context():
        return db.session, app


def _resolve_binary(app, name: str) -> str:
    """Resolve binary path using app config."""
    from app.ffmpeg_config import _resolve_binary as resolve_bin

    return resolve_bin(app, name)


def _get_current_version(binary_path: str, binary_name: str) -> str | None:
    """Get current version of a binary."""
    try:
        if binary_name == "yt-dlp":
            result = subprocess.run(
                [binary_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # yt-dlp outputs just the version number
                return result.stdout.strip()
        elif binary_name in ["ffmpeg", "ffprobe"]:
            result = subprocess.run(
                [binary_path, "-version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Extract version from first line: "ffmpeg version N-123456-..."
                match = re.search(r"version\s+([^\s]+)", result.stdout)
                if match:
                    return match.group(1)
    except Exception as e:
        logger.warning("failed_to_get_version", binary=binary_name, error=str(e))
    return None


def _get_latest_yt_dlp_version() -> str | None:
    """Get latest yt-dlp version from GitHub releases."""
    try:
        import requests

        response = requests.get(
            "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            # Tag name is like "2024.11.18"
            return data.get("tag_name", "").strip()
    except Exception as e:
        logger.warning("failed_to_check_yt_dlp_version", error=str(e))
    return None


def _get_latest_ffmpeg_version() -> str | None:
    """Get latest ffmpeg version (simplified - checks ffmpeg.org)."""
    try:
        import requests

        # FFmpeg doesn't have a simple API, so we'll parse their download page
        # This is a simplified check - in production you might use a more robust method
        response = requests.get("https://ffmpeg.org/download.html", timeout=10)
        if response.status_code == 200:
            # Look for version pattern like "6.1.1" or "7.0"
            match = re.search(
                r"Download\s+FFmpeg\s+(\d+\.\d+(?:\.\d+)?)", response.text
            )
            if match:
                return match.group(1)
    except Exception as e:
        logger.warning("failed_to_check_ffmpeg_version", error=str(e))
    return None


@celery_app.task(bind=True)
def check_binary_updates_task(self) -> dict:
    """Check for updates to ffmpeg, ffprobe, and yt-dlp binaries."""
    session, app = _get_db_session()
    updates_available = {}

    try:
        with app.app_context():
            # Check yt-dlp
            ytdlp_path = _resolve_binary(app, "yt-dlp")
            current_ytdlp = _get_current_version(ytdlp_path, "yt-dlp")
            latest_ytdlp = _get_latest_yt_dlp_version()

            if current_ytdlp and latest_ytdlp and current_ytdlp != latest_ytdlp:
                updates_available["yt-dlp"] = {
                    "current": current_ytdlp,
                    "latest": latest_ytdlp,
                    "path": ytdlp_path,
                }
                logger.info(
                    "ytdlp_update_available",
                    current=current_ytdlp,
                    latest=latest_ytdlp,
                )

            # Check ffmpeg
            ffmpeg_path = _resolve_binary(app, "ffmpeg")
            current_ffmpeg = _get_current_version(ffmpeg_path, "ffmpeg")
            latest_ffmpeg = _get_latest_ffmpeg_version()

            if current_ffmpeg and latest_ffmpeg:
                # Simple version comparison (not perfect but works for basic cases)
                if current_ffmpeg != latest_ffmpeg and not current_ffmpeg.startswith(
                    latest_ffmpeg
                ):
                    updates_available["ffmpeg"] = {
                        "current": current_ffmpeg,
                        "latest": latest_ffmpeg,
                        "path": ffmpeg_path,
                    }
                    logger.info(
                        "ffmpeg_update_available",
                        current=current_ffmpeg,
                        latest=latest_ffmpeg,
                    )

            # Store results in SystemSetting
            if updates_available:
                SystemSetting.set("BINARY_UPDATES_AVAILABLE", str(updates_available))
                SystemSetting.set(
                    "BINARY_UPDATES_CHECKED_AT", datetime.utcnow().isoformat()
                )
                session.commit()

                # Notify all admins
                admins = User.query.filter_by(role="admin").all()
                for admin in admins:
                    update_summary = ", ".join(
                        f"{k} ({v['current']} → {v['latest']})"
                        for k, v in updates_available.items()
                    )
                    create_notification(
                        user_id=admin.id,
                        message=f"Binary updates available: {update_summary}",
                        category="admin",
                        link="/admin/maintenance",
                    )
                session.commit()

                logger.info(
                    "binary_updates_check_complete",
                    updates_count=len(updates_available),
                )
            else:
                SystemSetting.set("BINARY_UPDATES_AVAILABLE", "{}")
                SystemSetting.set(
                    "BINARY_UPDATES_CHECKED_AT", datetime.utcnow().isoformat()
                )
                session.commit()
                logger.info("binary_updates_check_complete", updates_count=0)

            return {
                "status": "success",
                "updates_available": updates_available,
                "checked_at": datetime.utcnow().isoformat(),
            }

    except Exception as e:
        logger.error("binary_update_check_failed", error=str(e))
        return {
            "status": "error",
            "error": str(e),
        }
    finally:
        session.close()

"""
Version management for ClippyFront application.
"""

__version__ = "0.5.0"
__version_info__ = (0, 5, 0)

# Version history tracking
VERSION_HISTORY = {
    "0.1.0": "Initial Flask setup with Celery and basic API",
    "0.2.0": "Added user authentication, database models, and video processing pipeline",
    "0.3.0": "Project wizard overhaul (steps 3-5 consolidated), Twitch warning, and robust download polling",
    "0.3.1": "Maintenance: Add media reindex script to backfill DB from instance/uploads and regenerate thumbnails",
    "0.4.0": (
        "Compile pipeline upgrades: transitions interleaving + static bumper insertion, "
        "NVENC detection with CPU fallback, branded overlays incl. creator/game and optional avatar, "
        "timeline cards with drag-and-drop + order persistence, compile UI cleanup, and clearer concat logging."
    ),
    "0.4.1": (
        "Wizard Step 2 chevron progress UI; Celery compile routing fix with enqueue-first status; "
        "checksum-based media dedupe and admin UI; avatar overlay time-window + position fix; "
        "project details page redesign with download; externalized inline JS/CSS to static files."
    ),
    "0.5.0": (
        "Runtime now standardizes on PostgreSQL (SQLite reserved for tests); app enforces Postgres when not testing; "
        "improved DB logging; added scripts/create_database.py to provision DB and scripts/health_check.py to verify DB/Redis connectivity; "
        "test stability fixes (Flask-Login init in TESTING, runtime schema updates disabled in tests); docs updated (README, GPU worker, WireGuard)."
    ),
}


def get_version():
    """Get the current version string."""
    return __version__


def get_version_info():
    """Get the current version as a tuple."""
    return __version_info__


def get_changelog():
    """Get the version history."""
    return VERSION_HISTORY

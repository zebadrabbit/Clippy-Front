"""
Version management for ClippyFront application.
"""

__version__ = "0.4.0"
__version_info__ = (0, 4, 0)

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

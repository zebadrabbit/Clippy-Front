"""
Version management for ClippyFront application.
"""

__version__ = "0.2.0"
__version_info__ = (0, 2, 0)

# Version history tracking
VERSION_HISTORY = {
    "0.1.0": "Initial Flask setup with Celery and basic API",
    "0.2.0": "Added user authentication, database models, and video processing pipeline",
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

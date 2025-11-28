"""
Audio metadata extraction utilities using mutagen.

Extracts ID3 tags and other metadata from audio files for automatic attribution.
"""

import logging
from pathlib import Path
from typing import Any

try:
    from mutagen import File as MutagenFile
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4
    from mutagen.oggvorbis import OggVorbis
    from mutagen.wave import WAVE

    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

logger = logging.getLogger(__name__)


def extract_audio_metadata(file_path: str) -> dict[str, Any]:
    """
    Extract metadata from audio files including ID3 tags.

    Args:
        file_path: Path to the audio file

    Returns:
        Dictionary with extracted metadata:
        - artist: Artist/performer name
        - album: Album name
        - title: Track title
        - license: License information
        - attribution_url: URL to original source
        - attribution_text: Required attribution text
        - duration: Track duration in seconds
        - year: Release year
        - genre: Genre(s)
        - comment: Comments/notes
    """
    if not MUTAGEN_AVAILABLE:
        logger.warning("Mutagen not available, cannot extract audio metadata")
        return {}

    try:
        path = Path(file_path)
        if not path.exists():
            logger.error(f"Audio file not found: {file_path}")
            return {}

        audio = MutagenFile(file_path, easy=False)
        if audio is None:
            logger.warning(f"Could not read audio file: {file_path}")
            return {}

        metadata = {}

        # Extract duration (available for all formats)
        if hasattr(audio.info, "length"):
            metadata["duration"] = audio.info.length

        # Extract tags based on format
        if (
            isinstance(audio, MP3)
            or hasattr(audio, "tags")
            and isinstance(audio.tags, ID3)
        ):
            metadata.update(_extract_id3_tags(audio))
        elif isinstance(audio, FLAC):
            metadata.update(_extract_vorbis_tags(audio))
        elif isinstance(audio, MP4):
            metadata.update(_extract_mp4_tags(audio))
        elif isinstance(audio, OggVorbis):
            metadata.update(_extract_vorbis_tags(audio))
        elif isinstance(audio, WAVE):
            # WAVE files might have ID3 tags
            if hasattr(audio, "tags") and audio.tags:
                metadata.update(_extract_id3_tags(audio))
        else:
            # Try generic tag extraction
            if hasattr(audio, "tags") and audio.tags:
                metadata.update(_extract_generic_tags(audio.tags))

        logger.info(f"Extracted metadata from {file_path}: {metadata}")
        return metadata

    except Exception as e:
        logger.error(
            f"Error extracting audio metadata from {file_path}: {e}", exc_info=True
        )
        return {}


def _extract_id3_tags(audio) -> dict[str, Any]:
    """Extract metadata from ID3 tags (MP3)."""
    metadata = {}
    tags = audio.tags if hasattr(audio, "tags") else None

    if not tags:
        return metadata

    # Artist
    if "TPE1" in tags:  # Lead performer(s)/Soloist(s)
        metadata["artist"] = str(tags["TPE1"].text[0])
    elif "TPE2" in tags:  # Band/Orchestra/Accompaniment
        metadata["artist"] = str(tags["TPE2"].text[0])

    # Album
    if "TALB" in tags:
        metadata["album"] = str(tags["TALB"].text[0])

    # Title
    if "TIT2" in tags:
        metadata["title"] = str(tags["TIT2"].text[0])

    # Year
    if "TDRC" in tags:  # Recording time
        metadata["year"] = str(tags["TDRC"].text[0])
    elif "TYER" in tags:  # Year (old format)
        metadata["year"] = str(tags["TYER"].text[0])

    # Genre
    if "TCON" in tags:
        metadata["genre"] = str(tags["TCON"].text[0])

    # Copyright
    if "TCOP" in tags:
        metadata["attribution_text"] = str(tags["TCOP"].text[0])

    # URL (usually artist/file webpage)
    if "WOAR" in tags:  # Official artist webpage
        metadata["attribution_url"] = str(tags["WOAR"].url)
    elif "WOAS" in tags:  # Official audio source webpage
        metadata["attribution_url"] = str(tags["WOAS"].url)
    elif "WOAF" in tags:  # Official audio file webpage
        metadata["attribution_url"] = str(tags["WOAF"].url)

    # Comments (might contain license info)
    if "COMM" in tags:
        comment = str(tags["COMM"].text[0])
        metadata["comment"] = comment
        # Check if comment contains license info
        if any(
            lic in comment.upper()
            for lic in ["CC", "CREATIVE COMMONS", "LICENSE", "COPYRIGHT"]
        ):
            if "attribution_text" not in metadata:
                metadata["attribution_text"] = comment

    # Publisher (might contain license info)
    if "TPUB" in tags:
        metadata["license"] = str(tags["TPUB"].text[0])

    return metadata


def _extract_vorbis_tags(audio) -> dict[str, Any]:
    """Extract metadata from Vorbis comments (FLAC, OGG)."""
    metadata = {}
    tags = audio.tags if hasattr(audio, "tags") else audio

    if not tags:
        return metadata

    # Vorbis comments are case-insensitive
    tag_map = {
        "artist": "artist",
        "albumartist": "artist",
        "album": "album",
        "title": "title",
        "date": "year",
        "genre": "genre",
        "copyright": "attribution_text",
        "license": "license",
        "contact": "attribution_url",
        "comment": "comment",
    }

    for vorbis_key, meta_key in tag_map.items():
        values = tags.get(vorbis_key)
        if values and len(values) > 0:
            metadata[meta_key] = str(values[0])

    # Some files use different keys for URL
    for url_key in ["url", "website", "source"]:
        if url_key in tags and len(tags[url_key]) > 0:
            metadata["attribution_url"] = str(tags[url_key][0])
            break

    return metadata


def _extract_mp4_tags(audio) -> dict[str, Any]:
    """Extract metadata from MP4/M4A tags."""
    metadata = {}
    tags = audio.tags if hasattr(audio, "tags") else None

    if not tags:
        return metadata

    # MP4 tag keys
    if "\xa9ART" in tags:  # Artist
        metadata["artist"] = str(tags["\xa9ART"][0])

    if "\xa9alb" in tags:  # Album
        metadata["album"] = str(tags["\xa9alb"][0])

    if "\xa9nam" in tags:  # Title
        metadata["title"] = str(tags["\xa9nam"][0])

    if "\xa9day" in tags:  # Year
        metadata["year"] = str(tags["\xa9day"][0])

    if "\xa9gen" in tags:  # Genre
        metadata["genre"] = str(tags["\xa9gen"][0])

    if "\xa9cmt" in tags:  # Comment
        metadata["comment"] = str(tags["\xa9cmt"][0])

    if "cprt" in tags:  # Copyright
        metadata["attribution_text"] = str(tags["cprt"][0])

    return metadata


def _extract_generic_tags(tags) -> dict[str, Any]:
    """Extract metadata using generic tag interface."""
    metadata = {}

    # Try common tag names
    common_tags = {
        "artist": ["artist", "ARTIST", "Artist"],
        "album": ["album", "ALBUM", "Album"],
        "title": ["title", "TITLE", "Title"],
        "year": ["date", "DATE", "Date", "year", "YEAR"],
        "genre": ["genre", "GENRE", "Genre"],
        "comment": ["comment", "COMMENT", "Comment"],
        "license": ["license", "LICENSE", "License"],
    }

    for meta_key, possible_keys in common_tags.items():
        for key in possible_keys:
            if key in tags:
                value = tags[key]
                if isinstance(value, list | tuple) and len(value) > 0:
                    metadata[meta_key] = str(value[0])
                else:
                    metadata[meta_key] = str(value)
                break

    return metadata

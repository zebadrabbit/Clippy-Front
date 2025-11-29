#
# API routes and endpoints
#
# NOTE: Most routes have been moved into smaller modules under `app.api.*`:
#   - app.api.health: Health check endpoints
#   - app.api.jobs: Task/job status endpoints
#   - app.api.media: Media file endpoints
#   - app.api.projects: All project-related endpoints
#   - app.api.automation: Automation task/schedule endpoints
#
# This file now only contains Twitch and Discord integration endpoints.
#
# ruff: noqa: I001
from flask import current_app, jsonify, request
from flask_login import current_user, login_required

from app.error_utils import safe_log_error
from app.integrations.discord import (
    extract_clip_urls,
    filter_by_reactions,
    get_channel_messages,
)
from app.integrations.twitch import (
    get_clips as twitch_get_clips,
    get_user_id as twitch_get_user_id,
)

# Import the shared blueprint instance
from app.api import api_bp

# Register routes from other modules by importing them.
# These modules register their routes on the shared `api_bp` blueprint.
import importlib

importlib.import_module("app.api.health")
importlib.import_module("app.api.jobs")
importlib.import_module("app.api.media")
importlib.import_module("app.api.projects")
importlib.import_module("app.api.worker")
importlib.import_module("app.api.tags")
importlib.import_module("app.api.teams")
importlib.import_module("app.api.notifications")
importlib.import_module("app.api.project_metadata")
importlib.import_module("app.api.compilation_preview")


# ============================================================================
# Announcement API Endpoints
# ============================================================================


@api_bp.route("/announcements", methods=["GET"])
@login_required
def get_active_announcements():
    """Get active announcements not dismissed by current user."""
    from app.models import Announcement

    announcements = (
        Announcement.query.filter_by(active=True)
        .order_by(Announcement.created_at.desc())
        .all()
    )

    # Filter out announcements dismissed by this user
    active_announcements = [
        a for a in announcements if not a.is_dismissed_by(current_user.id)
    ]

    return jsonify({"announcements": [a.to_dict() for a in active_announcements]})


@api_bp.route("/announcements/<int:announcement_id>/dismiss", methods=["POST"])
@login_required
def dismiss_announcement(announcement_id):
    """Mark an announcement as dismissed for the current user."""
    from app.models import Announcement, DismissedAnnouncement, db

    # Verify announcement exists
    Announcement.query.get_or_404(announcement_id)

    # Check if already dismissed
    existing = DismissedAnnouncement.query.filter_by(
        user_id=current_user.id, announcement_id=announcement_id
    ).first()

    if existing:
        return jsonify({"message": "Already dismissed"}), 200

    # Create dismissal record
    try:
        dismissal = DismissedAnnouncement(
            user_id=current_user.id, announcement_id=announcement_id
        )
        db.session.add(dismissal)
        db.session.commit()
        return jsonify({"message": "Announcement dismissed"}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error dismissing announcement: {e}")
        return jsonify({"error": "Failed to dismiss announcement"}), 500


# ============================================================================
# Twitch & Discord Integration Endpoints
# ============================================================================


@api_bp.route("/twitch/clips", methods=["GET"])
@login_required
def twitch_clips_api():
    """Fetch Twitch clips for a given username or the current user's connected username.

    Query params:
        username (str, optional): Twitch username to fetch clips for.
            Defaults to current_user.twitch_username if not provided.
        first (int, optional): Maximum number of clips to return (max 100).
            Defaults to 20. Ignored if target_duration is specified.
        target_duration (int, optional): Target total duration in seconds.
            If provided, fetches clips iteratively until total duration
            meets or exceeds this value.
        started_at (str, optional): RFC3339 timestamp for clip start date.
            Example: "2025-01-01T00:00:00Z"
        ended_at (str, optional): RFC3339 timestamp for clip end date.
            Example: "2025-12-31T23:59:59Z"
        after (str, optional): Pagination cursor for fetching next page.
            Only used when target_duration is not specified.

    Returns:
        tuple: JSON response and HTTP status code.
            On success (200): {
                "username": str,
                "broadcaster_id": str,
                "items": list[dict],  # Clip objects from Twitch API
                "pagination": dict,   # Cursor for next page
                "total_duration": float  # Total duration (only if target_duration used)
            }
            On error (400): {"error": "No Twitch username provided or connected."}
            On error (404): {"error": "Twitch user not found"}
            On error (502): {"error": "Failed to fetch Twitch clips"}

    Raises:
        Exception: Caught and logged. Returns 502 error response on:
            - Twitch API connection failures
            - Authentication errors with Twitch
            - Rate limit exceeded
            - Invalid API response format

    Example:
        GET /api/twitch/clips?username=streamer&first=50
        GET /api/twitch/clips?username=streamer&target_duration=900
        GET /api/twitch/clips?started_at=2025-01-01T00:00:00Z&ended_at=2025-01-31T23:59:59Z
    """
    from app.integrations.twitch import (
        get_clips_for_duration as twitch_get_clips_for_duration,
    )

    username = (
        request.args.get("username") or (current_user.twitch_username or "")
    ).strip()
    if not username:
        return jsonify({"error": "No Twitch username provided or connected."}), 400

    first = request.args.get("first", default=20, type=int)
    target_duration = request.args.get("target_duration", type=int)
    started_at = request.args.get("started_at")
    ended_at = request.args.get("ended_at")
    after = request.args.get("after")

    current_app.logger.info(
        f"[Twitch API] Request: username={username}, first={first}, "
        f"target_duration={target_duration}, started_at={started_at}, ended_at={ended_at}"
    )

    try:
        broadcaster_id = twitch_get_user_id(username)
        if not broadcaster_id:
            return jsonify({"error": "Twitch user not found"}), 404

        # Use duration-based fetching if target_duration is specified
        if target_duration and target_duration > 0:
            result = twitch_get_clips_for_duration(
                broadcaster_id=broadcaster_id,
                target_duration_seconds=target_duration,
                started_at=started_at,
                ended_at=ended_at,
                max_clips=100,  # Safety limit
            )
        else:
            result = twitch_get_clips(
                broadcaster_id=broadcaster_id,
                started_at=started_at,
                ended_at=ended_at,
                first=first,
                after=after,
            )

        return jsonify(
            {
                "username": username,
                "broadcaster_id": broadcaster_id,
                **result,
            }
        )
    except Exception as e:
        safe_log_error(
            current_app.logger,
            "Twitch API error",
            exc_info=e,
            username=username,
            user_id=current_user.id,
        )
        return jsonify({"error": "Failed to fetch Twitch clips"}), 502


@api_bp.route("/discord/messages", methods=["GET"])
@login_required
def discord_messages_api():
    """Fetch recent Discord messages and extract Twitch clip URLs with reaction filtering.

    Query params:
        channel_id (str, optional): Discord channel ID to fetch messages from.
            Defaults to Config.DISCORD_CHANNEL_ID from environment.
        limit (int, optional): Number of messages to fetch (1-100).
            Defaults to 100.
        min_reactions (int, optional): Minimum reaction count to filter messages.
            Defaults to 1 (no filtering). Only messages with at least this many
            total reactions will be included.
        reaction_emoji (str, optional): Specific emoji to filter by (e.g., '👍', ':thumbsup:').
            If provided, only counts reactions of this type. Leave empty to count all reactions.

    Returns:
        tuple: JSON response and HTTP status code.
            On success (200): {
                "items": list[dict],         # Discord message objects
                "clip_urls": list[str],      # Extracted Twitch clip URLs
                "channel_id": str,           # Channel ID used
                "filtered_count": int,       # Number of messages after reaction filtering
                "total_count": int           # Total messages fetched before filtering
            }
            On error (502): {"error": "Failed to fetch Discord messages"}

    Raises:
        Exception: Caught and logged. Returns 502 error response on:
            - Discord API connection failures
            - Invalid bot token or permissions
            - Channel not found or inaccessible
            - Rate limit exceeded
            - Invalid message format

    Example:
        GET /api/discord/messages?limit=100
        GET /api/discord/messages?min_reactions=3&reaction_emoji=👍
        GET /api/discord/messages?channel_id=123456789&min_reactions=5
    """
    limit = request.args.get("limit", default=100, type=int)
    channel_id = request.args.get("channel_id")
    min_reactions = request.args.get("min_reactions", default=1, type=int)
    reaction_emoji = request.args.get("reaction_emoji", default="", type=str).strip()

    try:
        # Fetch messages from Discord
        messages = get_channel_messages(channel_id=channel_id, limit=limit)
        total_count = len(messages)

        # Log reaction data for debugging
        current_app.logger.info(
            f"Discord fetch: {total_count} messages, min_reactions={min_reactions}, emoji='{reaction_emoji}'"
        )
        for msg in messages[:5]:  # Log first 5 messages
            reactions = msg.get("reactions", [])
            if reactions:
                current_app.logger.debug(
                    f"Message {msg.get('id')}: reactions={reactions}"
                )

        # Filter by reactions if requested (min_reactions > 0 or specific emoji)
        if min_reactions > 0 or reaction_emoji:
            messages = filter_by_reactions(
                messages,
                min_reactions=min_reactions,
                reaction_emoji=reaction_emoji or None,
            )
            current_app.logger.info(
                f"After filtering: {len(messages)} messages (from {total_count})"
            )

        # Extract Twitch clip URLs from filtered messages
        clip_urls = extract_clip_urls(messages)

        return jsonify(
            {
                "items": messages,
                "clip_urls": clip_urls,
                "channel_id": channel_id,
                "filtered_count": len(messages),
                "total_count": total_count,
            }
        )
    except Exception as e:
        error_msg = str(e)
        safe_log_error(
            current_app.logger,
            "Discord API error",
            exc_info=e,
            channel_id=channel_id,
            limit=limit,
            min_reactions=min_reactions,
            reaction_emoji=reaction_emoji,
            user_id=current_user.id,
        )
        # Provide more specific error message to help user troubleshoot
        if "400" in error_msg or "Bad Request" in error_msg:
            return (
                jsonify(
                    {
                        "error": "Discord API error: Invalid request. Please check that:\n"
                        "1. Your Discord bot token is valid\n"
                        "2. The bot has been added to your server\n"
                        "3. The bot has 'Read Message History' permission in the channel\n"
                        "4. The channel ID is correct"
                    }
                ),
                502,
            )
        elif "401" in error_msg or "Unauthorized" in error_msg:
            return (
                jsonify(
                    {
                        "error": "Discord bot token is invalid or expired. Please update DISCORD_BOT_TOKEN in your environment."
                    }
                ),
                502,
            )
        elif "403" in error_msg or "Forbidden" in error_msg:
            return (
                jsonify(
                    {
                        "error": "Discord bot doesn't have permission to access this channel. "
                        "Please ensure the bot has 'Read Message History' permission."
                    }
                ),
                502,
            )
        elif "404" in error_msg or "Not Found" in error_msg:
            return (
                jsonify(
                    {
                        "error": f"Discord channel not found. Please check channel ID: {channel_id}"
                    }
                ),
                502,
            )
        else:
            return (
                jsonify({"error": f"Failed to fetch Discord messages: {error_msg}"}),
                502,
            )


@api_bp.route("/twitch/clips/enrich", methods=["POST"])
@login_required
def enrich_clip_urls_api():
    """Batch-fetch metadata for Twitch clip URLs.

    Request body:
        {
            "urls": ["https://clips.twitch.tv/...", ...]
        }

    Returns:
        {
            "clips": [
                {
                    "url": str,
                    "title": str,
                    "duration": float,
                    "creator_name": str,
                    "creator_id": str,
                    "game_name": str,
                    "created_at": str
                },
                ...
            ],
            "total_duration": float,
            "count": int
        }
    """
    from app.integrations.twitch import get_clip_by_id

    data = request.get_json(silent=True) or {}
    urls = data.get("urls", [])

    if not urls:
        return jsonify({"error": "No URLs provided"}), 400

    # Limit to 100 URLs max
    urls = urls[:100]

    def extract_clip_id(url: str) -> str | None:
        """Extract clip ID/slug from Twitch clip URL."""
        try:
            url_lower = url.lower()
            if "clips.twitch.tv" in url_lower:
                slug = url.split("clips.twitch.tv/", 1)[1].split("/")[0].split("?")[0]
                return slug
            elif "twitch.tv" in url_lower and "/clip/" in url_lower:
                slug = url.split("/clip/", 1)[1].split("/")[0].split("?")[0]
                return slug
        except Exception:
            pass
        return None

    enriched_clips = []
    total_duration = 0.0

    for url in urls:
        clip_id = extract_clip_id(url)
        if not clip_id:
            current_app.logger.warning(f"Could not extract clip ID from URL: {url}")
            continue

        try:
            clip = get_clip_by_id(clip_id)
            if clip:
                enriched_clips.append(
                    {
                        "url": url,
                        "title": clip.title,
                        "duration": clip.duration,
                        "creator_name": clip.creator_name,
                        "creator_id": clip.creator_id,
                        "game_name": clip.game_name,
                        "created_at": clip.created_at,
                        "view_count": clip.view_count,
                        "thumbnail_url": clip.thumbnail_url,
                    }
                )
                total_duration += clip.duration
            else:
                current_app.logger.warning(f"No metadata found for clip: {clip_id}")
        except Exception as e:
            current_app.logger.error(f"Failed to fetch metadata for {clip_id}: {e}")
            continue

    return jsonify(
        {
            "clips": enriched_clips,
            "total_duration": total_duration,
            "count": len(enriched_clips),
        }
    )

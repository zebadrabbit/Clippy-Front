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
importlib.import_module("app.api.automation")
importlib.import_module("app.api.worker")
importlib.import_module("app.api.templates")
importlib.import_module("app.api.tags")
importlib.import_module("app.api.teams")
importlib.import_module("app.api.notifications")


@api_bp.route("/twitch/clips", methods=["GET"])
@login_required
def twitch_clips_api():
    """Fetch Twitch clips for a given username or the current user's connected username.

    Query params:
        username (str, optional): Twitch username to fetch clips for.
            Defaults to current_user.twitch_username if not provided.
        first (int, optional): Maximum number of clips to return (max 100).
            Defaults to 20.
        started_at (str, optional): RFC3339 timestamp for clip start date.
            Example: "2025-01-01T00:00:00Z"
        ended_at (str, optional): RFC3339 timestamp for clip end date.
            Example: "2025-12-31T23:59:59Z"
        after (str, optional): Pagination cursor for fetching next page.

    Returns:
        tuple: JSON response and HTTP status code.
            On success (200): {
                "username": str,
                "broadcaster_id": str,
                "data": list[dict],  # Clip objects from Twitch API
                "pagination": dict   # Cursor for next page
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
        GET /api/twitch/clips?started_at=2025-01-01T00:00:00Z&ended_at=2025-01-31T23:59:59Z
    """
    username = (
        request.args.get("username") or (current_user.twitch_username or "")
    ).strip()
    if not username:
        return jsonify({"error": "No Twitch username provided or connected."}), 400

    first = request.args.get("first", default=20, type=int)
    started_at = request.args.get("started_at")
    ended_at = request.args.get("ended_at")
    after = request.args.get("after")

    try:
        broadcaster_id = twitch_get_user_id(username)
        if not broadcaster_id:
            return jsonify({"error": "Twitch user not found"}), 404

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
        limit (int, optional): Number of messages to fetch (1-200).
            Defaults to 200.
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
    limit = request.args.get("limit", default=200, type=int)
    channel_id = request.args.get("channel_id")
    min_reactions = request.args.get("min_reactions", default=1, type=int)
    reaction_emoji = request.args.get("reaction_emoji", default="", type=str).strip()

    try:
        # Fetch messages from Discord
        messages = get_channel_messages(channel_id=channel_id, limit=limit)
        total_count = len(messages)

        # Filter by reactions if requested
        if min_reactions > 1 or reaction_emoji:
            messages = filter_by_reactions(
                messages,
                min_reactions=min_reactions,
                reaction_emoji=reaction_emoji or None,
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
        return jsonify({"error": "Failed to fetch Discord messages"}), 502

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
from app.integrations.discord import extract_clip_urls, get_channel_messages
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
      - username: optional; defaults to current_user.twitch_username
      - first: max 100
      - started_at, ended_at: RFC3339 timestamps (e.g., 2025-01-01T00:00:00Z)
      - after: pagination cursor
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
    """Fetch recent Discord messages and extract Twitch clip URLs.

    Query params:
      - channel_id: optional; defaults to Config.DISCORD_CHANNEL_ID
      - limit: 1-200, default 200
    Returns: { items: [...messages...], clip_urls: [...], channel_id }
    """
    limit = request.args.get("limit", default=200, type=int)
    channel_id = request.args.get("channel_id")
    try:
        messages = get_channel_messages(channel_id=channel_id, limit=limit)
        clip_urls = extract_clip_urls(messages)
        return jsonify(
            {
                "items": messages,
                "clip_urls": clip_urls,
                "channel_id": channel_id,
            }
        )
    except Exception as e:
        safe_log_error(
            current_app.logger,
            "Discord API error",
            exc_info=e,
            channel_id=channel_id,
            limit=limit,
            user_id=current_user.id,
        )
        return jsonify({"error": "Failed to fetch Discord messages"}), 502

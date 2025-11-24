"""
Lightweight Discord client to fetch recent messages from a channel using a bot token.

Notes:
- This uses Discord's HTTP API with a bot token. Ensure the bot is in the server and
  has Read Message History permission for the channel.
- Configure DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID in the environment (.env).
"""
from __future__ import annotations

from typing import Any

import httpx

from config.settings import Config

DISCORD_API_BASE = "https://discord.com/api/v10"


def _headers() -> dict[str, str]:
    cfg = Config()
    if not cfg.DISCORD_BOT_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN is not configured.")
    return {
        "Authorization": f"Bot {cfg.DISCORD_BOT_TOKEN}",
        "User-Agent": "ClippyBot (https://example.com, 1.0)",
    }


def get_channel_messages(
    channel_id: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """Fetch recent messages from a channel.

    Args:
        channel_id: Discord channel ID as a string; defaults to Config.DISCORD_CHANNEL_ID
        limit: Max number of messages to fetch (1-100)

    Returns list of message dicts (subset of fields including reactions).
    """
    cfg = Config()
    cid = channel_id or cfg.DISCORD_CHANNEL_ID
    if not cid:
        raise RuntimeError("DISCORD_CHANNEL_ID is not configured.")

    lim = max(1, min(limit, 100))
    url = f"{DISCORD_API_BASE}/channels/{cid}/messages"
    params = {"limit": lim}

    with httpx.Client(timeout=20.0, headers=_headers()) as client:
        resp = client.get(url, params=params)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Log the response body for debugging
            error_detail = ""
            try:
                error_data = resp.json()
                error_detail = f" - {error_data}"
            except Exception:
                error_detail = f" - {resp.text}"
            raise RuntimeError(
                f"Discord API error {resp.status_code}: {error_detail}. "
                f"Check that bot token is valid and bot has access to channel {cid}"
            ) from e
        data = resp.json()

    # Return selected fields to reduce payload size
    out: list[dict[str, Any]] = []
    for m in data:
        out.append(
            {
                "id": m.get("id"),
                "content": m.get("content") or "",
                "author": {
                    "id": (m.get("author") or {}).get("id"),
                    "username": (m.get("author") or {}).get("username"),
                },
                "timestamp": m.get("timestamp"),
                "reactions": [
                    {
                        "emoji": r.get("emoji", {}).get("name"),
                        "emoji_id": r.get("emoji", {}).get("id"),
                        "count": r.get("count", 0),
                    }
                    for r in (m.get("reactions") or [])
                ],
                "attachments": [
                    {"url": a.get("url"), "content_type": a.get("content_type")}
                    for a in (m.get("attachments") or [])
                ],
                "embeds": [
                    {
                        "url": e.get("url"),
                        "title": e.get("title"),
                        "description": e.get("description"),
                    }
                    for e in (m.get("embeds") or [])
                ],
            }
        )
    return out


def filter_by_reactions(
    messages: list[dict[str, Any]],
    min_reactions: int = 1,
    reaction_emoji: str | None = None,
) -> list[dict[str, Any]]:
    """Filter messages by reaction count.

    Args:
        messages: List of message dicts with 'reactions' field
        min_reactions: Minimum total reaction count required
        reaction_emoji: Optional specific emoji to filter by
            - Unicode emoji: '👍'
            - Discord name: 'thumbsup', '+1' (for 👍)
            - With colons: ':thumbsup:', ':+1:'

    Returns:
        Filtered list of messages meeting reaction threshold
    """
    if min_reactions <= 0 and not reaction_emoji:
        return messages

    filtered: list[dict[str, Any]] = []

    # Normalize emoji for comparison
    # Discord API returns:
    #   - Unicode emojis as their Discord name (e.g., "+1" for 👍)
    #   - Custom emojis with both name and id
    normalized_emoji = None
    emoji_aliases = []
    if reaction_emoji:
        # Remove colons if present (:thumbsup: -> thumbsup)
        normalized_emoji = reaction_emoji.strip().strip(":").lower()
        emoji_aliases = [normalized_emoji]

        # Add common aliases
        # Discord uses "+1" for thumbsup emoji
        if normalized_emoji in ("thumbsup", "👍"):
            emoji_aliases.extend(["+1", "thumbsup", "👍"])
        elif normalized_emoji == "+1":
            emoji_aliases.extend(["thumbsup", "👍"])

    for msg in messages:
        reactions = msg.get("reactions") or []
        if not reactions:
            continue

        if normalized_emoji:
            # Filter by specific emoji
            matching_count = 0
            for r in reactions:
                emoji_name = (r.get("emoji") or "").lower()
                # Match against any of our emoji aliases
                if emoji_name in emoji_aliases or emoji_name == reaction_emoji.lower():
                    matching_count += r.get("count", 0)

            if matching_count >= min_reactions:
                filtered.append(msg)
        else:
            # Count all reactions
            total_reactions = sum(r.get("count", 0) for r in reactions)
            if total_reactions >= min_reactions:
                filtered.append(msg)

    return filtered


def extract_clip_urls(messages: list[dict[str, Any]]) -> list[str]:
    """Extract Twitch clip URLs from message content, attachments, and embeds.

    Recognizes patterns like:
      - https://clips.twitch.tv/...
      - https://www.twitch.tv/<user>/clip/<slug>
    """
    import re

    urls: list[str] = []
    clip_patterns = [
        r"https?://clips\.twitch\.tv/[\w-]+",
        r"https?://(www\.)?twitch\.tv/[\w-]+/clip/[\w-]+",
    ]
    rx = re.compile("(" + ")|(".join(clip_patterns) + ")")

    def add_from_text(text: str | None):
        if not text:
            return
        for m in rx.finditer(text):
            u = m.group(0)
            if u not in urls:
                urls.append(u)

    for m in messages:
        add_from_text(m.get("content"))
        for a in m.get("attachments", []):
            add_from_text(a.get("url"))
        for e in m.get("embeds", []):
            add_from_text(e.get("url"))
            add_from_text(e.get("description"))

    return urls

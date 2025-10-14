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
    channel_id: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    """Fetch recent messages from a channel.

    Args:
        channel_id: Discord channel ID as a string; defaults to Config.DISCORD_CHANNEL_ID
        limit: Max number of messages to fetch (1-200)

    Returns list of message dicts (subset of fields).
    """
    cfg = Config()
    cid = channel_id or cfg.DISCORD_CHANNEL_ID
    if not cid:
        raise RuntimeError("DISCORD_CHANNEL_ID is not configured.")

    lim = max(1, min(limit, 200))
    url = f"{DISCORD_API_BASE}/channels/{cid}/messages"
    params = {"limit": lim}

    with httpx.Client(timeout=20.0, headers=_headers()) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
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

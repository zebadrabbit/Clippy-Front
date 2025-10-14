"""
Lightweight Twitch API client for fetching clips using the Helix API.

Uses client-credentials (app access token) from Config to authenticate requests.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from config.settings import Config

TWITCH_OAUTH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_HELIX_BASE = "https://api.twitch.tv/helix"


_cached_token: str | None = None
_cached_expiry: float = 0.0


def _get_app_token() -> str:
    """Get an app access token using client credentials, with basic caching."""
    global _cached_token, _cached_expiry
    now = time.time()
    if _cached_token and now < _cached_expiry - 30:  # refresh 30s early
        return _cached_token

    cfg = Config()
    client_id = cfg.TWITCH_CLIENT_ID
    client_secret = cfg.TWITCH_CLIENT_SECRET
    if not client_id or not client_secret:
        raise RuntimeError("Twitch client credentials are not configured.")

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }
    resp = httpx.post(TWITCH_OAUTH_TOKEN_URL, data=data, timeout=15.0)
    resp.raise_for_status()
    payload = resp.json()
    _cached_token = payload.get("access_token")
    expires_in = int(payload.get("expires_in", 3600))
    _cached_expiry = now + expires_in
    if not _cached_token:
        raise RuntimeError("Failed to obtain Twitch access token.")
    return _cached_token


def _client_headers() -> dict[str, str]:
    cfg = Config()
    return {
        "Client-ID": cfg.TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {_get_app_token()}",
    }


def get_user_id(username: str) -> str | None:
    """Resolve a Twitch username (login) to a user/broadcaster ID."""
    if not username:
        return None
    url = f"{TWITCH_HELIX_BASE}/users"
    params = {"login": username}
    resp = httpx.get(url, headers=_client_headers(), params=params, timeout=15.0)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if not data:
        return None
    return data[0].get("id")


@dataclass
class Clip:
    id: str
    url: str
    title: str
    created_at: str
    duration: float
    view_count: int
    thumbnail_url: str
    creator_name: str | None = None
    game_id: str | None = None
    game_name: str | None = None


def get_clips(
    broadcaster_id: str,
    started_at: str | None = None,
    ended_at: str | None = None,
    first: int = 20,
    after: str | None = None,
) -> dict[str, Any]:
    """Fetch clips for a broadcaster.

    Returns dict with keys: items: List[Clip], pagination: {cursor}
    """
    url = f"{TWITCH_HELIX_BASE}/clips"
    params: dict[str, Any] = {
        "broadcaster_id": broadcaster_id,
        "first": max(1, min(first, 100)),
    }
    if started_at:
        params["started_at"] = started_at
    if ended_at:
        params["ended_at"] = ended_at
    if after:
        params["after"] = after

    resp = httpx.get(url, headers=_client_headers(), params=params, timeout=20.0)
    resp.raise_for_status()
    j = resp.json()
    raw = j.get("data", [])
    # Collect game_ids for enrichment
    game_ids = {c.get("game_id") for c in raw if c.get("game_id")}
    game_map: dict[str, str] = {}
    if game_ids:
        try:
            gids = list(game_ids)
            # Twitch API allows repeating game_id params
            games_params = []
            for gid in gids:
                games_params.append(("id", gid))
            g_resp = httpx.get(
                f"{TWITCH_HELIX_BASE}/games",
                headers=_client_headers(),
                params=games_params,
                timeout=15.0,
            )
            g_resp.raise_for_status()
            g_items = g_resp.json().get("data", [])
            for g in g_items:
                game_map[g.get("id")] = g.get("name")
        except Exception:
            game_map = {}

    items: list[Clip] = []
    for c in raw:
        items.append(
            Clip(
                id=c.get("id"),
                url=c.get("url"),
                title=c.get("title"),
                created_at=c.get("created_at"),
                duration=float(c.get("duration", 0)),
                view_count=int(c.get("view_count", 0)),
                thumbnail_url=c.get("thumbnail_url"),
                creator_name=c.get("creator_name"),
                game_id=c.get("game_id"),
                game_name=game_map.get(c.get("game_id")) if c.get("game_id") else None,
            )
        )

    return {
        "items": [clip.__dict__ for clip in items],
        "pagination": j.get("pagination", {}),
    }

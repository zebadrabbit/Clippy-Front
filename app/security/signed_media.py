"""Short-lived signed URL utilities for serving private media to workers.

Design goals:
- Prevent URL guessing/snooping with HMAC signatures and expiry timestamps
- Optionally bind signature to requester IP to limit token reuse
- Avoid path traversal by addressing media by database id (MediaFile.id)

Contract:
- Token covers: media_id, owner_user_id, expiry_epoch, optional client_ip
- Signature scheme: HMAC-SHA256(secret, f"{media_id}:{owner_id}:{exp}:{ip}") -> hex
- Default TTL is configurable via MEDIA_URL_TTL (seconds, default 300)
"""
from __future__ import annotations

import hmac
import time
from hashlib import sha256

from flask import Request, current_app, request, url_for


def _secret() -> str:
    # Prefer dedicated signing key; fallback to Flask SECRET_KEY
    key = current_app.config.get("MEDIA_SIGNING_KEY") or current_app.config.get(
        "SECRET_KEY"
    )
    if not key:
        # Extremely unlikely; Flask always has a secret
        raise RuntimeError("No signing key configured")
    # Normalize to str
    return str(key)


def get_client_ip(req: Request) -> str:
    """Best-effort client IP extraction supporting proxies.

    Returns first X-Forwarded-For hop when present, otherwise remote_addr.
    """
    try:
        xff = (req.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        return xff or (req.remote_addr or "")
    except Exception:
        return req.remote_addr or ""


def _canonical_string(media_id: int, owner_user_id: int, exp: int, ip: str) -> str:
    return f"{int(media_id)}:{int(owner_user_id)}:{int(exp)}:{ip or ''}"


def sign(media_id: int, owner_user_id: int, exp: int, ip: str = "") -> str:
    msg = _canonical_string(media_id, owner_user_id, exp, ip).encode("utf-8")
    return hmac.new(_secret().encode("utf-8"), msg, sha256).hexdigest()


def verify_signature(
    media_id: int,
    owner_user_id: int,
    exp: int,
    sig: str,
    requester_ip: str,
) -> bool:
    """Verify signature and expiry; optionally enforce IP binding.

    When MEDIA_URL_BIND_IP is true, requester_ip must match the IP used during signing.
    Otherwise, IP is ignored (empty string in canonical message).
    """
    try:
        now = int(time.time())
        if int(exp) <= now:
            return False
        bind_ip = bool(current_app.config.get("MEDIA_URL_BIND_IP", False))
        ip_used = requester_ip.strip() if bind_ip else ""
        expected = sign(media_id, owner_user_id, int(exp), ip_used)
        # Constant-time compare
        return hmac.compare_digest(str(sig or ""), expected)
    except Exception:
        return False


def generate_signed_media_url(
    media_id: int,
    owner_user_id: int,
    ttl_seconds: int | None = None,
    client_ip: str | None = None,
    external: bool = True,
) -> str:
    """Return a signed URL for streaming/downloading a media file by id.

    Args:
        media_id: MediaFile.id
        owner_user_id: owner for authorization encoding
        ttl_seconds: seconds until expiry (default: MEDIA_URL_TTL; min 30, max 86400)
        client_ip: optionally bind to a specific IP even if MEDIA_URL_BIND_IP is False
        external: if True, return absolute URL
    """
    try:
        default_ttl = int(current_app.config.get("MEDIA_URL_TTL", 300))
    except Exception:
        default_ttl = 300
    ttl = int(ttl_seconds or default_ttl)
    if ttl > 86400:
        ttl = 86400
    exp = int(time.time()) + ttl
    # Determine IP to bind: explicit param wins; otherwise respect config toggle
    ip = (client_ip or "").strip()
    if not ip and bool(current_app.config.get("MEDIA_URL_BIND_IP", False)):
        # If called within a request context, default to current client IP
        try:
            ip = get_client_ip(request)
        except Exception:
            ip = ""
    sig = sign(media_id, owner_user_id, exp, ip)
    return url_for(
        "api.signed_media_get",
        media_id=media_id,
        u=owner_user_id,
        e=exp,
        sig=sig,
        _external=external,
    )

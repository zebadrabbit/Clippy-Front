"""Security helpers package (signed URLs, auth utilities).

Currently exposes helpers to generate and verify short-lived signed URLs for
serving private media to non-authenticated workers (e.g., GPU render nodes).
"""

from .signed_media import (
    generate_signed_media_url,
    get_client_ip,
    verify_signature,
)

__all__ = [
    "generate_signed_media_url",
    "get_client_ip",
    "verify_signature",
]

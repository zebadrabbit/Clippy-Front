"""
Server-side task to enrich clip metadata from Twitch API.

This runs in the 'celery' queue (server-only) where TWITCH_CLIENT_ID
and TWITCH_CLIENT_SECRET are available in .env.
"""

from typing import Any

from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, queue="celery")
def enrich_twitch_clip_metadata_task(self, clip_id: int) -> dict[str, Any]:
    """
    Enrich a clip with metadata from Twitch API.

    This task runs server-side only (celery queue) to avoid exposing
    TWITCH_CLIENT_SECRET to remote workers.

    Args:
        clip_id: ID of the clip to enrich

    Returns:
        Dict with status and enriched fields
    """
    from app import create_app
    from app.models import Clip, db

    app = create_app()

    with app.app_context():
        try:
            clip = db.session.get(Clip, clip_id)
            if not clip:
                return {"status": "error", "message": "Clip not found"}

            # Only enrich Twitch clips
            if not clip.source_url or "twitch" not in clip.source_url.lower():
                return {"status": "skipped", "message": "Not a Twitch clip"}

            # Skip if already has metadata
            if clip.creator_name and clip.game_name and clip.clip_created_at:
                return {"status": "skipped", "message": "Already has metadata"}

            # Extract clip slug from URL
            import re

            match = re.search(
                r"(?:clips?\.twitch\.tv/|twitch\.tv/.+/clip/)([^/?&#]+)",
                clip.source_url,
            )
            if not match:
                return {
                    "status": "error",
                    "message": "Could not extract clip ID from URL",
                }

            clip_slug = match.group(1)

            # Fetch from Twitch API
            from app.integrations.twitch import get_clip_by_id

            twitch_clip = get_clip_by_id(clip_slug)
            if not twitch_clip:
                return {"status": "error", "message": "Clip not found on Twitch"}

            # Update clip with metadata
            enriched_fields = []

            if not clip.creator_name and twitch_clip.creator_name:
                clip.creator_name = twitch_clip.creator_name
                enriched_fields.append("creator_name")

            if not clip.creator_id and twitch_clip.creator_id:
                clip.creator_id = twitch_clip.creator_id
                enriched_fields.append("creator_id")

            if not clip.game_name and twitch_clip.game_name:
                clip.game_name = twitch_clip.game_name
                enriched_fields.append("game_name")

            if not clip.clip_created_at and twitch_clip.created_at:
                try:
                    from datetime import datetime

                    clip.clip_created_at = datetime.fromisoformat(
                        twitch_clip.created_at.replace("Z", "+00:00")
                    )
                    enriched_fields.append("clip_created_at")
                except Exception:
                    pass

            if (not clip.title or clip.title.startswith("Clip ")) and twitch_clip.title:
                clip.title = twitch_clip.title
                enriched_fields.append("title")

            db.session.commit()

            app.logger.info(
                f"Enriched clip {clip_id} with Twitch metadata: {enriched_fields}"
            )

            return {
                "status": "success",
                "clip_id": clip_id,
                "enriched_fields": enriched_fields,
            }

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Failed to enrich clip {clip_id}: {e}")
            return {"status": "error", "message": str(e)}

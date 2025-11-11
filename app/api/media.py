"""Media-related API endpoints extracted from the large routes file.

This module exposes a small, focused set of endpoints for serving media files
and listing the user's media library. Imports are kept local to functions to
reduce the risk of circular imports during the incremental refactor.
"""

from flask import current_app, jsonify, request, send_file, url_for
from flask_login import login_required

from app.api import api_bp

from ._helpers import log_exception


@api_bp.route("/media/raw/<int:media_id>", methods=["GET"])
def media_raw_get(media_id: int):
    """Serve a media file by id without signatures.

    This is intended for internal/worker access. The function makes a best-effort
    attempt to resolve instance paths and stream the file. It intentionally
    avoids importing large app modules at module import time.
    """
    try:
        import os

        from app.models import MediaFile

        # Prefer extension-bound DB access when available; fall back to module db
        media = None
        try:
            media = (
                current_app.extensions.get("db").session.get(MediaFile, media_id)
                if getattr(current_app, "extensions", None)
                else None
            )
        except Exception:
            media = None

        if not media:
            from app.models import db as _db

            media = _db.session.get(MediaFile, media_id)

        if not media:
            return jsonify({"error": "Not found"}), 404
        if not media.file_path:
            return jsonify({"error": "File missing"}), 404

        orig_path = str(media.file_path).strip()
        try:
            from app.main.routes import _rebase_instance_path as _rebase

            resolved = _rebase(orig_path) or orig_path
        except Exception:
            resolved = orig_path

        path = (
            resolved
            if os.path.isfile(resolved)
            else (orig_path if os.path.isfile(orig_path) else None)
        )
        if not path:
            current_app.logger.warning(
                "Raw media 404: media_id=%s resolved_path='%s' orig_path='%s'",
                media_id,
                resolved,
                orig_path,
            )
            payload = {"error": "File not found"}
            if current_app.debug:
                payload.update(
                    {
                        "resolved_path": resolved,
                        "original_path": orig_path,
                        "instance_path": getattr(current_app, "instance_path", None),
                    }
                )
            return jsonify(payload), 404

        try:
            import mimetypes as _m

            guessed, _ = _m.guess_type(path)
            mimetype = guessed or (media.mime_type or "application/octet-stream")
        except Exception:
            mimetype = media.mime_type or "application/octet-stream"

        try:
            return send_file(path, mimetype=mimetype, conditional=True)
        except FileNotFoundError:
            current_app.logger.warning(
                "Raw media vanished: media_id=%s path='%s'", media_id, path
            )
            return jsonify({"error": "File not found"}), 404
        except PermissionError:
            current_app.logger.error(
                "Raw media permission denied: media_id=%s path='%s'", media_id, path
            )
            return jsonify({"error": "Permission denied"}), 403
        except Exception as e:
            log_exception(current_app.logger, "Raw media send error", e)
            return jsonify({"error": "Failed"}), 500
    except Exception as e:
        log_exception(current_app.logger, "Raw media error", e)
        return jsonify({"error": "Failed"}), 500


@api_bp.route("/assets/static.mp4", methods=["GET"])
def static_bumper_asset():
    """Serve the static.mp4 bumper file for workers.

    This allows remote workers to download the static bumper video that gets
    inserted between clips during compilation. The file is expected to be at
    instance/assets/static.mp4.
    """
    try:
        import os

        static_path = os.path.join(current_app.instance_path, "assets", "static.mp4")

        if not os.path.exists(static_path):
            current_app.logger.warning("Static bumper not found at: %s", static_path)
            return jsonify({"error": "Static bumper file not found"}), 404

        return send_file(static_path, mimetype="video/mp4", conditional=True)
    except FileNotFoundError:
        return jsonify({"error": "Static bumper file not found"}), 404
    except Exception as e:
        log_exception(current_app.logger, "Static bumper serve error", e)
        return jsonify({"error": "Failed to serve static bumper"}), 500


@api_bp.route("/avatars/by-clip/<int:clip_id>", methods=["GET"])
def avatar_by_clip(clip_id: int):
    """Serve a cached avatar image for a given clip.

    Falls back to instance/static placeholders when no cached avatar exists.
    """
    try:
        import glob
        import os
        import re

        from app.models import Clip

        clip = None
        try:
            clip = (
                current_app.extensions.get("db").session.get(Clip, clip_id)
                if getattr(current_app, "extensions", None)
                else None
            )
        except Exception:
            clip = None

        if not clip:
            from app.models import db as _db

            clip = _db.session.get(Clip, clip_id)
        if not clip:
            return jsonify({"error": "Not found"}), 404

        avatar_path = None
        try:
            if getattr(clip, "creator_avatar_path", None):
                orig = str(clip.creator_avatar_path)
                try:
                    from app.main.routes import _rebase_instance_path as _rebase

                    remapped = _rebase(orig) or orig
                except Exception:
                    remapped = orig
                if os.path.isfile(remapped):
                    avatar_path = remapped
                elif os.path.isfile(orig):
                    avatar_path = orig
        except Exception:
            avatar_path = None

        if not avatar_path:
            try:
                base_assets = os.path.join(current_app.instance_path, "assets")
                avatars_dir = os.path.join(base_assets, "avatars")
                author = (clip.creator_name or "").strip().lower()
                if author:
                    safe = re.sub(r"[^a-z0-9_-]+", "_", author)
                    for ext in (".png", ".jpg", ".jpeg", ".webp"):
                        cand = os.path.join(avatars_dir, safe + ext)
                        if os.path.isfile(cand):
                            avatar_path = cand
                            break
                        matches = glob.glob(os.path.join(avatars_dir, f"{safe}_*{ext}"))
                        if matches:
                            matches.sort(
                                key=lambda p: os.path.getmtime(p), reverse=True
                            )
                            avatar_path = matches[0]
                            break
                if not avatar_path:
                    for name in ("avatar.png", "avatar.jpg", "default_avatar.png"):
                        cand = os.path.join(base_assets, name)
                        if os.path.isfile(cand):
                            avatar_path = cand
                            break
                        cand2 = os.path.join(avatars_dir, name)
                        if os.path.isfile(cand2):
                            avatar_path = cand2
                            break
            except Exception:
                avatar_path = None

        if not avatar_path:
            try:
                static_base = os.path.join(current_app.root_path, "static", "avatars")
                author = (clip.creator_name or "").strip().lower()
                if author:
                    safe = re.sub(r"[^a-z0-9_-]+", "_", author)
                    for ext in (".png", ".jpg", ".jpeg", ".webp"):
                        cand = os.path.join(static_base, safe + ext)
                        if os.path.isfile(cand):
                            avatar_path = cand
                            break
                        matches = glob.glob(os.path.join(static_base, f"{safe}_*{ext}"))
                        if matches:
                            matches.sort(
                                key=lambda p: os.path.getmtime(p), reverse=True
                            )
                            avatar_path = matches[0]
                            break
                if not avatar_path:
                    for name in ("avatar.png", "avatar.jpg", "default_avatar.png"):
                        cand = os.path.join(static_base, name)
                        if os.path.isfile(cand):
                            avatar_path = cand
                            break
            except Exception:
                avatar_path = None

        if not avatar_path:
            return jsonify({"error": "Not found"}), 404

        try:
            import mimetypes as _m

            guessed, _ = _m.guess_type(avatar_path)
            mimetype = guessed or "image/jpeg"
        except Exception:
            mimetype = "image/jpeg"

        try:
            return send_file(avatar_path, mimetype=mimetype, conditional=True)
        except FileNotFoundError:
            return jsonify({"error": "Not found"}), 404
        except PermissionError:
            return jsonify({"error": "Permission denied"}), 403
        except Exception as e:
            log_exception(current_app.logger, "Avatar send error", e)
            return jsonify({"error": "Failed"}), 500
    except Exception as e:
        log_exception(current_app.logger, "Avatar error", e)
        return jsonify({"error": "Failed"}), 500


@api_bp.route("/media/stats", methods=["GET"])
@login_required
def media_stats_api():
    """Return counts of media for the current user by type.

    Optional query param:
      - type: filter to a specific MediaType value
    """
    try:
        from flask_login import current_user

        from app.models import MediaType

        q = current_user.media_files
        type_filter = request.args.get("type")
        if type_filter and type_filter in [t.value for t in MediaType]:
            q = q.filter_by(media_type=MediaType(type_filter))

        items = q.all()
        total = len(items)
        by_type: dict[str, int] = {}
        for t in MediaType:
            by_type[t.value] = len([m for m in items if m.media_type == t])
        recent = [m.id for m in items[:5]]
        return jsonify({"total": total, "by_type": by_type, "recent_ids": recent})
    except Exception as e:
        log_exception(current_app.logger, "media_stats_api error", e)
        return jsonify({"error": "Failed"}), 500


@api_bp.route("/media", methods=["GET"])
@login_required
def list_user_media_api():
    """List current user's media library, optionally filtered by type.

    Query params:
      - type: one of intro,outro,transition,clip (optional)
    Returns an array of media with preview/thumbnail URLs for selection UIs.
    """
    try:
        from flask_login import current_user

        from app.models import MediaFile, MediaType

        type_q = (request.args.get("type") or "").strip().lower()
        type_map = {
            "intro": MediaType.INTRO,
            "outro": MediaType.OUTRO,
            "transition": MediaType.TRANSITION,
            "clip": MediaType.CLIP,
        }

        q = MediaFile.query.filter_by(user_id=current_user.id)
        if type_q in type_map:
            q = q.filter_by(media_type=type_map[type_q])
        q = q.order_by(MediaFile.uploaded_at.desc())

        items = []
        for mf in q.all():
            items.append(
                {
                    "id": mf.id,
                    "filename": mf.original_filename or mf.filename,
                    "duration": mf.duration,
                    "media_type": mf.media_type.value
                    if hasattr(mf.media_type, "value")
                    else str(mf.media_type),
                    "thumbnail_url": url_for("main.media_thumbnail", media_id=mf.id)
                    if mf.thumbnail_path
                    else None,
                    "preview_url": url_for("main.media_preview", media_id=mf.id),
                }
            )

        return jsonify({"items": items, "count": len(items)})
    except Exception as e:
        log_exception(current_app.logger, "list_user_media_api error", e)
        return jsonify({"error": "Failed"}), 500


@api_bp.route("/projects/<int:project_id>/media", methods=["GET"])
@login_required
def list_project_media_api(project_id: int):
    """List media files for a project, optionally filtered by media type.

    Query params:
      - type: one of intro, outro, transition, clip (optional)
    """
    try:
        from flask_login import current_user

        from app.models import MediaFile, MediaType, Project

        project = Project.query.filter_by(
            id=project_id, user_id=current_user.id
        ).first()
        if not project:
            return jsonify({"error": "Project not found"}), 404

        type_q = (request.args.get("type") or "").strip().lower()
        type_map = {
            "intro": MediaType.INTRO,
            "outro": MediaType.OUTRO,
            "transition": MediaType.TRANSITION,
            "clip": MediaType.CLIP,
        }

        q = MediaFile.query.filter_by(user_id=current_user.id)
        if type_q in type_map:
            q = q.filter_by(media_type=type_map[type_q])
        q = q.order_by(MediaFile.uploaded_at.desc())

        items = []
        for mf in q.all():
            items.append(
                {
                    "id": mf.id,
                    "filename": mf.filename,
                    "original_filename": mf.original_filename,
                    "duration": mf.duration,
                    "width": mf.width,
                    "height": mf.height,
                    "framerate": mf.framerate,
                    "media_type": mf.media_type.value
                    if hasattr(mf.media_type, "value")
                    else str(mf.media_type),
                    "thumbnail_url": url_for("main.media_thumbnail", media_id=mf.id)
                    if mf.thumbnail_path
                    else None,
                    "preview_url": url_for("main.media_preview", media_id=mf.id),
                }
            )

        return jsonify({"items": items, "count": len(items)})
    except Exception as e:
        log_exception(current_app.logger, "list_project_media_api error", e)
        return jsonify({"error": "Failed"}), 500

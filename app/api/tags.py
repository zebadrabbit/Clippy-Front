"""
API endpoints for tag management.

Allows users to create, search, and manage tags for organizing media and clips.
"""
import re

from flask import current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.api import api_bp
from app.models import Clip, MediaFile, Tag, db


def slugify(text: str) -> str:
    """
    Convert text to URL-friendly slug.

    Args:
        text: Text to slugify

    Returns:
        str: Slugified text
    """
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text[:50]


@api_bp.route("/tags", methods=["GET"])
@login_required
def list_tags():
    """
    List all tags for the current user.

    Query params:
        - q: Search query
        - limit: Maximum results (default 50)
        - include_global: Include global tags (default true)

    Returns:
        JSON: List of tag objects with usage counts
    """
    query_text = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 50)), 100)
    include_global = request.args.get("include_global", "true").lower() == "true"

    # Build query
    query = Tag.query

    # Filter by ownership
    if include_global:
        query = query.filter(
            or_(Tag.user_id == current_user.id, Tag.is_global.is_(True))
        )
    else:
        query = query.filter(Tag.user_id == current_user.id)

    # Search filter
    if query_text:
        search_pattern = f"%{query_text}%"
        query = query.filter(
            or_(Tag.name.ilike(search_pattern), Tag.description.ilike(search_pattern))
        )

    # Order by usage and name
    tags = query.order_by(Tag.use_count.desc(), Tag.name).limit(limit).all()

    return jsonify(
        {
            "tags": [
                {
                    "id": t.id,
                    "name": t.name,
                    "slug": t.slug,
                    "description": t.description,
                    "color": t.color,
                    "is_global": t.is_global,
                    "parent_id": t.parent_id,
                    "full_path": t.full_path,
                    "use_count": t.use_count or 0,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tags
            ]
        }
    )


@api_bp.route("/tags", methods=["POST"])
@login_required
def create_tag():
    """
    Create a new tag.

    Request JSON:
        - name: Tag name (required)
        - description: Tag description (optional)
        - color: Hex color code (optional, default #6c757d)
        - parent_id: Parent tag ID for hierarchical tags (optional)

    Returns:
        JSON: Created tag object
    """
    data = request.get_json()

    if not data or not data.get("name"):
        return jsonify({"error": "Tag name is required"}), 400

    name = data["name"].strip()
    if not name or len(name) > 50:
        return jsonify({"error": "Tag name must be 1-50 characters"}), 400

    slug = slugify(name)

    # Check for duplicate slug for this user
    existing = Tag.query.filter_by(user_id=current_user.id, slug=slug).first()
    if existing:
        return jsonify({"error": f"Tag '{name}' already exists"}), 409

    # Validate color format
    color = data.get("color", "#6c757d")
    if not re.match(r"^#[0-9A-Fa-f]{6}$", color):
        color = "#6c757d"

    # Validate parent tag
    parent_id = data.get("parent_id")
    if parent_id:
        parent = db.session.get(Tag, parent_id)
        if not parent or (parent.user_id != current_user.id and not parent.is_global):
            return jsonify({"error": "Invalid parent tag"}), 400

    try:
        tag = Tag(
            name=name,
            slug=slug,
            description=data.get("description", "").strip() or None,
            color=color,
            user_id=current_user.id,
            parent_id=parent_id,
        )
        db.session.add(tag)
        db.session.commit()

        current_app.logger.info(f"Tag created: {tag.id} by user {current_user.id}")

        return (
            jsonify(
                {
                    "id": tag.id,
                    "name": tag.name,
                    "slug": tag.slug,
                    "description": tag.description,
                    "color": tag.color,
                    "parent_id": tag.parent_id,
                    "full_path": tag.full_path,
                    "created_at": tag.created_at.isoformat(),
                }
            ),
            201,
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating tag: {e}")
        return jsonify({"error": "Failed to create tag"}), 500


@api_bp.route("/tags/<int:tag_id>", methods=["GET"])
@login_required
def get_tag(tag_id):
    """
    Get a specific tag with usage statistics.

    Args:
        tag_id: Tag ID

    Returns:
        JSON: Tag object with media/clip counts
    """
    tag = db.session.get(Tag, tag_id)

    if not tag or (tag.user_id != current_user.id and not tag.is_global):
        return jsonify({"error": "Tag not found"}), 404

    # Count usage
    media_count = tag.media_files.filter(MediaFile.user_id == current_user.id).count()
    clip_count = (
        tag.clips.join(Clip.project)
        .filter(MediaFile.user_id == current_user.id)
        .count()
    )

    return jsonify(
        {
            "id": tag.id,
            "name": tag.name,
            "slug": tag.slug,
            "description": tag.description,
            "color": tag.color,
            "is_global": tag.is_global,
            "parent_id": tag.parent_id,
            "full_path": tag.full_path,
            "use_count": tag.use_count or 0,
            "media_count": media_count,
            "clip_count": clip_count,
            "created_at": tag.created_at.isoformat() if tag.created_at else None,
            "updated_at": tag.updated_at.isoformat() if tag.updated_at else None,
        }
    )


@api_bp.route("/tags/<int:tag_id>", methods=["PUT"])
@login_required
def update_tag(tag_id):
    """
    Update a tag.

    Args:
        tag_id: Tag ID

    Request JSON:
        - name: Tag name
        - description: Tag description
        - color: Hex color code
        - parent_id: Parent tag ID

    Returns:
        JSON: Updated tag object
    """
    tag = db.session.get(Tag, tag_id)

    if not tag or tag.user_id != current_user.id:
        return jsonify({"error": "Tag not found"}), 404

    data = request.get_json()

    # Update name/slug
    if "name" in data:
        name = data["name"].strip()
        if not name or len(name) > 50:
            return jsonify({"error": "Tag name must be 1-50 characters"}), 400

        new_slug = slugify(name)

        # Check for duplicate slug (excluding current tag)
        existing = Tag.query.filter(
            Tag.user_id == current_user.id, Tag.slug == new_slug, Tag.id != tag_id
        ).first()

        if existing:
            return jsonify({"error": f"Tag '{name}' already exists"}), 409

        tag.name = name
        tag.slug = new_slug

    # Update description
    if "description" in data:
        tag.description = data["description"].strip() or None

    # Update color
    if "color" in data:
        color = data["color"]
        if re.match(r"^#[0-9A-Fa-f]{6}$", color):
            tag.color = color

    # Update parent
    if "parent_id" in data:
        parent_id = data["parent_id"]
        if parent_id:
            parent = db.session.get(Tag, parent_id)
            if not parent or (
                parent.user_id != current_user.id and not parent.is_global
            ):
                return jsonify({"error": "Invalid parent tag"}), 400
            # Prevent circular reference
            if parent_id == tag_id or (parent.parent_id == tag_id):
                return (
                    jsonify({"error": "Circular parent relationship not allowed"}),
                    400,
                )
        tag.parent_id = parent_id

    try:
        db.session.commit()
        current_app.logger.info(f"Tag updated: {tag.id} by user {current_user.id}")

        return jsonify(
            {
                "id": tag.id,
                "name": tag.name,
                "slug": tag.slug,
                "description": tag.description,
                "color": tag.color,
                "parent_id": tag.parent_id,
                "full_path": tag.full_path,
                "updated_at": tag.updated_at.isoformat() if tag.updated_at else None,
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating tag: {e}")
        return jsonify({"error": "Failed to update tag"}), 500


@api_bp.route("/tags/<int:tag_id>", methods=["DELETE"])
@login_required
def delete_tag(tag_id):
    """
    Delete a tag.

    Args:
        tag_id: Tag ID

    Returns:
        JSON: Success message
    """
    tag = db.session.get(Tag, tag_id)

    if not tag or tag.user_id != current_user.id:
        return jsonify({"error": "Tag not found"}), 404

    try:
        # Associations are automatically removed via cascade
        db.session.delete(tag)
        db.session.commit()
        current_app.logger.info(f"Tag deleted: {tag_id} by user {current_user.id}")

        return jsonify({"message": "Tag deleted successfully"})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting tag: {e}")
        return jsonify({"error": "Failed to delete tag"}), 500


@api_bp.route("/media/<int:media_id>/tags", methods=["POST"])
@login_required
def add_media_tags(media_id):
    """
    Add tags to a media file.

    Args:
        media_id: Media file ID

    Request JSON:
        - tag_ids: List of tag IDs to add

    Returns:
        JSON: Updated tag list
    """
    media = db.session.get(MediaFile, media_id)

    if not media or media.user_id != current_user.id:
        return jsonify({"error": "Media file not found"}), 404

    data = request.get_json()
    tag_ids = data.get("tag_ids", [])

    if not isinstance(tag_ids, list):
        return jsonify({"error": "tag_ids must be a list"}), 400

    try:
        for tag_id in tag_ids:
            tag = db.session.get(Tag, tag_id)
            if tag and (tag.user_id == current_user.id or tag.is_global):
                if tag not in media.tag_objects.all():
                    media.tag_objects.append(tag)
                    tag.increment_usage()

        db.session.commit()

        tags = media.tag_objects.all()
        return jsonify(
            {
                "tags": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "color": t.color,
                        "full_path": t.full_path,
                    }
                    for t in tags
                ]
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error adding media tags: {e}")
        return jsonify({"error": "Failed to add tags"}), 500


@api_bp.route("/media/<int:media_id>/tags/<int:tag_id>", methods=["DELETE"])
@login_required
def remove_media_tag(media_id, tag_id):
    """
    Remove a tag from a media file.

    Args:
        media_id: Media file ID
        tag_id: Tag ID

    Returns:
        JSON: Success message
    """
    media = db.session.get(MediaFile, media_id)

    if not media or media.user_id != current_user.id:
        return jsonify({"error": "Media file not found"}), 404

    tag = db.session.get(Tag, tag_id)

    if not tag:
        return jsonify({"error": "Tag not found"}), 404

    try:
        if tag in media.tag_objects.all():
            media.tag_objects.remove(tag)
            db.session.commit()

        return jsonify({"message": "Tag removed successfully"})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error removing media tag: {e}")
        return jsonify({"error": "Failed to remove tag"}), 500


@api_bp.route("/clips/<int:clip_id>/tags", methods=["POST"])
@login_required
def add_clip_tags(clip_id):
    """
    Add tags to a clip.

    Args:
        clip_id: Clip ID

    Request JSON:
        - tag_ids: List of tag IDs to add

    Returns:
        JSON: Updated tag list
    """
    clip = db.session.get(Clip, clip_id)

    if not clip:
        return jsonify({"error": "Clip not found"}), 404

    # Verify ownership via project
    if not clip.project or clip.project.user_id != current_user.id:
        return jsonify({"error": "Clip not found"}), 404

    data = request.get_json()
    tag_ids = data.get("tag_ids", [])

    if not isinstance(tag_ids, list):
        return jsonify({"error": "tag_ids must be a list"}), 400

    try:
        for tag_id in tag_ids:
            tag = db.session.get(Tag, tag_id)
            if tag and (tag.user_id == current_user.id or tag.is_global):
                if tag not in clip.tag_objects.all():
                    clip.tag_objects.append(tag)
                    tag.increment_usage()

        db.session.commit()

        tags = clip.tag_objects.all()
        return jsonify(
            {
                "tags": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "color": t.color,
                        "full_path": t.full_path,
                    }
                    for t in tags
                ]
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error adding clip tags: {e}")
        return jsonify({"error": "Failed to add tags"}), 500


@api_bp.route("/clips/<int:clip_id>/tags/<int:tag_id>", methods=["DELETE"])
@login_required
def remove_clip_tag(clip_id, tag_id):
    """
    Remove a tag from a clip.

    Args:
        clip_id: Clip ID
        tag_id: Tag ID

    Returns:
        JSON: Success message
    """
    clip = db.session.get(Clip, clip_id)

    if not clip:
        return jsonify({"error": "Clip not found"}), 404

    # Verify ownership via project
    if not clip.project or clip.project.user_id != current_user.id:
        return jsonify({"error": "Clip not found"}), 404

    tag = db.session.get(Tag, tag_id)

    if not tag:
        return jsonify({"error": "Tag not found"}), 404

    try:
        if tag in clip.tag_objects.all():
            clip.tag_objects.remove(tag)
            db.session.commit()

        return jsonify({"message": "Tag removed successfully"})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error removing clip tag: {e}")
        return jsonify({"error": "Failed to remove tag"}), 500

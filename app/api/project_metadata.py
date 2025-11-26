"""
Project metadata update endpoint.
"""

import structlog
from flask import jsonify, request
from flask_login import current_user, login_required

from app.api import api_bp

logger = structlog.get_logger(__name__)


@api_bp.route("/projects/<int:project_id>/metadata", methods=["PATCH"])
@login_required
def update_project_metadata_api(project_id):
    """Update project name, description, and tags."""
    from app.models import Project, db

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json(silent=True) or {}

    # Update fields if provided
    if "name" in data:
        name = (data["name"] or "").strip()
        if name:
            project.name = name

    if "description" in data:
        project.description = (data["description"] or "").strip() or None

    if "tags" in data:
        # Tags is a comma-separated string
        tags = (data["tags"] or "").strip()
        project.tags = tags if tags else None

    try:
        db.session.commit()
        logger.info(
            "project_metadata_updated",
            project_id=project.id,
            user_id=current_user.id,
        )
        return jsonify(
            {
                "success": True,
                "project": {
                    "id": project.id,
                    "name": project.name,
                    "description": project.description,
                    "tags": project.tags,
                },
            }
        )
    except Exception as e:
        db.session.rollback()
        logger.error(
            "project_metadata_update_failed",
            project_id=project.id,
            error=str(e),
        )
        return jsonify({"error": "Failed to update project"}), 500

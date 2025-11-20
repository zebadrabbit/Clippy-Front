"""
API endpoints for project templates.

Allows users to save and reuse project configurations as templates.
"""
from flask import current_app, jsonify, request
from flask_login import current_user, login_required

from app.api import api_bp
from app.models import Clip, CompilationTask, MediaFile, Project, db


@api_bp.route("/templates", methods=["GET"])
@login_required
def list_templates():
    """
    List all templates for the current user.

    Returns:
        JSON: List of template objects
    """
    templates = (
        CompilationTask.query.filter_by(user_id=current_user.id, is_template=True)
        .order_by(CompilationTask.updated_at.desc())
        .all()
    )

    return jsonify(
        {
            "templates": [
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "params": t.params,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                }
                for t in templates
            ]
        }
    )


@api_bp.route("/templates", methods=["POST"])
@login_required
def create_template():
    """
    Create a new template from a project or from scratch.

    Request JSON:
        - name: Template name (required)
        - description: Template description (optional)
        - project_id: Project to use as basis (optional)
        - params: Direct parameters (optional, used if no project_id)

    Returns:
        JSON: Created template object
    """
    data = request.get_json()

    if not data or not data.get("name"):
        return jsonify({"error": "Template name is required"}), 400

    name = data["name"]
    description = data.get("description", "")
    project_id = data.get("project_id")
    params = data.get("params", {})

    # If project_id provided, extract parameters from project
    if project_id:
        project = db.session.get(Project, project_id)
        if not project or project.user_id != current_user.id:
            return jsonify({"error": "Project not found"}), 404

        # Build params from project configuration
        params = {
            "output_resolution": project.output_resolution,
            "output_format": project.output_format,
            "quality": project.quality,
            "fps": project.fps,
            "transitions_enabled": project.transitions_enabled,
            "watermark_enabled": project.watermark_enabled,
        }

        # Add clip configuration
        clips = project.clips.order_by(Clip.order_index).all()
        if clips:
            params["clip_count"] = len(clips)
            # Store clip source patterns if available
            params["clip_sources"] = [
                {
                    "source_url": clip.source_url,
                    "source_platform": clip.source_platform,
                }
                for clip in clips
                if clip.source_url
            ]

        # Add intro/outro if set
        intro_clips = [
            c for c in clips if c.media_type and c.media_type.value == "intro"
        ]
        outro_clips = [
            c for c in clips if c.media_type and c.media_type.value == "outro"
        ]

        if intro_clips:
            params["intro_media_id"] = intro_clips[0].media_file_id
        if outro_clips:
            params["outro_media_id"] = outro_clips[0].media_file_id

    # Create template
    try:
        template = CompilationTask(
            user_id=current_user.id,
            name=name,
            description=description,
            is_template=True,
            params=params,
        )
        db.session.add(template)
        db.session.commit()

        current_app.logger.info(
            f"Template created: {template.id} by user {current_user.id}"
        )

        return (
            jsonify(
                {
                    "id": template.id,
                    "name": template.name,
                    "description": template.description,
                    "params": template.params,
                    "created_at": template.created_at.isoformat(),
                }
            ),
            201,
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating template: {e}")
        return jsonify({"error": "Failed to create template"}), 500


@api_bp.route("/templates/<int:template_id>", methods=["GET"])
@login_required
def get_template(template_id):
    """
    Get a specific template.

    Args:
        template_id: Template ID

    Returns:
        JSON: Template object
    """
    template = db.session.get(CompilationTask, template_id)

    if not template or template.user_id != current_user.id or not template.is_template:
        return jsonify({"error": "Template not found"}), 404

    return jsonify(
        {
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "params": template.params,
            "created_at": template.created_at.isoformat()
            if template.created_at
            else None,
            "updated_at": template.updated_at.isoformat()
            if template.updated_at
            else None,
        }
    )


@api_bp.route("/templates/<int:template_id>", methods=["PUT"])
@login_required
def update_template(template_id):
    """
    Update a template.

    Args:
        template_id: Template ID

    Request JSON:
        - name: Template name
        - description: Template description
        - params: Template parameters

    Returns:
        JSON: Updated template object
    """
    template = db.session.get(CompilationTask, template_id)

    if not template or template.user_id != current_user.id or not template.is_template:
        return jsonify({"error": "Template not found"}), 404

    data = request.get_json()

    if "name" in data:
        template.name = data["name"]
    if "description" in data:
        template.description = data["description"]
    if "params" in data:
        template.params = data["params"]

    try:
        db.session.commit()
        current_app.logger.info(
            f"Template updated: {template.id} by user {current_user.id}"
        )

        return jsonify(
            {
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "params": template.params,
                "updated_at": template.updated_at.isoformat()
                if template.updated_at
                else None,
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating template: {e}")
        return jsonify({"error": "Failed to update template"}), 500


@api_bp.route("/templates/<int:template_id>", methods=["DELETE"])
@login_required
def delete_template(template_id):
    """
    Delete a template.

    Args:
        template_id: Template ID

    Returns:
        JSON: Success message
    """
    template = db.session.get(CompilationTask, template_id)

    if not template or template.user_id != current_user.id or not template.is_template:
        return jsonify({"error": "Template not found"}), 404

    try:
        db.session.delete(template)
        db.session.commit()
        current_app.logger.info(
            f"Template deleted: {template_id} by user {current_user.id}"
        )

        return jsonify({"message": "Template deleted successfully"})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting template: {e}")
        return jsonify({"error": "Failed to delete template"}), 500


@api_bp.route("/templates/<int:template_id>/apply", methods=["POST"])
@login_required
def apply_template(template_id):
    """
    Create a new project from a template.

    Args:
        template_id: Template ID

    Request JSON:
        - project_name: Name for the new project (required)

    Returns:
        JSON: Created project object
    """
    template = db.session.get(CompilationTask, template_id)

    if not template or template.user_id != current_user.id or not template.is_template:
        return jsonify({"error": "Template not found"}), 404

    data = request.get_json()
    project_name = data.get("project_name") if data else None

    if not project_name:
        return jsonify({"error": "project_name is required"}), 400

    try:
        # Create new project with template parameters
        params = template.params or {}
        project = Project(
            name=project_name,
            user_id=current_user.id,
            output_resolution=params.get("output_resolution", "1080p"),
            output_format=params.get("output_format", "mp4"),
            quality=params.get("quality", "high"),
            fps=params.get("fps", 30),
            transitions_enabled=params.get("transitions_enabled", True),
            watermark_enabled=params.get("watermark_enabled", False),
        )
        db.session.add(project)
        db.session.flush()

        # Add intro/outro if specified in template
        if "intro_media_id" in params:
            intro_media = db.session.get(MediaFile, params["intro_media_id"])
            if intro_media and intro_media.user_id == current_user.id:
                project.intro_media_id = intro_media.id

        if "outro_media_id" in params:
            outro_media = db.session.get(MediaFile, params["outro_media_id"])
            if outro_media and outro_media.user_id == current_user.id:
                project.outro_media_id = outro_media.id

        db.session.commit()

        current_app.logger.info(
            f"Project created from template {template_id}: {project.id} by user {current_user.id}"
        )

        return (
            jsonify(
                {
                    "id": project.id,
                    "name": project.name,
                    "status": project.status.value,
                    "created_at": project.created_at.isoformat(),
                }
            ),
            201,
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error applying template: {e}")
        return jsonify({"error": "Failed to create project from template"}), 500

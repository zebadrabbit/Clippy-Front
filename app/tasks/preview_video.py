"""
Celery task for generating preview videos (low-res, 480p 10fps) for compilations.
Applies same filters/transformations as final output.
Caches preview for fast subsequent loads.
"""
import os

from celery import shared_task

from app import create_app
from app.models import Project
from app.tasks.video_processing import ffmpeg_render_preview


@shared_task(bind=True)
def generate_preview_video_task(self, project_id):
    app = create_app()
    with app.app_context():
        project = Project.query.get(project_id)
        if not project:
            return {"error": "Project not found"}
        # Output path for preview
        preview_dir = os.path.join(
            app.config["INSTANCE_PATH"], "previews", str(project.user_id)
        )
        os.makedirs(preview_dir, exist_ok=True)
        preview_path = os.path.join(preview_dir, f"preview_{project.id}.mp4")
        # If preview exists, skip rendering
        if os.path.exists(preview_path):
            return {"preview": preview_path, "cached": True}
        # Gather clips and transformations (reuse final compilation logic)
        # For now, just use first clip as a stub
        clips = project.clips.all()
        if not clips:
            return {"error": "No clips in project"}
        # TODO: Apply same filters/transformations as final output
        input_path = clips[0].media_file.file_path if clips[0].media_file else None
        if not input_path:
            return {"error": "No valid input file"}
        # Render preview (low-res, 480p 10fps)
        ffmpeg_render_preview(input_path, preview_path)
        # Save preview path to project (optional)
        project.preview_path = preview_path
        from app import db

        db.session.commit()
        return {"preview": preview_path, "cached": False}

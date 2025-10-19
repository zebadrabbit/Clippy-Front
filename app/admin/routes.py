"""
Admin panel routes for Clippy platform management.

This module provides administrative functionality including user management,
system monitoring, and platform configuration for admin users only.
"""
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func

from app.models import (
    Clip,
    MediaFile,
    ProcessingJob,
    Project,
    ProjectStatus,
    User,
    UserRole,
    db,
)
from app.tasks.celery_app import celery_app
from app.tasks.media_maintenance import (
    dedupe_media_task,
    reindex_media_task,
)
from app.version import get_changelog, get_version

# Create admin blueprint
admin_bp = Blueprint("admin", __name__)


def admin_required(f):
    """
    Decorator to ensure only admin users can access admin routes.

    Args:
        f: Function to wrap

    Returns:
        Function: Wrapped function with admin check
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash("Access denied. Admin privileges required.", "danger")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)

    return decorated_function


@admin_bp.route("/")
@login_required
@admin_required
def dashboard():
    """
    Admin dashboard with system overview and statistics.

    Displays key metrics, recent activity, and system status
    for platform administrators.

    Returns:
        Response: Rendered admin dashboard template
    """
    # Get system statistics
    stats = {
        "total_users": User.query.count(),
        "active_users": User.query.filter_by(is_active=True).count(),
        "admin_users": User.query.filter_by(role=UserRole.ADMIN).count(),
        "total_projects": Project.query.count(),
        "active_projects": Project.query.filter_by(
            status=ProjectStatus.PROCESSING
        ).count(),
        "completed_projects": Project.query.filter_by(
            status=ProjectStatus.COMPLETED
        ).count(),
        "total_media_files": MediaFile.query.count(),
        "total_clips": Clip.query.count(),
        "pending_jobs": ProcessingJob.query.filter_by(status="pending").count(),
    }

    # Get recent activity (last 24 hours)
    yesterday = datetime.utcnow() - timedelta(days=1)
    recent_stats = {
        "new_users": User.query.filter(User.created_at >= yesterday).count(),
        "new_projects": Project.query.filter(Project.created_at >= yesterday).count(),
        "new_media_files": MediaFile.query.filter(
            MediaFile.uploaded_at >= yesterday
        ).count(),
        "completed_jobs": ProcessingJob.query.filter(
            ProcessingJob.completed_at >= yesterday, ProcessingJob.status == "success"
        ).count(),
    }

    # Get recent users and projects
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    recent_projects = Project.query.order_by(Project.created_at.desc()).limit(5).all()

    # Calculate storage usage
    total_storage = db.session.query(func.sum(MediaFile.file_size)).scalar() or 0
    total_storage_mb = total_storage / (1024 * 1024)

    return render_template(
        "admin/dashboard.html",
        title="Admin Dashboard",
        stats=stats,
        recent_stats=recent_stats,
        recent_users=recent_users,
        recent_projects=recent_projects,
        total_storage_mb=total_storage_mb,
        version=get_version(),
    )


@admin_bp.route("/users")
@login_required
@admin_required
def users():
    """
    User management interface with listing and filtering.

    Returns:
        Response: Rendered users management template
    """
    page = request.args.get("page", 1, type=int)
    per_page = current_app.config.get("ADMIN_USERS_PER_PAGE", 25)

    # Filter options
    role_filter = request.args.get("role")
    status_filter = request.args.get("status")
    search_query = request.args.get("search", "").strip()

    # Build query
    query = User.query

    if role_filter and role_filter in [r.value for r in UserRole]:
        query = query.filter_by(role=UserRole(role_filter))

    if status_filter == "active":
        query = query.filter_by(is_active=True)
    elif status_filter == "inactive":
        query = query.filter_by(is_active=False)

    if search_query:
        search_term = f"%{search_query}%"
        query = query.filter(
            (User.username.ilike(search_term))
            | (User.email.ilike(search_term))
            | (User.first_name.ilike(search_term))
            | (User.last_name.ilike(search_term))
        )

    users_pagination = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template(
        "admin/users.html",
        title="User Management",
        users=users_pagination.items,
        pagination=users_pagination,
        role_filter=role_filter,
        status_filter=status_filter,
        search_query=search_query,
        user_roles=UserRole,
    )


@admin_bp.route("/users/<int:user_id>")
@login_required
@admin_required
def user_details(user_id):
    """
    Detailed view of a specific user account.

    Args:
        user_id: ID of the user to display

    Returns:
        Response: Rendered user details template
    """
    user = db.session.get(User, user_id)
    if not user:
        return abort(404)

    # Get user statistics
    user_stats = {
        "total_projects": user.projects.count(),
        "completed_projects": user.projects.filter_by(
            status=ProjectStatus.COMPLETED
        ).count(),
        "total_media_files": user.media_files.count(),
        "total_storage": db.session.query(func.sum(MediaFile.file_size))
        .filter_by(user_id=user_id)
        .scalar()
        or 0,
        # processing_jobs relationship backref may be a list; count explicitly via query
        "processing_jobs": ProcessingJob.query.filter_by(user_id=user_id).count(),
    }

    # Convert storage to MB
    user_stats["total_storage_mb"] = user_stats["total_storage"] / (1024 * 1024)

    # Get recent activity
    recent_projects = user.projects.order_by(Project.created_at.desc()).limit(5).all()
    recent_media = (
        user.media_files.order_by(MediaFile.uploaded_at.desc()).limit(5).all()
    )

    return render_template(
        "admin/user_details.html",
        title=f"User: {user.username}",
        user=user,
        user_stats=user_stats,
        recent_projects=recent_projects,
        recent_media=recent_media,
    )


@admin_bp.route("/users/<int:user_id>/toggle-status", methods=["POST"])
@login_required
@admin_required
def toggle_user_status(user_id):
    """
    Toggle user active/inactive status.

    Args:
        user_id: ID of the user to toggle

    Returns:
        Response: JSON response with new status
    """
    if user_id == current_user.id:
        return jsonify({"error": "Cannot deactivate your own account"}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    try:
        user.is_active = not user.is_active
        db.session.commit()

        status = "activated" if user.is_active else "deactivated"
        current_app.logger.info(
            f"User {user.username} (ID: {user_id}) {status} by admin {current_user.username}"
        )

        return jsonify(
            {
                "success": True,
                "is_active": user.is_active,
                "message": f"User {user.username} has been {status}",
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error toggling user status: {str(e)}")
        return jsonify({"error": "Failed to update user status"}), 500


@admin_bp.route("/users/<int:user_id>/promote", methods=["POST"])
@login_required
@admin_required
def promote_user(user_id):
    """
    Promote user to admin or demote admin to user.

    Args:
        user_id: ID of the user to promote/demote

    Returns:
        Response: JSON response with new role
    """
    if user_id == current_user.id:
        return jsonify({"error": "Cannot modify your own admin status"}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    try:
        if user.role == UserRole.ADMIN:
            user.role = UserRole.USER
            action = "demoted from admin"
        else:
            user.role = UserRole.ADMIN
            action = "promoted to admin"

        db.session.commit()

        current_app.logger.warning(
            f"User {user.username} (ID: {user_id}) {action} by admin {current_user.username}"
        )

        return jsonify(
            {
                "success": True,
                "role": user.role.value,
                "message": f"User {user.username} has been {action}",
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating user role: {str(e)}")
        return jsonify({"error": "Failed to update user role"}), 500


@admin_bp.route("/projects")
@login_required
@admin_required
def projects():
    """
    Project management interface for admins.

    Returns:
        Response: Rendered projects management template
    """
    page = request.args.get("page", 1, type=int)
    per_page = current_app.config.get("ADMIN_PROJECTS_PER_PAGE", 25)

    # Filter options
    status_filter = request.args.get("status")
    user_filter = request.args.get("user_id", type=int)

    # Build query
    query = Project.query

    if status_filter and status_filter in [s.value for s in ProjectStatus]:
        query = query.filter_by(status=ProjectStatus(status_filter))

    if user_filter:
        query = query.filter_by(user_id=user_filter)

    projects_pagination = query.order_by(Project.updated_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Get users for filter dropdown
    users_with_projects = db.session.query(User).join(Project).distinct().all()

    return render_template(
        "admin/projects.html",
        title="Project Management",
        projects=projects_pagination.items,
        pagination=projects_pagination,
        status_filter=status_filter,
        user_filter=user_filter,
        users_with_projects=users_with_projects,
        project_statuses=ProjectStatus,
    )


@admin_bp.route("/system")
@login_required
@admin_required
def system_info():
    """
    System information and configuration panel.

    Returns:
        Response: Rendered system info template
    """
    # Get database statistics
    db_stats = {
        "users": User.query.count(),
        "projects": Project.query.count(),
        "media_files": MediaFile.query.count(),
        "clips": Clip.query.count(),
        "processing_jobs": ProcessingJob.query.count(),
    }

    # Get storage statistics
    storage_stats = {
        "total_size": db.session.query(func.sum(MediaFile.file_size)).scalar() or 0,
        "by_type": {},
    }

    # Storage by media type
    for media_type in ["intro", "outro", "transition", "clip"]:
        size = (
            db.session.query(func.sum(MediaFile.file_size))
            .filter(MediaFile.media_type == media_type)
            .scalar()
            or 0
        )
        storage_stats["by_type"][media_type] = size / (1024 * 1024)  # Convert to MB

    storage_stats["total_size_mb"] = storage_stats["total_size"] / (1024 * 1024)

    # Get processing job statistics
    job_stats = {}
    for status in ["pending", "started", "success", "failure", "retry", "revoked"]:
        job_stats[status] = ProcessingJob.query.filter_by(status=status).count()

    return render_template(
        "admin/system_info.html",
        title="System Information",
        db_stats=db_stats,
        storage_stats=storage_stats,
        job_stats=job_stats,
        version=get_version(),
        changelog=get_changelog(),
    )


@admin_bp.route("/logs")
@login_required
@admin_required
def logs():
    """
    System logs viewer for debugging and monitoring.

    Returns:
        Response: Rendered logs template
    """
    # This would typically read from log files
    # For now, return a placeholder
    return render_template(
        "admin/logs.html",
        title="System Logs",
        logs=[
            {
                "timestamp": datetime.utcnow(),
                "level": "INFO",
                "message": "System started",
            },
            {
                "timestamp": datetime.utcnow(),
                "level": "INFO",
                "message": "Database connected",
            },
        ],
    )


@admin_bp.route("/maintenance", methods=["GET", "POST"])
@login_required
@admin_required
def maintenance():
    """Admin-only maintenance actions: reindex media and deduplicate entries."""
    if request.method == "POST":
        action = request.form.get("action")
        if action == "reindex":
            task = reindex_media_task.delay(False)
            flash(
                f"Started reindex task ({task.id}). Check Jobs in the UI to monitor.",
                "info",
            )
        elif action == "dedupe_media":
            user_id = request.form.get("user_id", type=int)
            dry_run = request.form.get("dry_run") == "1"
            task = dedupe_media_task.delay(dry_run=dry_run, user_id=user_id)
            flash(
                f"Started media deduplication task ({task.id}). This keeps newest entries and removes duplicates.",
                "warning",
            )
        return redirect(url_for("admin.maintenance"))

    # GET: show simple form
    return render_template("admin/maintenance.html", title="Maintenance")


@admin_bp.route("/workers")
@login_required
@admin_required
def workers():
    """Show Celery worker nodes and queues.

    Uses Celery's inspect API to display connected workers, their active queues,
    and basic runtime statistics. Useful when running remote GPU workers.
    """
    info = {
        "stats": {},
        "active": {},
        "registered": {},
        "scheduled": {},
        "active_queues": {},
        "errors": [],
    }
    try:
        insp = celery_app.control.inspect(timeout=2)
        info["stats"] = insp.stats() or {}
        info["active"] = insp.active() or {}
        info["registered"] = insp.registered() or {}
        info["scheduled"] = insp.scheduled() or {}
        info["active_queues"] = insp.active_queues() or {}
    except Exception as e:
        info["errors"].append(str(e))

    # Normalize into a list of workers for easier rendering
    workers_list = []
    keys = set()
    for d in (
        info["stats"],
        info["active"],
        info["registered"],
        info["scheduled"],
        info["active_queues"],
    ):
        if isinstance(d, dict):
            keys.update(d.keys())
    for name in sorted(keys):
        workers_list.append(
            {
                "name": name,
                "stats": (info["stats"] or {}).get(name) or {},
                "active": (info["active"] or {}).get(name) or [],
                "registered": (info["registered"] or {}).get(name) or [],
                "scheduled": (info["scheduled"] or {}).get(name) or [],
                "queues": (info["active_queues"] or {}).get(name) or [],
            }
        )

    return render_template(
        "admin/workers.html",
        title="Workers",
        workers=workers_list,
        raw=info,
    )


@admin_bp.route("/workers.json")
@login_required
@admin_required
def workers_json():
    """JSON view of Celery workers and queues."""
    try:
        insp = celery_app.control.inspect(timeout=2)
        payload = {
            "stats": insp.stats() or {},
            "active": insp.active() or {},
            "registered": insp.registered() or {},
            "scheduled": insp.scheduled() or {},
            "active_queues": insp.active_queues() or {},
        }
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 502

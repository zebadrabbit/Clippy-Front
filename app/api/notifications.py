"""
API endpoints for user notifications.
"""

from flask import jsonify, request
from flask_login import current_user, login_required

# Import the shared blueprint instance
from app.api import api_bp
from app.models import Notification, db
from app.notifications import get_unread_count, get_user_notifications, mark_all_as_read


@api_bp.route("/notifications", methods=["GET"])
@login_required
def list_notifications():
    """
    Get notifications for the current user.

    Query parameters:
        limit: Maximum number of notifications (default: 20, max: 100)
        offset: Pagination offset (default: 0)
        unread_only: Only return unread notifications (default: false)

    Returns:
        {
            "notifications": [
                {
                    "id": int,
                    "type": str,
                    "message": str,
                    "is_read": bool,
                    "created_at": str,
                    "read_at": str | null,
                    "actor": {...} | null,
                    "team": {...} | null,
                    "project": {...} | null,
                    "context": {...}
                }
            ],
            "unread_count": int,
            "total": int
        }
    """
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))
    unread_only = request.args.get("unread_only", "false").lower() == "true"

    notifications = get_user_notifications(
        user_id=current_user.id, limit=limit, offset=offset, unread_only=unread_only
    )

    return jsonify(
        {
            "notifications": [n.to_dict() for n in notifications],
            "unread_count": get_unread_count(current_user.id),
            "total": len(notifications),
        }
    )


@api_bp.route("/notifications/unread-count", methods=["GET"])
@login_required
def unread_count():
    """
    Get count of unread notifications for the current user.

    Returns:
        {"count": int}
    """
    return jsonify({"count": get_unread_count(current_user.id)})


@api_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notification_id):
    """
    Mark a notification as read.

    Returns:
        {"message": "Notification marked as read"}
    """
    notification = db.session.get(Notification, notification_id)

    if not notification:
        return jsonify({"error": "Notification not found"}), 404

    if notification.user_id != current_user.id:
        return jsonify({"error": "Permission denied"}), 403

    notification.mark_as_read()

    return jsonify({"message": "Notification marked as read"})


@api_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_notifications_read():
    """
    Mark all notifications as read for the current user.

    Returns:
        {"message": "All notifications marked as read"}
    """
    mark_all_as_read(current_user.id)

    return jsonify({"message": "All notifications marked as read"})


@api_bp.route("/notifications/stream", methods=["GET"])
@login_required
def notification_stream():
    """
    Server-Sent Events stream for real-time notifications.

    This endpoint keeps the connection open and pushes new notifications
    as they arrive. Clients should listen with EventSource.

    Returns:
        SSE stream of notification events
    """
    import json
    import time
    from datetime import datetime

    from flask import current_app

    # Capture app and user_id before entering the generator
    # These need to be captured while we're still in the request context
    app = current_app._get_current_object()
    user_id = current_user.id

    def generate():
        """Generate SSE events for new notifications."""
        # Push application context for database access
        with app.app_context():
            # Send initial connection message
            yield f"data: {{'type': 'connected', 'timestamp': '{datetime.utcnow().isoformat()}'}}\n\n"

            last_check = datetime.utcnow()

            while True:
                try:
                    # Check for new notifications since last check
                    new_notifications = (
                        db.session.query(Notification)
                        .filter(
                            Notification.user_id == user_id,
                            Notification.created_at > last_check,
                        )
                        .order_by(Notification.created_at.asc())
                        .all()
                    )

                    for notification in new_notifications:
                        data = json.dumps(notification.to_dict())
                        yield f"data: {data}\n\n"

                    last_check = datetime.utcnow()

                    # Send keepalive every 30 seconds
                    yield f": keepalive {datetime.utcnow().isoformat()}\n\n"

                except Exception as e:
                    # Log error but don't crash the stream
                    app.logger.error(f"SSE stream error: {e}", exc_info=True)
                    yield "data: {'type': 'error', 'message': 'Internal error'}\n\n"

                # Sleep for 5 seconds before checking again
                time.sleep(5)

    return generate(), {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
    }


@api_bp.route("/notification-preferences", methods=["GET"])
@login_required
def get_notification_preferences():
    """
    Get notification preferences for the current user.

    Returns:
        {
            "preferences": {
                "email_compilation_complete": bool,
                "email_compilation_failed": bool,
                "email_team_invitation": bool,
                "email_team_member_added": bool,
                "email_project_shared": bool,
                "email_mention": bool,
                "email_digest_enabled": bool,
                "email_digest_frequency": str,
                "email_digest_time": str,
                "inapp_all_enabled": bool
            }
        }
    """
    from app.models import NotificationPreferences

    prefs = NotificationPreferences.get_or_create(current_user.id)
    return jsonify({"preferences": prefs.to_dict()})


@api_bp.route("/notification-preferences", methods=["PUT"])
@login_required
def update_notification_preferences():
    """
    Update notification preferences for the current user.

    Request body:
        {
            "email_compilation_complete": bool (optional),
            "email_compilation_failed": bool (optional),
            "email_team_invitation": bool (optional),
            "email_team_member_added": bool (optional),
            "email_project_shared": bool (optional),
            "email_mention": bool (optional),
            "email_digest_enabled": bool (optional),
            "email_digest_frequency": str (optional, "daily" or "weekly"),
            "email_digest_time": str (optional, "HH:MM" format),
            "inapp_all_enabled": bool (optional)
        }

    Returns:
        {
            "success": true,
            "preferences": { ... }
        }
    """
    from app.models import NotificationPreferences

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    prefs = NotificationPreferences.get_or_create(current_user.id)

    # Update fields that were provided
    updatable_fields = [
        "email_compilation_complete",
        "email_compilation_failed",
        "email_team_invitation",
        "email_team_member_added",
        "email_project_shared",
        "email_mention",
        "email_digest_enabled",
        "email_digest_frequency",
        "email_digest_time",
        "inapp_all_enabled",
    ]

    for field in updatable_fields:
        if field in data:
            # Validate email_digest_frequency
            if field == "email_digest_frequency" and data[field] not in [
                "daily",
                "weekly",
            ]:
                return (
                    jsonify(
                        {
                            "error": f"Invalid value for {field}, must be 'daily' or 'weekly'"
                        }
                    ),
                    400,
                )

            # Validate email_digest_time format (HH:MM)
            if field == "email_digest_time":
                import re

                if not re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", data[field]):
                    return (
                        jsonify(
                            {
                                "error": f"Invalid value for {field}, must be in HH:MM format (00:00-23:59)"
                            }
                        ),
                        400,
                    )

            setattr(prefs, field, data[field])

    db.session.commit()

    return jsonify({"success": True, "preferences": prefs.to_dict()})

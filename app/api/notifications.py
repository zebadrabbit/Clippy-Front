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
    import time
    from datetime import datetime

    def generate():
        """Generate SSE events for new notifications."""
        # Send initial connection message
        yield f"data: {{'type': 'connected', 'timestamp': '{datetime.utcnow().isoformat()}'}}\n\n"

        last_check = datetime.utcnow()

        while True:
            # Check for new notifications since last check
            new_notifications = (
                db.session.query(Notification)
                .filter(
                    Notification.user_id == current_user.id,
                    Notification.created_at > last_check,
                )
                .order_by(Notification.created_at.asc())
                .all()
            )

            for notification in new_notifications:
                import json

                data = json.dumps(notification.to_dict())
                yield f"data: {data}\n\n"

            last_check = datetime.utcnow()

            # Send keepalive every 30 seconds
            yield f": keepalive {datetime.utcnow().isoformat()}\n\n"

            # Sleep for 5 seconds before checking again
            time.sleep(5)

    return generate(), {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
    }

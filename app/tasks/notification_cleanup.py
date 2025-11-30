"""
Celery task for cleaning up old read notifications.
Runs as a scheduled task via Celery Beat.
"""
from datetime import datetime, timedelta

import structlog
from celery import shared_task

from app import create_app
from app.models import Notification, db

logger = structlog.get_logger(__name__)


@shared_task(bind=True)
def cleanup_old_notifications_task(self, retention_days: int = 30):
    """
    Delete read notifications older than the retention period.

    Unread notifications are never deleted to ensure users don't miss
    important information.

    Args:
        retention_days: Number of days to retain read notifications (default: 30)

    Returns:
        dict: Cleanup statistics
    """
    app = create_app()
    with app.app_context():
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

            logger.info(
                "notification_cleanup_started",
                retention_days=retention_days,
                cutoff_date=cutoff_date.isoformat(),
            )

            # Count notifications to be deleted
            to_delete = (
                db.session.query(Notification)
                .filter(
                    Notification.is_read.is_(True), Notification.read_at < cutoff_date
                )
                .count()
            )

            if to_delete == 0:
                logger.info("notification_cleanup_complete", deleted=0)
                return {"deleted": 0, "message": "No old notifications to clean up"}

            # Delete old read notifications
            deleted = (
                db.session.query(Notification)
                .filter(
                    Notification.is_read.is_(True), Notification.read_at < cutoff_date
                )
                .delete(synchronize_session=False)
            )

            db.session.commit()

            logger.info(
                "notification_cleanup_complete",
                deleted=deleted,
                cutoff_date=cutoff_date.isoformat(),
            )

            return {
                "deleted": deleted,
                "cutoff_date": cutoff_date.isoformat(),
                "message": f"Deleted {deleted} read notification(s) older than {retention_days} days",
            }

        except Exception as e:
            db.session.rollback()
            logger.error(
                "notification_cleanup_failed",
                error=str(e),
                exc_info=True,
            )
            return {"error": str(e), "deleted": 0}

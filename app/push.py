"""
Push notification sending utilities using Web Push API.
"""
import json

import structlog
from pywebpush import WebPushException, webpush

from app.models import PushSubscription, User, db

logger = structlog.get_logger(__name__)


def send_push_notification(
    user: User,
    title: str,
    body: str,
    notification_type: str = None,
    project_id: int = None,
    team_id: int = None,
    icon: str = None,
    vapid_private_key: str = None,
    vapid_claims: dict = None,
):
    """
    Send a push notification to all of a user's subscribed devices.

    Args:
        user: User to send notification to
        title: Notification title
        body: Notification body text
        notification_type: Type of notification (for routing on click)
        project_id: Associated project ID (optional)
        team_id: Associated team ID (optional)
        icon: Custom icon URL (optional)
        vapid_private_key: VAPID private key for authentication
        vapid_claims: VAPID claims (sub email)

    Returns:
        dict: Statistics about sent notifications
    """
    if not vapid_private_key or not vapid_claims:
        logger.warning(
            "push_notification_skipped",
            reason="VAPID keys not configured",
            user_id=user.id,
        )
        return {"sent": 0, "failed": 0, "total": 0}

    # Get all push subscriptions for this user
    subscriptions = PushSubscription.query.filter_by(user_id=user.id).all()

    if not subscriptions:
        logger.debug(
            "push_notification_skipped",
            reason="No push subscriptions",
            user_id=user.id,
        )
        return {"sent": 0, "failed": 0, "total": 0}

    # Prepare notification payload
    payload = {
        "title": title,
        "body": body,
        "icon": icon or "/static/img/logo.png",
        "badge": "/static/img/badge.png",
        "tag": f"notification-{notification_type or 'general'}",
        "data": {
            "type": notification_type,
            "project_id": project_id,
            "team_id": team_id,
        },
    }

    sent = 0
    failed = 0
    expired_subscriptions = []

    for subscription in subscriptions:
        try:
            # Prepare subscription info for pywebpush
            subscription_info = {
                "endpoint": subscription.endpoint,
                "keys": {
                    "p256dh": subscription.p256dh_key,
                    "auth": subscription.auth_key,
                },
            }

            # Send push notification
            webpush(
                subscription_info=subscription_info,
                data=json.dumps(payload),
                vapid_private_key=vapid_private_key,
                vapid_claims=vapid_claims,
            )

            # Update last_used_at
            from datetime import datetime

            subscription.last_used_at = datetime.utcnow()
            sent += 1

            logger.debug(
                "push_notification_sent",
                user_id=user.id,
                subscription_id=subscription.id,
                title=title,
            )

        except WebPushException as e:
            failed += 1
            logger.warning(
                "push_notification_failed",
                user_id=user.id,
                subscription_id=subscription.id,
                error=str(e),
                status_code=e.response.status_code if e.response else None,
            )

            # Remove expired/invalid subscriptions
            if e.response and e.response.status_code in (404, 410):
                expired_subscriptions.append(subscription)
                logger.info(
                    "push_subscription_expired",
                    user_id=user.id,
                    subscription_id=subscription.id,
                )

        except Exception as e:
            failed += 1
            logger.error(
                "push_notification_error",
                user_id=user.id,
                subscription_id=subscription.id,
                error=str(e),
                exc_info=True,
            )

    # Clean up expired subscriptions
    for subscription in expired_subscriptions:
        db.session.delete(subscription)

    db.session.commit()

    total = len(subscriptions)
    logger.info(
        "push_notification_batch_complete",
        user_id=user.id,
        sent=sent,
        failed=failed,
        total=total,
        expired=len(expired_subscriptions),
    )

    return {"sent": sent, "failed": failed, "total": total}

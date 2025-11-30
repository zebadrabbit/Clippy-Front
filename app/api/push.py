"""
API endpoints for Web Push notifications.
"""
from flask import current_app, jsonify, request
from flask_login import current_user, login_required

from app.api import api_bp
from app.models import PushSubscription, db


@api_bp.route("/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    """
    Subscribe to push notifications.

    Request body (from PushSubscription.toJSON()):
        {
            "endpoint": "https://...",
            "keys": {
                "p256dh": "...",
                "auth": "..."
            }
        }

    Returns:
        {"message": "Subscription saved", "id": int}
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    endpoint = data.get("endpoint")
    keys = data.get("keys", {})
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        return jsonify({"error": "Missing required subscription fields"}), 400

    # Check if subscription already exists
    existing = PushSubscription.query.filter_by(endpoint=endpoint).first()

    if existing:
        # Update last_used_at
        from datetime import datetime

        existing.last_used_at = datetime.utcnow()
        db.session.commit()

        current_app.logger.info(
            f"Push subscription refreshed for user {current_user.id}: {endpoint[:50]}..."
        )

        return (
            jsonify({"message": "Subscription already exists", "id": existing.id}),
            200,
        )

    # Create new subscription
    subscription = PushSubscription(
        user_id=current_user.id,
        endpoint=endpoint,
        p256dh_key=p256dh,
        auth_key=auth,
        user_agent=request.headers.get("User-Agent"),
    )

    db.session.add(subscription)
    db.session.commit()

    current_app.logger.info(
        f"Push subscription created for user {current_user.id}: {endpoint[:50]}..."
    )

    return jsonify({"message": "Subscription saved", "id": subscription.id}), 201


@api_bp.route("/push/unsubscribe", methods=["POST"])
@login_required
def push_unsubscribe():
    """
    Unsubscribe from push notifications.

    Request body:
        {
            "endpoint": "https://..."
        }

    Returns:
        {"message": "Subscription removed"}
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    endpoint = data.get("endpoint")
    if not endpoint:
        return jsonify({"error": "Missing endpoint"}), 400

    subscription = PushSubscription.query.filter_by(
        endpoint=endpoint, user_id=current_user.id
    ).first()

    if not subscription:
        return jsonify({"error": "Subscription not found"}), 404

    db.session.delete(subscription)
    db.session.commit()

    current_app.logger.info(
        f"Push subscription removed for user {current_user.id}: {endpoint[:50]}..."
    )

    return jsonify({"message": "Subscription removed"}), 200


@api_bp.route("/push/subscriptions", methods=["GET"])
@login_required
def list_push_subscriptions():
    """
    List all push subscriptions for the current user.

    Returns:
        {
            "subscriptions": [
                {
                    "id": int,
                    "endpoint": str,
                    "created_at": str,
                    "last_used_at": str
                }
            ]
        }
    """
    subscriptions = PushSubscription.query.filter_by(user_id=current_user.id).all()

    return (
        jsonify(
            {
                "subscriptions": [
                    {
                        "id": sub.id,
                        "endpoint": sub.endpoint[:100] + "..."
                        if len(sub.endpoint) > 100
                        else sub.endpoint,
                        "created_at": sub.created_at.isoformat()
                        if sub.created_at
                        else None,
                        "last_used_at": sub.last_used_at.isoformat()
                        if sub.last_used_at
                        else None,
                        "user_agent": sub.user_agent,
                    }
                    for sub in subscriptions
                ]
            }
        ),
        200,
    )

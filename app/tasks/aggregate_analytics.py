"""
Background task for aggregating clip analytics data.

Runs periodically to compute summary statistics for games and creators,
improving query performance for the analytics dashboard.
"""
from datetime import datetime, timedelta

import structlog
from sqlalchemy import func

from app.models import (
    ClipAnalytics,
    CreatorAnalytics,
    GameAnalytics,
    User,
    db,
)
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="aggregate_analytics")
def aggregate_analytics_task(user_id=None, period="day"):
    """
    Aggregate analytics data for games and creators.

    Args:
        user_id: Optional user ID to aggregate for (None = all users)
        period: Period type - 'day', 'week', 'month', 'all_time'

    Returns:
        dict: Summary of aggregation results
    """
    logger.info("analytics_aggregation_started", user_id=user_id, period=period)

    try:
        # Determine date range for this period
        now = datetime.utcnow()
        if period == "day":
            period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            period_end = period_start + timedelta(days=1)
        elif period == "week":
            # Start of current week (Monday)
            period_start = now - timedelta(days=now.weekday())
            period_start = period_start.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            period_end = period_start + timedelta(weeks=1)
        elif period == "month":
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # Next month
            if now.month == 12:
                period_end = period_start.replace(year=period_start.year + 1, month=1)
            else:
                period_end = period_start.replace(month=period_start.month + 1)
        else:  # all_time
            period_start = datetime(2020, 1, 1)  # Arbitrary early date
            period_end = now + timedelta(days=1)

        # Get users to process
        if user_id:
            users = [User.query.get(user_id)]
        else:
            users = User.query.all()

        games_aggregated = 0
        creators_aggregated = 0

        for user in users:
            if not user:
                continue

            # Aggregate game analytics
            games_aggregated += _aggregate_game_analytics(
                user.id, period, period_start, period_end
            )

            # Aggregate creator analytics
            creators_aggregated += _aggregate_creator_analytics(
                user.id, period, period_start, period_end
            )

        logger.info(
            "analytics_aggregation_completed",
            user_id=user_id,
            period=period,
            games=games_aggregated,
            creators=creators_aggregated,
        )

        return {
            "success": True,
            "games_aggregated": games_aggregated,
            "creators_aggregated": creators_aggregated,
        }

    except Exception as e:
        logger.error("analytics_aggregation_failed", error=str(e), exc_info=e)
        return {"success": False, "error": str(e)}


def _aggregate_game_analytics(user_id, period, period_start, period_end):
    """Aggregate analytics for games."""
    # Query all clip analytics for this user in this period
    analytics_query = (
        db.session.query(
            ClipAnalytics.game_name,
            ClipAnalytics.game_id,
            func.count(ClipAnalytics.id).label("clip_count"),
            func.sum(ClipAnalytics.view_count).label("total_views"),
            func.avg(ClipAnalytics.view_count).label("avg_views"),
            func.sum(ClipAnalytics.discord_shares).label("discord_shares"),
            func.sum(ClipAnalytics.discord_reactions).label("discord_reactions"),
            func.count(func.distinct(ClipAnalytics.creator_name)).label(
                "unique_creators"
            ),
            func.max(ClipAnalytics.view_count).label("top_clip_views"),
        )
        .filter(ClipAnalytics.user_id == user_id)
        .filter(ClipAnalytics.game_name.isnot(None))
    )

    # Apply period filter (unless all_time)
    if period != "all_time":
        analytics_query = analytics_query.filter(
            ClipAnalytics.clip_created_at >= period_start,
            ClipAnalytics.clip_created_at < period_end,
        )

    analytics_query = analytics_query.group_by(
        ClipAnalytics.game_name, ClipAnalytics.game_id
    )

    results = analytics_query.all()

    count = 0
    for row in results:
        if not row.game_name:
            continue

        # Find or create GameAnalytics record
        game_analytics = GameAnalytics.query.filter_by(
            user_id=user_id,
            game_name=row.game_name,
            period_type=period,
            period_start=period_start,
        ).first()

        if not game_analytics:
            game_analytics = GameAnalytics(
                user_id=user_id,
                game_name=row.game_name,
                game_id=row.game_id,
                period_type=period,
                period_start=period_start,
                period_end=period_end,
            )
            db.session.add(game_analytics)

        # Update aggregated metrics
        game_analytics.clip_count = row.clip_count
        game_analytics.total_views = int(row.total_views or 0)
        game_analytics.avg_view_count = round(row.avg_views or 0, 1)
        game_analytics.discord_shares = int(row.discord_shares or 0)
        game_analytics.discord_reactions = int(row.discord_reactions or 0)
        game_analytics.unique_creators = row.unique_creators
        game_analytics.top_clip_views = int(row.top_clip_views or 0)

        count += 1

    db.session.commit()
    return count


def _aggregate_creator_analytics(user_id, period, period_start, period_end):
    """Aggregate analytics for creators."""
    # Query all clip analytics for this user in this period
    analytics_query = (
        db.session.query(
            ClipAnalytics.creator_name,
            ClipAnalytics.creator_id,
            ClipAnalytics.creator_platform,
            func.count(ClipAnalytics.id).label("clip_count"),
            func.sum(ClipAnalytics.view_count).label("total_views"),
            func.avg(ClipAnalytics.view_count).label("avg_views"),
            func.sum(ClipAnalytics.discord_shares).label("discord_shares"),
            func.sum(ClipAnalytics.discord_reactions).label("discord_reactions"),
            func.count(func.distinct(ClipAnalytics.game_name)).label("unique_games"),
        )
        .filter(ClipAnalytics.user_id == user_id)
        .filter(ClipAnalytics.creator_name.isnot(None))
    )

    # Apply period filter (unless all_time)
    if period != "all_time":
        analytics_query = analytics_query.filter(
            ClipAnalytics.clip_created_at >= period_start,
            ClipAnalytics.clip_created_at < period_end,
        )

    analytics_query = analytics_query.group_by(
        ClipAnalytics.creator_name,
        ClipAnalytics.creator_id,
        ClipAnalytics.creator_platform,
    )

    results = analytics_query.all()

    count = 0
    for row in results:
        if not row.creator_name:
            continue

        # Find or create CreatorAnalytics record
        creator_analytics = CreatorAnalytics.query.filter_by(
            user_id=user_id,
            creator_name=row.creator_name,
            period_type=period,
            period_start=period_start,
        ).first()

        if not creator_analytics:
            creator_analytics = CreatorAnalytics(
                user_id=user_id,
                creator_name=row.creator_name,
                creator_id=row.creator_id,
                creator_platform=row.creator_platform,
                period_type=period,
                period_start=period_start,
                period_end=period_end,
            )
            db.session.add(creator_analytics)

        # Update aggregated metrics
        creator_analytics.clip_count = row.clip_count
        creator_analytics.total_views = int(row.total_views or 0)
        creator_analytics.avg_view_count = round(row.avg_views or 0, 1)
        creator_analytics.discord_shares = int(row.discord_shares or 0)
        creator_analytics.discord_reactions = int(row.discord_reactions or 0)
        creator_analytics.unique_games = row.unique_games

        # Get top game for this creator
        top_game = (
            db.session.query(
                ClipAnalytics.game_name, func.count(ClipAnalytics.id).label("count")
            )
            .filter(ClipAnalytics.user_id == user_id)
            .filter(ClipAnalytics.creator_name == row.creator_name)
            .filter(ClipAnalytics.game_name.isnot(None))
            .group_by(ClipAnalytics.game_name)
            .order_by(func.count(ClipAnalytics.id).desc())
            .first()
        )

        if top_game:
            creator_analytics.top_game = top_game[0]

        count += 1

    db.session.commit()
    return count


@celery_app.task(name="aggregate_all_analytics")
def aggregate_all_analytics_task():
    """
    Aggregate analytics for all periods (day, week, month, all_time).

    This task should be run daily to keep aggregated data fresh.
    """
    logger.info("aggregate_all_analytics_started")

    results = {}
    for period in ["day", "week", "month", "all_time"]:
        try:
            result = aggregate_analytics_task(user_id=None, period=period)
            results[period] = result
        except Exception as e:
            logger.error(f"aggregate_analytics_failed_for_{period}", error=str(e))
            results[period] = {"success": False, "error": str(e)}

    logger.info("aggregate_all_analytics_completed", results=results)
    return results

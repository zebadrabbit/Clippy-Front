"""
Analytics routes for clip and engagement metrics.

Provides endpoints for:
- Top clip creators/clippers
- Game performance analytics
- Engagement trends over time
- Viral clips and community favorites
- Peak activity times
"""
from datetime import datetime, timedelta

from flask import jsonify, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import desc, func

from app.analytics import analytics_bp
from app.models import (
    Clip,
    ClipAnalytics,
    db,
)


@analytics_bp.route("/")
@login_required
def analytics_dashboard():
    """Render the main analytics dashboard page."""
    return render_template("analytics/dashboard.html")


@analytics_bp.route("/api/overview")
@login_required
def overview_api():
    """
    Get high-level analytics overview for the current user.

    Returns:
        JSON with overall stats: total clips, total views, unique creators,
        unique games, date range, top game, top creator
    """
    user_id = current_user.id

    # Get all-time stats
    total_clips = (
        db.session.query(func.count(ClipAnalytics.id))
        .filter(ClipAnalytics.user_id == user_id)
        .scalar()
        or 0
    )

    total_views = (
        db.session.query(func.sum(ClipAnalytics.view_count))
        .filter(ClipAnalytics.user_id == user_id)
        .scalar()
        or 0
    )

    total_discord_shares = (
        db.session.query(func.sum(ClipAnalytics.discord_shares))
        .filter(ClipAnalytics.user_id == user_id)
        .scalar()
        or 0
    )

    total_discord_reactions = (
        db.session.query(func.sum(ClipAnalytics.discord_reactions))
        .filter(ClipAnalytics.user_id == user_id)
        .scalar()
        or 0
    )

    unique_creators = (
        db.session.query(func.count(func.distinct(ClipAnalytics.creator_name)))
        .filter(ClipAnalytics.user_id == user_id)
        .filter(ClipAnalytics.creator_name.isnot(None))
        .scalar()
        or 0
    )

    unique_games = (
        db.session.query(func.count(func.distinct(ClipAnalytics.game_name)))
        .filter(ClipAnalytics.user_id == user_id)
        .filter(ClipAnalytics.game_name.isnot(None))
        .scalar()
        or 0
    )

    # Get date range
    date_range = (
        db.session.query(
            func.min(ClipAnalytics.clip_created_at),
            func.max(ClipAnalytics.clip_created_at),
        )
        .filter(ClipAnalytics.user_id == user_id)
        .first()
    )

    # Get top game
    top_game_row = (
        db.session.query(
            ClipAnalytics.game_name, func.count(ClipAnalytics.id).label("count")
        )
        .filter(ClipAnalytics.user_id == user_id)
        .filter(ClipAnalytics.game_name.isnot(None))
        .group_by(ClipAnalytics.game_name)
        .order_by(desc("count"))
        .first()
    )

    # Get top creator
    top_creator_row = (
        db.session.query(
            ClipAnalytics.creator_name, func.count(ClipAnalytics.id).label("count")
        )
        .filter(ClipAnalytics.user_id == user_id)
        .filter(ClipAnalytics.creator_name.isnot(None))
        .group_by(ClipAnalytics.creator_name)
        .order_by(desc("count"))
        .first()
    )

    return jsonify(
        {
            "total_clips": total_clips,
            "total_views": int(total_views),
            "total_discord_shares": int(total_discord_shares or 0),
            "total_discord_reactions": int(total_discord_reactions or 0),
            "unique_creators": unique_creators,
            "unique_games": unique_games,
            "date_range": {
                "start": date_range[0].isoformat() if date_range[0] else None,
                "end": date_range[1].isoformat() if date_range[1] else None,
            },
            "top_game": {
                "name": top_game_row[0] if top_game_row else None,
                "clip_count": top_game_row[1] if top_game_row else 0,
            },
            "top_creator": {
                "name": top_creator_row[0] if top_creator_row else None,
                "clip_count": top_creator_row[1] if top_creator_row else 0,
            },
        }
    )


@analytics_bp.route("/api/top-creators")
@login_required
def top_creators_api():
    """
    Get top clip creators/clippers ranked by clip count and engagement.

    Query params:
        period (str): Time period - 'day', 'week', 'month', 'all_time' (default: all_time)
        limit (int): Max results (default: 10, max: 100)

    Returns:
        JSON list of creators with clip counts, views, and engagement metrics
    """
    user_id = current_user.id
    period = request.args.get("period", "all_time")
    limit = min(int(request.args.get("limit", 10)), 100)

    # Build query based on period
    query = (
        db.session.query(
            ClipAnalytics.creator_name,
            ClipAnalytics.creator_id,
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

    # Apply time filter
    if period != "all_time":
        now = datetime.utcnow()
        if period == "day":
            start_date = now - timedelta(days=1)
        elif period == "week":
            start_date = now - timedelta(weeks=1)
        elif period == "month":
            start_date = now - timedelta(days=30)
        else:
            start_date = None

        if start_date:
            query = query.filter(ClipAnalytics.clip_created_at >= start_date)

    # Group and order
    query = (
        query.group_by(ClipAnalytics.creator_name, ClipAnalytics.creator_id)
        .order_by(desc("clip_count"))
        .limit(limit)
    )

    results = query.all()

    creators = []
    for row in results:
        creators.append(
            {
                "creator_name": row.creator_name,
                "creator_id": row.creator_id,
                "clip_count": row.clip_count,
                "total_views": int(row.total_views or 0),
                "avg_views": round(row.avg_views or 0, 1),
                "discord_shares": int(row.discord_shares or 0),
                "discord_reactions": int(row.discord_reactions or 0),
                "unique_games": row.unique_games,
            }
        )

    return jsonify({"period": period, "creators": creators})


@analytics_bp.route("/api/top-games")
@login_required
def top_games_api():
    """
    Get top games ranked by clip count and engagement.

    Query params:
        period (str): Time period - 'day', 'week', 'month', 'all_time' (default: all_time)
        limit (int): Max results (default: 10, max: 100)

    Returns:
        JSON list of games with clip counts, views, and engagement metrics
    """
    user_id = current_user.id
    period = request.args.get("period", "all_time")
    limit = min(int(request.args.get("limit", 10)), 100)

    # Build query
    query = (
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
        )
        .filter(ClipAnalytics.user_id == user_id)
        .filter(ClipAnalytics.game_name.isnot(None))
    )

    # Apply time filter
    if period != "all_time":
        now = datetime.utcnow()
        if period == "day":
            start_date = now - timedelta(days=1)
        elif period == "week":
            start_date = now - timedelta(weeks=1)
        elif period == "month":
            start_date = now - timedelta(days=30)
        else:
            start_date = None

        if start_date:
            query = query.filter(ClipAnalytics.clip_created_at >= start_date)

    # Group and order
    query = (
        query.group_by(ClipAnalytics.game_name, ClipAnalytics.game_id)
        .order_by(desc("clip_count"))
        .limit(limit)
    )

    results = query.all()

    games = []
    for row in results:
        games.append(
            {
                "game_name": row.game_name,
                "game_id": row.game_id,
                "clip_count": row.clip_count,
                "total_views": int(row.total_views or 0),
                "avg_views": round(row.avg_views or 0, 1),
                "discord_shares": int(row.discord_shares or 0),
                "discord_reactions": int(row.discord_reactions or 0),
                "unique_creators": row.unique_creators,
            }
        )

    return jsonify({"period": period, "games": games})


@analytics_bp.route("/api/viral-clips")
@login_required
def viral_clips_api():
    """
    Get viral clips ranked by view count and engagement.

    Query params:
        period (str): Time period - 'day', 'week', 'month', 'all_time' (default: week)
        limit (int): Max results (default: 20, max: 100)
        min_views (int): Minimum view count threshold (default: 100)

    Returns:
        JSON list of clips with metadata and engagement metrics
    """
    user_id = current_user.id
    period = request.args.get("period", "week")
    limit = min(int(request.args.get("limit", 20)), 100)
    min_views = int(request.args.get("min_views", 100))

    # Build query with clip details
    query = (
        db.session.query(ClipAnalytics, Clip)
        .join(Clip, ClipAnalytics.clip_id == Clip.id)
        .filter(ClipAnalytics.user_id == user_id)
        .filter(ClipAnalytics.view_count >= min_views)
    )

    # Apply time filter
    if period != "all_time":
        now = datetime.utcnow()
        if period == "day":
            start_date = now - timedelta(days=1)
        elif period == "week":
            start_date = now - timedelta(weeks=1)
        elif period == "month":
            start_date = now - timedelta(days=30)
        else:
            start_date = None

        if start_date:
            query = query.filter(ClipAnalytics.clip_created_at >= start_date)

    # Order by views
    query = query.order_by(desc(ClipAnalytics.view_count)).limit(limit)

    results = query.all()

    clips = []
    for analytics, clip in results:
        clips.append(
            {
                "clip_id": clip.id,
                "title": clip.title,
                "source_url": clip.source_url,
                "creator_name": analytics.creator_name,
                "game_name": analytics.game_name,
                "view_count": analytics.view_count,
                "discord_shares": analytics.discord_shares or 0,
                "discord_reactions": analytics.discord_reactions or 0,
                "clip_created_at": (
                    analytics.clip_created_at.isoformat()
                    if analytics.clip_created_at
                    else None
                ),
                "duration": clip.duration,
            }
        )

    return jsonify({"period": period, "min_views": min_views, "clips": clips})


@analytics_bp.route("/api/engagement-timeline")
@login_required
def engagement_timeline_api():
    """
    Get engagement timeline showing clip activity over time.

    Query params:
        period (str): Grouping - 'day', 'week', 'month' (default: day)
        days (int): Number of days back to look (default: 30, max: 365)

    Returns:
        JSON with timeline data points (date, clip_count, views, shares, reactions)
    """
    user_id = current_user.id
    period = request.args.get("period", "day")
    days_back = min(int(request.args.get("days", 30)), 365)

    start_date = datetime.utcnow() - timedelta(days=days_back)

    # Get data grouped by date
    if period == "day":
        date_trunc = func.date(ClipAnalytics.clip_created_at)
    elif period == "week":
        # PostgreSQL: date_trunc('week', ...), SQLite: date(..., 'weekday 0')
        date_trunc = func.date(
            ClipAnalytics.clip_created_at, "weekday 0"
        )  # SQLite syntax
    else:  # month
        date_trunc = func.strftime(
            "%Y-%m", ClipAnalytics.clip_created_at
        )  # SQLite syntax

    query = (
        db.session.query(
            date_trunc.label("date"),
            func.count(ClipAnalytics.id).label("clip_count"),
            func.sum(ClipAnalytics.view_count).label("total_views"),
            func.sum(ClipAnalytics.discord_shares).label("discord_shares"),
            func.sum(ClipAnalytics.discord_reactions).label("discord_reactions"),
        )
        .filter(ClipAnalytics.user_id == user_id)
        .filter(ClipAnalytics.clip_created_at >= start_date)
        .group_by("date")
        .order_by("date")
    )

    results = query.all()

    timeline = []
    for row in results:
        timeline.append(
            {
                "date": str(row.date),
                "clip_count": row.clip_count,
                "total_views": int(row.total_views or 0),
                "discord_shares": int(row.discord_shares or 0),
                "discord_reactions": int(row.discord_reactions or 0),
            }
        )

    return jsonify({"period": period, "days_back": days_back, "timeline": timeline})


@analytics_bp.route("/api/peak-times")
@login_required
def peak_times_api():
    """
    Get peak activity times (hour of day, day of week).

    Returns:
        JSON with hourly and daily distribution of clip creation
    """
    user_id = current_user.id

    # Get clips grouped by hour of day
    hourly = (
        db.session.query(
            func.strftime("%H", ClipAnalytics.clip_created_at).label("hour"),
            func.count(ClipAnalytics.id).label("clip_count"),
        )
        .filter(ClipAnalytics.user_id == user_id)
        .filter(ClipAnalytics.clip_created_at.isnot(None))
        .group_by("hour")
        .order_by("hour")
        .all()
    )

    # Get clips grouped by day of week (0=Sunday in SQLite)
    daily = (
        db.session.query(
            func.strftime("%w", ClipAnalytics.clip_created_at).label("day"),
            func.count(ClipAnalytics.id).label("clip_count"),
        )
        .filter(ClipAnalytics.user_id == user_id)
        .filter(ClipAnalytics.clip_created_at.isnot(None))
        .group_by("day")
        .order_by("day")
        .all()
    )

    day_names = [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
    ]

    return jsonify(
        {
            "hourly": [
                {"hour": int(row.hour), "clip_count": row.clip_count} for row in hourly
            ],
            "daily": [
                {
                    "day": int(row.day),
                    "day_name": day_names[int(row.day)],
                    "clip_count": row.clip_count,
                }
                for row in daily
            ],
        }
    )

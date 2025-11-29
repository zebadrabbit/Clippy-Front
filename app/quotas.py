"""
Quota and tier management utilities.

This module centralizes logic for:
- Subscription tiers (storage, render-time, watermark policy, unlimited)
- Usage accounting (storage used, render time used per period)
- Enforcement helpers used by routes and Celery tasks

Design notes
------------
- Storage quota counts all MediaFile rows for the user plus compiled outputs
  recorded in Project.output_file_size. This reflects total disk impact.
- Render-time quota uses the duration of final compiled outputs (seconds) and
  accumulates per calendar month using RenderUsage rows. We choose calendar
  month for simplicity; can be adjusted later to rolling windows.
- Watermark policy: A tier can enforce watermarking (apply_watermark=True),
  allow removal (apply_watermark=False), or bypass entirely via is_unlimited.
  A per-user admin override `user.watermark_disabled` always disables watermark.

All helpers accept an optional SQLAlchemy session. If omitted, db.session is used.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func

from app.models import MediaFile, Project, RenderUsage, Tier, User, db

# Reasonable default tiers (can be customized via Admin UI)
# These values match the production database settings
DEFAULT_TIERS = [
    {
        "name": "Free",
        "description": "Starter tier with watermark and limited storage/render time.",
        "storage_limit_bytes": 1073741824,  # 1 GB
        "render_time_limit_seconds": 1800,  # 30 minutes per month
        "apply_watermark": True,
        "is_unlimited": False,
        "is_active": True,
        "is_default": True,  # Default tier for new users
        "max_teams_owned": 1,
        "max_team_members": 3,
    },
    {
        "name": "Pro",
        "description": "Higher limits, no watermark, automation enabled.",
        "storage_limit_bytes": 53687091200,  # 50 GB
        "render_time_limit_seconds": 21600,  # 6 hours per month
        "apply_watermark": False,
        "is_unlimited": False,
        "is_active": True,
        "is_default": False,
        "max_teams_owned": 5,
        "max_team_members": 15,
    },
    {
        "name": "Unlimited",
        "description": "Admin/testing tier with no limits and no watermark.",
        "storage_limit_bytes": None,
        "render_time_limit_seconds": None,
        "apply_watermark": False,
        "is_unlimited": True,
        "is_active": True,
        "is_default": False,
        "max_teams_owned": None,
        "max_team_members": None,
    },
]


def ensure_default_tiers(session=None) -> None:
    """Ensure default tiers exist at runtime.

    Safe to call repeatedly; creates missing tiers by name.
    Also ensures exactly one tier is marked as default.
    """
    s = session or db.session
    created = 0
    for t in DEFAULT_TIERS:
        row = s.query(Tier).filter_by(name=t["name"]).first()
        if not row:
            row = Tier(**t)
            s.add(row)
            created += 1
    if created:
        try:
            s.commit()
        except Exception:
            s.rollback()

    # Ensure exactly one default tier exists
    ensure_single_default_tier(s)


def ensure_single_default_tier(session=None) -> None:
    """Ensure exactly one tier is marked as default.

    If no default tier exists, mark the first active tier as default.
    If multiple defaults exist, keep only the first one.
    """
    s = session or db.session

    default_tiers = s.query(Tier).filter_by(is_default=True, is_active=True).all()

    if len(default_tiers) == 0:
        # No default tier - mark the first active tier as default
        first_active = s.query(Tier).filter_by(is_active=True).first()
        if first_active:
            first_active.is_default = True
            try:
                s.commit()
            except Exception:
                s.rollback()
    elif len(default_tiers) > 1:
        # Multiple defaults - keep only the first one
        for tier in default_tiers[1:]:
            tier.is_default = False
        try:
            s.commit()
        except Exception:
            s.rollback()


def get_default_tier(session=None) -> Tier | None:
    """Get the tier marked as default for new users.

    Returns the default tier, or falls back to Free tier if no default is set.
    """
    s = session or db.session

    # Try to get the default tier
    default = s.query(Tier).filter_by(is_default=True, is_active=True).first()
    if default:
        return default

    # Fall back to Free tier
    free = s.query(Tier).filter_by(name="Free", is_active=True).first()
    if free:
        return free

    # Last resort: any active tier
    return s.query(Tier).filter_by(is_active=True).first()


def get_effective_tier(user: User, session=None) -> Tier | None:
    """Return the user's assigned tier or a sensible default.

    If no tiers exist in the DB, attempt to create defaults and return the default tier.
    """
    if not user:
        return None
    s = session or db.session
    try:
        if user.tier:
            return user.tier
    except Exception:
        pass

    # No assigned tier; fall back to default tier
    default_tier = get_default_tier(s)
    if default_tier:
        return default_tier

    # Try to seed defaults and fetch again
    try:
        ensure_default_tiers(s)
        return get_default_tier(s)
    except Exception:
        return None


def storage_used_bytes(user_id: int, session=None) -> int:
    """Compute total storage used by a user in bytes.

    Includes all MediaFile sizes and compiled output sizes on Projects.
    """
    s = session or db.session
    media_sum = (
        s.query(func.coalesce(func.sum(MediaFile.file_size), 0))
        .filter(MediaFile.user_id == user_id)
        .scalar()
        or 0
    )
    proj_sum = (
        s.query(func.coalesce(func.sum(Project.output_file_size), 0))
        .filter(Project.user_id == user_id)
        .scalar()
        or 0
    )
    try:
        return int(media_sum) + int(proj_sum)
    except Exception:
        return int(media_sum)


def storage_remaining_bytes(user: User, session=None) -> int | None:
    """Return remaining storage bytes for the user, or None for unlimited."""
    tier = get_effective_tier(user, session=session)
    if not tier or tier.is_unlimited or tier.storage_limit_bytes is None:
        return None
    used = storage_used_bytes(user.id, session=session)
    return max(0, int(tier.storage_limit_bytes) - int(used))


@dataclass
class QuotaCheck:
    ok: bool
    remaining: int | None
    limit: int | None
    reason: str | None = None


def check_storage_quota(
    user: User, additional_bytes: int = 0, session=None
) -> QuotaCheck:
    """Check if the user can add additional_bytes without exceeding storage limit."""
    tier = get_effective_tier(user, session=session)
    if not tier or tier.is_unlimited or tier.storage_limit_bytes is None:
        return QuotaCheck(ok=True, remaining=None, limit=None)
    remaining = storage_remaining_bytes(user, session=session) or 0
    if additional_bytes <= remaining:
        return QuotaCheck(
            ok=True,
            remaining=remaining - int(additional_bytes),
            limit=int(tier.storage_limit_bytes),
        )
    return QuotaCheck(
        ok=False,
        remaining=max(0, int(remaining)),
        limit=int(tier.storage_limit_bytes),
        reason="storage_exceeded",
    )


def month_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return UTC start/end of the current calendar month."""
    n = now or datetime.now(timezone.utc)
    start = datetime(n.year, n.month, 1, tzinfo=timezone.utc)
    if n.month == 12:
        end = datetime(n.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(n.year, n.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def render_used_seconds_this_month(
    user_id: int, now: datetime | None = None, session=None
) -> int:
    """Sum seconds_used for the user within the current month window."""
    s = session or db.session
    start, end = month_window(now)
    total = (
        s.query(func.coalesce(func.sum(RenderUsage.seconds_used), 0))
        .filter(
            RenderUsage.user_id == user_id,
            RenderUsage.created_at >= start,
            RenderUsage.created_at < end,
        )
        .scalar()
        or 0
    )
    try:
        return int(total)
    except Exception:
        return 0


def render_remaining_seconds(
    user: User, now: datetime | None = None, session=None
) -> int | None:
    """Return remaining render-time seconds for current month, or None for unlimited."""
    tier = get_effective_tier(user, session=session)
    if not tier or tier.is_unlimited or tier.render_time_limit_seconds is None:
        return None
    used = render_used_seconds_this_month(user.id, now=now, session=session)
    return max(0, int(tier.render_time_limit_seconds) - int(used))


def check_render_quota(
    user: User, planned_seconds: int, now: datetime | None = None, session=None
) -> QuotaCheck:
    """Check if user can render planned_seconds more this month."""
    tier = get_effective_tier(user, session=session)
    if not tier or tier.is_unlimited or tier.render_time_limit_seconds is None:
        return QuotaCheck(ok=True, remaining=None, limit=None)
    remaining = render_remaining_seconds(user, now=now, session=session) or 0
    if int(planned_seconds) <= int(remaining):
        return QuotaCheck(
            ok=True,
            remaining=int(remaining) - int(planned_seconds),
            limit=int(tier.render_time_limit_seconds),
        )
    return QuotaCheck(
        ok=False,
        remaining=max(0, int(remaining)),
        limit=int(tier.render_time_limit_seconds),
        reason="render_time_exceeded",
    )


def record_render_usage(
    user_id: int, project_id: int | None, seconds_used: int, session=None
) -> None:
    """Append a RenderUsage row after a successful compilation."""
    s = session or db.session
    try:
        s.add(
            RenderUsage(
                user_id=user_id, project_id=project_id, seconds_used=int(seconds_used)
            )
        )
        s.commit()
    except Exception:
        s.rollback()


def should_apply_watermark(user: User, session=None) -> bool:
    """Decide whether the watermark should be applied for this user.

    Order of precedence:
      - Per-user override: watermark_disabled=True => never apply
      - Tier.apply_watermark (True => apply, False => do not apply)
      - Fallback: apply (conservative)
    """
    try:
        if getattr(user, "watermark_disabled", False):
            return False
    except Exception:
        pass
    tier = get_effective_tier(user, session=session)
    if tier:
        return bool(tier.apply_watermark)
    return True


def count_owned_teams(user_id: int, session=None) -> int:
    """Count the number of teams owned by a user."""
    from app.models import Team

    s = session or db.session
    return s.query(func.count(Team.id)).filter(Team.owner_id == user_id).scalar() or 0


def count_team_members(team_id: int, session=None) -> int:
    """Count total members in a team (including owner)."""
    from app.models import TeamMembership

    s = session or db.session
    # Owner + memberships
    membership_count = (
        s.query(func.count(TeamMembership.id))
        .filter(TeamMembership.team_id == team_id)
        .scalar()
        or 0
    )
    return int(membership_count) + 1  # +1 for owner


def check_team_creation_quota(user: User, session=None) -> QuotaCheck:
    """Check if user can create another team."""
    tier = get_effective_tier(user, session=session)
    if not tier or tier.is_unlimited or tier.max_teams_owned is None:
        return QuotaCheck(ok=True, remaining=None, limit=None)

    owned = count_owned_teams(user.id, session=session)
    limit = int(tier.max_teams_owned)

    if owned < limit:
        return QuotaCheck(ok=True, remaining=limit - owned - 1, limit=limit)

    return QuotaCheck(
        ok=False,
        remaining=0,
        limit=limit,
        reason="max_teams_reached",
    )


def check_team_member_quota(team_id: int, owner: User, session=None) -> QuotaCheck:
    """Check if a team can add another member based on owner's tier."""
    tier = get_effective_tier(owner, session=session)
    if not tier or tier.is_unlimited or tier.max_team_members is None:
        return QuotaCheck(ok=True, remaining=None, limit=None)

    current = count_team_members(team_id, session=session)
    limit = int(tier.max_team_members)

    if current < limit:
        return QuotaCheck(ok=True, remaining=limit - current - 1, limit=limit)

    return QuotaCheck(
        ok=False,
        remaining=0,
        limit=limit,
        reason="max_team_members_reached",
    )

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
DEFAULT_TIERS = [
    {
        "name": "Free",
        "description": "Starter tier with watermark and limited storage/render time.",
        "storage_limit_bytes": 1 * 1024 * 1024 * 1024,  # 1 GB
        "render_time_limit_seconds": 30 * 60,  # 30 minutes per month
        "apply_watermark": True,
        "is_unlimited": False,
        "is_active": True,
    },
    {
        "name": "Pro",
        "description": "Higher limits, no watermark.",
        "storage_limit_bytes": 50 * 1024 * 1024 * 1024,  # 50 GB
        "render_time_limit_seconds": 6 * 60 * 60,  # 6 hours per month
        "apply_watermark": False,
        "is_unlimited": False,
        "is_active": True,
    },
    {
        "name": "Unlimited",
        "description": "Admin/testing tier with no limits and no watermark.",
        "storage_limit_bytes": None,
        "render_time_limit_seconds": None,
        "apply_watermark": False,
        "is_unlimited": True,
        "is_active": True,
    },
]


def ensure_default_tiers(session=None) -> None:
    """Ensure default tiers exist at runtime.

    Safe to call repeatedly; creates missing tiers by name.
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


def get_effective_tier(user: User, session=None) -> Tier | None:
    """Return the user's assigned tier or a sensible default.

    If no tiers exist in the DB, attempt to create defaults and return "Free".
    """
    if not user:
        return None
    s = session or db.session
    try:
        if user.tier:
            return user.tier
    except Exception:
        pass
    # No assigned tier; fall back to Free if present
    free = s.query(Tier).filter_by(name="Free").first()
    if free:
        return free
    # Try to seed defaults and fetch again
    try:
        ensure_default_tiers(s)
        return s.query(Tier).filter_by(name="Free").first()
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
      - Unlimited tier => never apply
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
        if tier.is_unlimited:
            return False
        return bool(tier.apply_watermark)
    return True

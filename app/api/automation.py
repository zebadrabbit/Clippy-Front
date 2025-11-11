"""
Automation/task/scheduler-related API endpoints extracted from the legacy shim.

Registers routes on the shared `api_bp` blueprint.
"""
import re

from flask import jsonify, request
from flask_login import current_user, login_required

from app.api import api_bp


@api_bp.route("/automation/tasks", methods=["POST"])
@login_required
def create_compilation_task_api():
    from app.models import CompilationTask, db

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    description = (data.get("description") or "").strip() or None
    params = data.get("params") or {}

    source = (params.get("source") or "twitch").strip().lower()
    if source not in {"twitch"}:
        return jsonify({"error": "source must be 'twitch'"}), 400

    task = CompilationTask(
        user_id=current_user.id, name=name, description=description, params=params
    )
    try:
        db.session.add(task)
        db.session.commit()
        return jsonify({"id": task.id, "status": "created"}), 201
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to create task"}), 500


@api_bp.route("/automation/tasks", methods=["GET"])
@login_required
def list_compilation_tasks_api():
    from app.models import CompilationTask

    items = (
        CompilationTask.query.filter_by(user_id=current_user.id)
        .order_by(CompilationTask.updated_at.desc())
        .all()
    )
    return jsonify(
        {
            "items": [
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                }
                for t in items
            ],
            "count": len(items),
        }
    )


@api_bp.route("/automation/tasks/<int:task_id>/run", methods=["POST"])
@login_required
def run_compilation_task_api(task_id: int):
    from app.models import CompilationTask

    ctask = CompilationTask.query.filter_by(id=task_id, user_id=current_user.id).first()
    if not ctask:
        return jsonify({"error": "Task not found"}), 404
    try:
        from app.tasks.automation import run_compilation_task as _run

        res = _run.apply_async(args=(ctask.id,))
        return jsonify({"status": "started", "task_id": res.id}), 202
    except Exception:
        return jsonify({"error": "Failed to start run"}), 500


@api_bp.route("/automation/tasks/<int:task_id>", methods=["GET"])
@login_required
def get_compilation_task_api(task_id: int):
    from app.models import CompilationTask

    t = CompilationTask.query.filter_by(id=task_id, user_id=current_user.id).first()
    if not t:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "params": t.params or {},
            "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
    )


@api_bp.route("/automation/tasks/<int:task_id>", methods=["PATCH", "PUT"])
@login_required
def update_compilation_task_api(task_id: int):
    from app.models import CompilationTask, db

    t = CompilationTask.query.filter_by(id=task_id, user_id=current_user.id).first()
    if not t:
        return jsonify({"error": "Task not found"}), 404
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    if name is not None:
        name = (str(name) or "").strip()
        if not name:
            return jsonify({"error": "name cannot be blank"}), 400
        t.name = name
    if "description" in data:
        desc = data.get("description")
        t.description = (str(desc) or "").strip() or None
    if "params" in data:
        params = data.get("params") or {}
        try:
            src = (params.get("source") or "twitch").strip().lower()
            if src not in {"twitch"}:
                return (jsonify({"error": "params.source must be 'twitch'"}), 400)
        except Exception:
            pass
        t.params = params
    try:
        db.session.commit()
        return jsonify({"success": True})
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to update task"}), 500


@api_bp.route("/automation/tasks/<int:task_id>", methods=["DELETE"])
@login_required
def delete_compilation_task_api(task_id: int):
    from app.models import CompilationTask, ScheduledTask, db

    t = CompilationTask.query.filter_by(id=task_id, user_id=current_user.id).first()
    if not t:
        return jsonify({"error": "Task not found"}), 404
    try:
        ScheduledTask.query.filter_by(user_id=current_user.id, task_id=t.id).delete()
        db.session.delete(t)
        db.session.commit()
        return jsonify({"success": True})
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to delete task"}), 500


@api_bp.route("/automation/tasks/<int:task_id>/schedules", methods=["POST"])
@login_required
def create_schedule_api(task_id: int):
    from app.models import CompilationTask, ScheduledTask, ScheduleType, db

    ctask = CompilationTask.query.filter_by(id=task_id, user_id=current_user.id).first()
    if not ctask:
        return jsonify({"error": "Task not found"}), 404

    try:
        if not (
            current_user.tier
            and getattr(current_user.tier, "can_schedule_tasks", False)
        ):
            return jsonify({"error": "Scheduling not available for your tier"}), 403
        active_count = ScheduledTask.query.filter_by(
            user_id=current_user.id, enabled=True
        ).count()
        max_allowed = int(getattr(current_user.tier, "max_schedules_per_user", 1) or 1)
        if active_count >= max_allowed:
            return (
                jsonify({"error": "Schedule limit reached", "limit": max_allowed}),
                403,
            )
    except Exception:
        return jsonify({"error": "Scheduling not available"}), 403

    data = request.get_json(silent=True) or {}
    stype = (data.get("type") or "").strip().lower()
    if stype not in {"daily", "weekly", "monthly"}:
        return jsonify({"error": "type must be one of: daily,weekly,monthly"}), 400

    run_at = None
    daily_time = None
    weekly_day = None
    month_day = None
    if stype == "daily":
        daily_time = (data.get("time") or "").strip()
        if not daily_time:
            return jsonify({"error": "time is required"}), 400
        if not re.match(r"^\d{2}:\d{2}$", daily_time):
            return jsonify({"error": "time must be HH:MM"}), 400
    elif stype == "weekly":
        daily_time = (data.get("time") or "").strip()
        if not daily_time:
            return jsonify({"error": "time is required"}), 400
        if not re.match(r"^\d{2}:\d{2}$", daily_time):
            return jsonify({"error": "time must be HH:MM"}), 400
        try:
            weekly_day = int(data.get("weekday"))
        except Exception:
            weekly_day = 0
        if weekly_day < 0 or weekly_day > 6:
            return jsonify({"error": "weekday must be 0..6 (Mon..Sun)"}), 400
    elif stype == "monthly":
        daily_time = (data.get("time") or "").strip()
        if not daily_time:
            return jsonify({"error": "time is required"}), 400
        if not re.match(r"^\d{2}:\d{2}$", daily_time):
            return jsonify({"error": "time must be HH:MM"}), 400
        try:
            month_day = int(data.get("month_day"))
        except Exception:
            month_day = 1
        if month_day < 1 or month_day > 31:
            return jsonify({"error": "month_day must be 1..31"}), 400

    tz_name = (data.get("timezone") or current_user.timezone or "UTC").strip() or "UTC"
    try:
        from zoneinfo import ZoneInfo

        _ = ZoneInfo(tz_name)
    except Exception:
        tz_name = "UTC"

    sched = ScheduledTask(
        user_id=current_user.id,
        task_id=ctask.id,
        schedule_type=ScheduleType(stype),
        run_at=run_at,
        daily_time=daily_time,
        weekly_day=weekly_day,
        monthly_day=month_day,
        timezone=tz_name,
        enabled=True,
    )
    try:
        try:
            from datetime import datetime as _dt

            from app.tasks.automation import _compute_next_run

            now_utc = _dt.utcnow().replace(tzinfo=None)
            sched.next_run_at = _compute_next_run(sched, now_utc)
        except Exception:
            sched.next_run_at = None

        db.session.add(sched)
        db.session.commit()
        return jsonify({"id": sched.id, "status": "created"}), 201
    except Exception as e:
        db.session.rollback()
        return (
            jsonify({"error": "Failed to create schedule", "error_detail": str(e)}),
            500,
        )


@api_bp.route("/automation/tasks/<int:task_id>/schedules", methods=["GET"])
@login_required
def list_schedules_api(task_id: int):
    from app.models import ScheduledTask

    rows = (
        ScheduledTask.query.filter_by(user_id=current_user.id, task_id=task_id)
        .order_by(ScheduledTask.created_at.desc())
        .all()
    )
    try:
        from datetime import datetime as _dt

        from app.tasks.automation import _compute_next_run

        now_utc = _dt.utcnow().replace(tzinfo=None)
    except Exception:
        now_utc = None
    return jsonify(
        {
            "items": [
                {
                    "id": s.id,
                    "enabled": s.enabled,
                    "type": s.schedule_type.value
                    if hasattr(s.schedule_type, "value")
                    else str(s.schedule_type),
                    "run_at": s.run_at.isoformat() if s.run_at else None,
                    "time": s.daily_time,
                    "weekday": s.weekly_day,
                    "timezone": getattr(s, "timezone", None) or "UTC",
                    "month_day": s.monthly_day,
                    "next_run_at": (
                        s.next_run_at.isoformat()
                        if s.next_run_at
                        else (
                            _compute_next_run(s, now_utc).isoformat()
                            if (now_utc is not None and _compute_next_run(s, now_utc))
                            else None
                        )
                    ),
                    "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
                }
                for s in rows
            ],
            "count": len(rows),
        }
    )


@api_bp.route("/automation/schedules/<int:schedule_id>", methods=["PATCH"])
@login_required
def update_schedule_api(schedule_id: int):
    from datetime import datetime as _dt

    from app.models import ScheduledTask, ScheduleType
    from app.tasks.automation import _compute_next_run

    s = ScheduledTask.query.filter_by(id=schedule_id, user_id=current_user.id).first()
    if not s:
        return jsonify({"error": "Schedule not found"}), 404
    data = request.get_json(silent=True) or {}
    if "enabled" in data:
        s.enabled = bool(data.get("enabled"))
    if "type" in data:
        stype = (str(data.get("type")) or "").strip().lower()
        if stype not in {"daily", "weekly", "monthly"}:
            return jsonify({"error": "type must be daily|weekly|monthly"}), 400
        s.schedule_type = ScheduleType(stype)
        s.run_at = None
        s.daily_time = None
        s.weekly_day = None
        s.monthly_day = None
    if s.schedule_type == ScheduleType.ONCE:
        forbidden_keys = {k for k in data.keys() if k not in {"enabled", "type"}}
        if forbidden_keys:
            return (
                jsonify(
                    {
                        "error": "Legacy one-time schedules are read-only. Change type to daily/weekly/monthly to edit.",
                        "forbidden": sorted(forbidden_keys),
                    }
                ),
                400,
            )
    if s.schedule_type in (
        ScheduleType.DAILY,
        ScheduleType.WEEKLY,
        ScheduleType.MONTHLY,
    ):
        if "time" in data:
            s.daily_time = (str(data.get("time")) or "00:00").strip()
        if s.schedule_type == ScheduleType.WEEKLY and "weekday" in data:
            try:
                s.weekly_day = int(data.get("weekday"))
            except Exception:
                s.weekly_day = 0
        if s.schedule_type == ScheduleType.MONTHLY and "month_day" in data:
            try:
                s.monthly_day = int(data.get("month_day"))
            except Exception:
                s.monthly_day = 1
    if "timezone" in data:
        tz = (str(data.get("timezone")) or "UTC").strip() or "UTC"
        s.timezone = tz

    try:
        now_utc = _dt.utcnow().replace(tzinfo=None)
        s.next_run_at = _compute_next_run(s, now_utc)
    except Exception:
        pass
    try:
        from app.models import db

        db.session.commit()
        return jsonify(
            {
                "success": True,
                "enabled": s.enabled,
                "type": s.schedule_type.value,
                "run_at": s.run_at.isoformat() if s.run_at else None,
                "time": s.daily_time,
                "weekday": s.weekly_day,
                "timezone": s.timezone,
                "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
            }
        )
    except Exception:
        from app.models import db

        db.session.rollback()
        return jsonify({"error": "Failed to update schedule"}), 500


@api_bp.route("/automation/schedules/<int:schedule_id>", methods=["DELETE"])
@login_required
def delete_schedule_api(schedule_id: int):
    from app.models import ScheduledTask, db

    s = ScheduledTask.query.filter_by(id=schedule_id, user_id=current_user.id).first()
    if not s:
        return jsonify({"error": "Schedule not found"}), 404
    try:
        db.session.delete(s)
        db.session.commit()
        return jsonify({"success": True})
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to delete schedule"}), 500


@api_bp.route("/automation/tasks/<int:task_id>/clone", methods=["POST"])
@login_required
def clone_compilation_task_api(task_id: int):
    from app.models import CompilationTask, ScheduledTask, db

    src = CompilationTask.query.filter_by(id=task_id, user_id=current_user.id).first()
    if not src:
        return jsonify({"error": "Task not found"}), 404
    data = request.get_json(silent=True) or {}
    copy_schedules = bool(data.get("copy_schedules") or False)

    base = src.name or "Task"
    new_name = f"Copy of {base}"
    try:
        existing_names = {
            t.name
            for t in CompilationTask.query.filter_by(user_id=current_user.id).all()
        }
        if new_name in existing_names:
            idx = 2
            while f"{new_name} ({idx})" in existing_names and idx < 1000:
                idx += 1
            new_name = f"{new_name} ({idx})"
    except Exception:
        pass

    try:
        clone = CompilationTask(
            user_id=current_user.id,
            name=new_name,
            description=src.description,
            params=dict(src.params or {}),
        )
        db.session.add(clone)
        db.session.flush()

        if copy_schedules:
            rows = (
                ScheduledTask.query.filter_by(user_id=current_user.id, task_id=src.id)
                .order_by(ScheduledTask.created_at.asc())
                .all()
            )
            for s in rows:
                dup = ScheduledTask(
                    user_id=current_user.id,
                    task_id=clone.id,
                    schedule_type=s.schedule_type,
                    run_at=s.run_at,
                    daily_time=s.daily_time,
                    weekly_day=s.weekly_day,
                    timezone=s.timezone,
                    enabled=False,
                )
                db.session.add(dup)

        db.session.commit()
        return jsonify({"id": clone.id, "status": "cloned"}), 201
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to clone task"}), 500


@api_bp.route("/automation/scheduler/tick", methods=["POST"])
@login_required
def trigger_scheduler_tick_api():
    if not current_user.is_admin():
        return jsonify({"error": "Forbidden"}), 403
    try:
        from app.tasks.automation import scheduled_tasks_tick as _tick

        res = _tick.apply_async()
        return jsonify({"status": "started", "task_id": res.id}), 202
    except Exception:
        return jsonify({"error": "Failed to trigger tick"}), 500

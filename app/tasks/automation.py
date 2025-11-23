"""
Automation tasks: run parameterized compilation tasks and scheduling tick.

This module provides Celery tasks to execute a saved CompilationTask and a periodic
"tick" that enqueues due scheduled tasks. It reuses existing video_processing
helpers and APIs where practical, keeping orchestration within the worker.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import not_, or_
from sqlalchemy.orm import scoped_session, sessionmaker

from app.models import (
    Clip,
    CompilationTask,
    MediaFile,
    MediaType,
    Project,
    ScheduledTask,
    ScheduleType,
    User,
    db,
)
from app.tasks.celery_app import celery_app


def _get_db_session():
    from app import create_app

    app = create_app()
    with app.app_context():
        Session = scoped_session(sessionmaker(bind=db.engine))
        return Session(), app


def _normalize_url(u: str) -> str:
    try:
        s = (u or "").strip()
        if not s:
            return ""
        base = s.split("?")[0].split("#")[0]
        if base.endswith("/"):
            base = base[:-1]
        return base
    except Exception:
        return (u or "").strip()


def _extract_key(u: str) -> str:
    try:
        s = _normalize_url(u)
        if not s:
            return ""
        low = s.lower()
        # Twitch clip URL pattern: /clip/<slug>
        if "twitch.tv" in low and "/clip/" in low:
            try:
                slug = low.split("/clip/", 1)[1].split("/")[0]
                return slug
            except Exception:
                pass
        return s
    except Exception:
        return _normalize_url(u)


def _resolve_queue(app=None) -> str:
    """Pick an appropriate queue based on active queues and config.

    For render/compile tasks: gpu or cpu only (never celery).
    Fallback order: gpu -> cpu, defaulting to gpu if USE_GPU_QUEUE is set.
    """
    # Default to gpu or cpu based on config - NEVER use 'celery' for rendering
    if app:
        queue_name = "gpu" if bool(app.config.get("USE_GPU_QUEUE")) else "cpu"
        use_gpu = bool(app.config.get("USE_GPU_QUEUE"))
    else:
        # Fallback when no app context available
        queue_name = "gpu"
        use_gpu = True

    try:
        i = celery_app.control.inspect(timeout=1.0)
        active_queues = set()
        if i:
            aq = i.active_queues() or {}
            for _worker, queues in aq.items():
                for q in queues or []:
                    qname = q.get("name") if isinstance(q, dict) else None
                    if qname:
                        active_queues.add(qname)

        # Prefer gpu if configured and available, otherwise cpu
        if use_gpu:
            if "gpu" in active_queues:
                return "gpu"
            if "cpu" in active_queues:
                return "cpu"  # Fallback to CPU if GPU not available
            # else return default "gpu" - task will wait for worker
        else:
            # CPU mode
            if "cpu" in active_queues:
                return "cpu"
            if "gpu" in active_queues:
                return "gpu"  # GPU can do CPU work
            # else return default "cpu" - task will wait for worker
    except Exception:
        pass  # Use configured default on error
    return queue_name


def _fetch_twitch_clip_urls(
    session,
    user: User,
    limit: int = 10,
    started_at: str | None = None,
    ended_at: str | None = None,
) -> list[str]:
    """Fetch recent Twitch clip URLs for the user's connected username.

    Returns up to limit items. Uses existing Twitch integration.
    """
    if not user or not user.twitch_username:
        return []
    try:
        from app.integrations.twitch import get_clips as twitch_get_clips
        from app.integrations.twitch import get_user_id as twitch_get_user_id

        broadcaster_id = twitch_get_user_id(user.twitch_username)
        if not broadcaster_id:
            return []
        first = max(1, min(100, int(limit or 10)))
        result = twitch_get_clips(
            broadcaster_id=broadcaster_id,
            started_at=started_at,
            ended_at=ended_at,
            first=first,
        )
        items = result.get("items") or []
        urls: list[str] = []
        # Prefer newest first if created_at present
        try:
            items = sorted(
                items,
                key=lambda x: x.get("created_at") or "",
                reverse=True,
            )
        except Exception:
            pass
        for it in items:
            url = it.get("url") or ""
            if url:
                urls.append(url)
        return urls[:first]
    except Exception:
        return []


@celery_app.task(bind=True)
def run_compilation_task(self, task_id: int) -> dict[str, Any]:
    """Execute a saved CompilationTask: create a project, gather clips, download, and enqueue compile.

            Parameters expected in CompilationTask.params:
        - source: "twitch"
    - clip_limit: int (default 10)
    - intro_id: Optional[int]
    - outro_id: Optional[int]
    - transition_ids: Optional[List[int]]
    - randomize_transitions: bool
        - output: { output_resolution, output_format, max_clip_duration, audio_norm_db }
                    - fallback_to_library: Optional[bool] (default False). When True and no URLs
                        are available from the chosen source, pick the user's most recent library clips.
                        Optional filters apply only when fallback is enabled:
                            - min_duration_seconds: Optional[int]
                            - max_duration_seconds: Optional[int]
                            - include_tags: Optional[List[str] | str CSV]
                            - exclude_tags: Optional[List[str] | str CSV]
    """
    session, _app = _get_db_session()
    try:
        ctask = session.get(CompilationTask, int(task_id))
        if not ctask:
            raise ValueError(f"CompilationTask {task_id} not found")
        user = session.get(User, int(ctask.user_id))
        if not user:
            raise ValueError("Task owner not found")

        p = dict(ctask.params or {})
        # Default to twitch to align with documented params and UI behavior
        source = (p.get("source") or "twitch").strip().lower()
        clip_limit = int(p.get("clip_limit") or 10)
        fallback_to_library = bool(p.get("fallback_to_library") or False)
        clip_urls: list[str] = []
        if source == "twitch":
            started_at = p.get("started_at")
            ended_at = p.get("ended_at")
            clip_urls = _fetch_twitch_clip_urls(
                session,
                user,
                limit=clip_limit,
                started_at=started_at,
                ended_at=ended_at,
            )
        elif source and source != "twitch":
            # Manual/unknown sources are disabled for security
            return {"status": "skipped", "reason": "unsupported_source"}
        else:
            clip_urls = []

        # If no URLs from source, optionally fall back to most recent library clips
        library_media: list[MediaFile] = []
        if not clip_urls and fallback_to_library:
            try:
                # Parse optional filters
                def _as_list(v):
                    if v is None:
                        return []
                    if isinstance(v, list):
                        return [str(x).strip() for x in v if str(x).strip()]
                    return [s.strip() for s in str(v).split(",") if s.strip()]

                min_dur = p.get("min_duration_seconds")
                try:
                    min_dur = int(min_dur) if str(min_dur).strip() else None
                except Exception:
                    min_dur = None
                max_dur = p.get("max_duration_seconds")
                try:
                    max_dur = int(max_dur) if str(max_dur).strip() else None
                except Exception:
                    max_dur = None
                include_tags = _as_list(p.get("include_tags"))
                exclude_tags = _as_list(p.get("exclude_tags"))

                qlm = session.query(MediaFile).filter(
                    MediaFile.user_id == user.id,
                    MediaFile.media_type == MediaType.CLIP,
                )
                if min_dur is not None:
                    qlm = qlm.filter(MediaFile.duration.isnot(None))
                    qlm = qlm.filter(MediaFile.duration >= float(min_dur))
                if max_dur is not None:
                    qlm = qlm.filter(MediaFile.duration.isnot(None))
                    qlm = qlm.filter(MediaFile.duration <= float(max_dur))
                # Tag filters are substring matches on comma-separated tags; case-insensitive
                if include_tags:
                    ors = [MediaFile.tags.ilike(f"%{t}%") for t in include_tags]
                    qlm = qlm.filter(or_(*ors))
                if exclude_tags:
                    ors = [MediaFile.tags.ilike(f"%{t}%") for t in exclude_tags]
                    qlm = qlm.filter(not_(or_(*ors)))

                library_media = (
                    qlm.order_by(MediaFile.uploaded_at.desc(), MediaFile.id.desc())
                    .limit(clip_limit)
                    .all()
                )
            except Exception:
                library_media = []
            # Secondary fallback: reuse most recent clips that appeared in any of the user's projects
            if not library_media:
                try:
                    qclips = (
                        session.query(MediaFile)
                        .join(Clip, Clip.media_file_id == MediaFile.id)
                        .join(Project, Project.id == Clip.project_id)
                        .filter(
                            Project.user_id == user.id,
                            MediaFile.media_type == MediaType.CLIP,
                            Clip.media_file_id.isnot(None),
                        )
                        .order_by(Clip.created_at.desc())
                    )
                    # Apply same filters to the joined set
                    if min_dur is not None:
                        qclips = qclips.filter(MediaFile.duration.isnot(None))
                        qclips = qclips.filter(MediaFile.duration >= float(min_dur))
                    if max_dur is not None:
                        qclips = qclips.filter(MediaFile.duration.isnot(None))
                        qclips = qclips.filter(MediaFile.duration <= float(max_dur))
                    if include_tags:
                        ors = [MediaFile.tags.ilike(f"%{t}%") for t in include_tags]
                        qclips = qclips.filter(or_(*ors))
                    if exclude_tags:
                        ors = [MediaFile.tags.ilike(f"%{t}%") for t in exclude_tags]
                        qclips = qclips.filter(not_(or_(*ors)))
                    # Deduplicate MediaFile ids while preserving order
                    seen_mf = set()
                    results: list[MediaFile] = []
                    for mf in qclips.limit(max(clip_limit * 3, clip_limit)).all():
                        if mf.id in seen_mf:
                            continue
                        seen_mf.add(mf.id)
                        results.append(mf)
                        if len(results) >= clip_limit:
                            break
                    library_media = results
                except Exception:
                    library_media = []
            if not library_media:
                # Graceful no-op when fallback yields nothing
                return {"status": "skipped", "reason": "no_clips_in_library"}
        elif not clip_urls:
            # No URLs and fallback disabled: respect the chosen source strictly
            return {"status": "skipped", "reason": "no_clips_from_source"}

        # Prepare project
        now_tag = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        proj_name = f"{ctask.name} – {now_tag}"
        output_cfg = p.get("output") or {}
        project = Project(
            name=proj_name,
            description=(ctask.description or None),
            user_id=user.id,
            max_clip_duration=int(output_cfg.get("max_clip_duration") or 30),
            output_resolution=output_cfg.get("output_resolution")
            or _app.config.get("DEFAULT_OUTPUT_RESOLUTION", "1080p"),
            output_format=output_cfg.get("output_format")
            or _app.config.get("DEFAULT_OUTPUT_FORMAT", "mp4"),
            audio_norm_db=(
                output_cfg.get("audio_norm_db")
                if output_cfg.get("audio_norm_db") not in (None, "")
                else None
            ),
            public_id=Project.generate_public_id(),
        )
        session.add(project)
        session.commit()

        # Create clips and download (reuse when possible); call the existing download task asynchronously
        from app.tasks.download_clip_v2 import (
            download_clip_task_v2 as download_clip_task,
        )

        items: list[dict] = []
        seen = set()
        order_base = 0
        download_task_ids = []

        if clip_urls:
            for idx, raw_url in enumerate(clip_urls[:clip_limit]):
                url_s = (raw_url or "").strip()
                if not url_s:
                    continue
                norm = _normalize_url(url_s)
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                # Create new clip and queue download (no reuse)
                clip = Clip(
                    title=f"Clip {order_base + idx + 1}",
                    description=None,
                    source_platform=("twitch" if "twitch" in norm else "external"),
                    source_url=url_s,
                    project_id=project.id,
                    order_index=order_base + idx,
                )
                session.add(clip)
                session.flush()
                # Commit before running the download task to ensure the Clip row is persisted
                try:
                    session.commit()
                except Exception:
                    session.rollback()
                    continue
                # Queue download task asynchronously
                res = download_clip_task.apply_async(
                    args=(clip.id, url_s), queue="celery"
                )
                download_task_ids.append(res.id)
                items.append({"clip_id": clip.id, "task_id": res.id, "url": url_s})

            # Poll for download completion (max 5 minutes)
            if download_task_ids:
                import time

                max_wait = 300  # 5 minutes
                poll_interval = 2  # 2 seconds
                elapsed = 0

                while elapsed < max_wait:
                    all_done = True
                    for task_id in download_task_ids:
                        result = celery_app.AsyncResult(task_id)
                        if not result.ready():
                            all_done = False
                            break
                        if result.failed():
                            # Download failed, but continue with others
                            pass

                    if all_done:
                        break

                    time.sleep(poll_interval)
                    elapsed += poll_interval

                # Refresh project and clips from DB to get updated media_file_id values
                session.expire_all()
                project = session.query(Project).get(project.id)
        else:
            # Use most recent library media files as clips (no download)
            for idx, mf in enumerate(library_media[:clip_limit]):
                clip = Clip(
                    title=f"Clip {order_base + idx + 1}",
                    description=mf.description or None,
                    source_platform="library",
                    source_url=None,
                    project_id=project.id,
                    order_index=order_base + idx,
                    media_file_id=mf.id,
                    is_downloaded=True,
                    duration=mf.duration,
                )
                session.add(clip)
                session.flush()
                items.append(
                    {
                        "clip_id": clip.id,
                        "task_id": None,
                        "library_media_id": mf.id,
                        "filename": mf.filename,
                    }
                )
        session.commit()

        # Enqueue compile
        from app.tasks.compile_video_v2 import (
            compile_video_task_v2 as compile_video_task,
        )

        intro_id = p.get("intro_id")
        outro_id = p.get("outro_id")
        transition_ids = p.get("transition_ids") or []
        randomize_transitions = bool(p.get("randomize_transitions") or False)

        qname = _resolve_queue(_app)
        task = compile_video_task.apply_async(
            args=(project.id,),
            kwargs={
                "intro_id": intro_id,
                "outro_id": outro_id,
                "transition_ids": transition_ids,
                "randomize_transitions": randomize_transitions,
            },
            queue=qname,
        )

        # Update last_run and return
        ctask.last_run_at = datetime.utcnow()
        session.add(ctask)
        session.commit()

        return {
            "status": "started",
            "project_id": project.id,
            "compile_task_id": task.id,
            "clips": items,
        }
    except Exception as e:
        session.rollback()
        # Gracefully treat expected "no clips" errors as a skip instead of failure
        try:
            msg = str(e).lower()
        except Exception:
            msg = ""
        if any(
            s in msg
            for s in [
                "no clips available from the selected source",
                "no clips found for compilation",
                "no clips could be processed",
            ]
        ):
            return {"status": "skipped", "reason": "no_clips", "error": str(e)}
        raise
    finally:
        session.close()


def _compute_next_run(st: ScheduledTask, now_utc: datetime) -> datetime | None:
    """Compute next_run_at for a scheduled task given current UTC time.

    Interprets st.daily_time in st.timezone (IANA name) when provided; converts to UTC.
    """
    try:
        if not st.enabled:
            return None
        if st.schedule_type == ScheduleType.ONCE:
            # Only run once; don't reschedule if in the past
            return st.run_at if (st.run_at and st.run_at > now_utc) else None
        # Resolve timezone
        tz_name = getattr(st, "timezone", None) or "UTC"
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
        # Parse time-of-day
        hhmm = (st.daily_time or "00:00").strip()
        hh, mm = 0, 0
        try:
            parts = hhmm.split(":")
            hh = int(parts[0])
            mm = int(parts[1]) if len(parts) > 1 else 0
        except Exception:
            hh, mm = 0, 0
        # Convert now to local tz
        aware_utc = now_utc.replace(tzinfo=timezone.utc)
        now_local = aware_utc.astimezone(tz)
        # Build candidate in local time
        candidate_local = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if st.schedule_type == ScheduleType.DAILY:
            if candidate_local <= now_local:
                candidate_local = candidate_local + timedelta(days=1)
            return candidate_local.astimezone(timezone.utc).replace(tzinfo=None)
        if st.schedule_type == ScheduleType.WEEKLY:
            # 0=Mon .. 6=Sun
            wd = int(st.weekly_day if st.weekly_day is not None else 0)
            days_ahead = (wd - now_local.weekday()) % 7
            candidate_local = candidate_local + timedelta(days=days_ahead)
            if candidate_local <= now_local:
                candidate_local = candidate_local + timedelta(days=7)
            return candidate_local.astimezone(timezone.utc).replace(tzinfo=None)
        if st.schedule_type == ScheduleType.MONTHLY:
            # Day-of-month scheduling; clamp to month's last day if needed
            try:
                import calendar

                md = int(st.monthly_day if st.monthly_day else 1)
                md = max(1, min(31, md))
                year, month = now_local.year, now_local.month
                last_day = calendar.monthrange(year, month)[1]
                use_day = min(md, last_day)
                # If use_day differs from today, rebuild date; otherwise use today's date
                candidate_local = candidate_local.replace(day=use_day)
                # If candidate already passed today, advance to next month
                if candidate_local <= now_local:
                    # increment month
                    if month == 12:
                        year += 1
                        month = 1
                    else:
                        month += 1
                    last_day = calendar.monthrange(year, month)[1]
                    use_day = min(md, last_day)
                    candidate_local = candidate_local.replace(
                        year=year, month=month, day=use_day
                    )
                return candidate_local.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                return None
    except Exception:
        return None
    return None


@celery_app.task(bind=True)
def scheduled_tasks_tick(self) -> dict:
    """Scan for due ScheduledTask rows and enqueue their CompilationTask runs.

    This task is intended to be triggered periodically (e.g., via Celery Beat every minute).
    """
    session, _app = _get_db_session()
    now = datetime.utcnow().replace(tzinfo=None)
    triggered = 0
    examined = 0
    try:
        q = (
            session.query(ScheduledTask)
            .filter(ScheduledTask.enabled.is_(True))
            .order_by(ScheduledTask.id.asc())
        )
        for st in q.all():
            examined += 1
            # Initialize next_run if missing
            if not st.next_run_at:
                st.next_run_at = _compute_next_run(st, now)
                session.add(st)
                session.commit()
            # Due?
            if st.next_run_at and st.next_run_at <= now:
                # Enqueue run
                try:
                    run_compilation_task.apply_async(
                        args=(int(st.task_id),), queue="celery"
                    )
                    triggered += 1
                    st.last_run_at = now
                    # Compute next
                    nxt = _compute_next_run(st, now + timedelta(seconds=1))
                    st.next_run_at = nxt
                    # Disable if one-time
                    if st.schedule_type == ScheduleType.ONCE:
                        st.enabled = False
                    session.add(st)
                    session.commit()
                except Exception:
                    session.rollback()
                    continue
        return {"status": "ok", "triggered": triggered, "examined": examined}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

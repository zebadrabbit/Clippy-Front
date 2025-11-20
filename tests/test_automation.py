"""Tests for automation task scheduling and compilation tasks."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app.models import CompilationTask, ScheduledTask, ScheduleType
from app.tasks.automation import (
    _compute_next_run,
    _extract_key,
    _normalize_url,
    _resolve_queue,
    run_compilation_task,
    scheduled_tasks_tick,
)


class TestURLNormalization:
    """Test URL normalization and key extraction."""

    def test_normalize_url_strips_query_params(self):
        """Should remove query parameters from URL."""
        url = "https://example.com/video?param=value"
        result = _normalize_url(url)
        assert result == "https://example.com/video"

    def test_normalize_url_strips_hash(self):
        """Should remove hash fragment from URL."""
        url = "https://example.com/video#section"
        result = _normalize_url(url)
        assert result == "https://example.com/video"

    def test_normalize_url_removes_trailing_slash(self):
        """Should remove trailing slash."""
        url = "https://example.com/video/"
        result = _normalize_url(url)
        assert result == "https://example.com/video"

    def test_normalize_url_handles_empty_string(self):
        """Should return empty string for empty input."""
        assert _normalize_url("") == ""
        assert _normalize_url("   ") == ""
        assert _normalize_url(None) == ""

    def test_extract_key_returns_twitch_slug(self):
        """Should extract Twitch clip slug from URL."""
        url = "https://www.twitch.tv/clip/FunnySlug123"
        result = _extract_key(url)
        assert result == "funnyslug123"

    def test_extract_key_returns_normalized_url_for_non_twitch(self):
        """Should return normalized URL for non-Twitch URLs."""
        url = "https://youtube.com/watch?v=abc123"
        result = _extract_key(url)
        assert result == "https://youtube.com/watch"


class TestQueueResolution:
    """Test queue selection logic."""

    @patch("app.tasks.automation.celery_app.control.inspect")
    def test_resolve_queue_returns_gpu_when_configured_and_available(
        self, mock_inspect, app
    ):
        """Should return 'gpu' when USE_GPU_QUEUE is True and gpu queue is active."""
        with app.app_context():
            app.config["USE_GPU_QUEUE"] = True
            mock_inspector = MagicMock()
            mock_inspect.return_value = mock_inspector
            mock_inspector.active_queues.return_value = {
                "worker1": [{"name": "gpu"}, {"name": "cpu"}]
            }

            result = _resolve_queue()
            assert result == "gpu"

    @patch("app.tasks.automation.celery_app.control.inspect")
    def test_resolve_queue_falls_back_to_cpu_when_gpu_unavailable(
        self, mock_inspect, app
    ):
        """Should fall back to 'cpu' when gpu queue is not active."""
        with app.app_context():
            app.config["USE_GPU_QUEUE"] = True
            mock_inspector = MagicMock()
            mock_inspect.return_value = mock_inspector
            mock_inspector.active_queues.return_value = {"worker1": [{"name": "cpu"}]}

            result = _resolve_queue()
            assert result == "cpu"

    @patch("app.tasks.automation.celery_app.control.inspect")
    def test_resolve_queue_returns_cpu_when_not_configured_for_gpu(
        self, mock_inspect, app
    ):
        """Should return 'cpu' when USE_GPU_QUEUE is False."""
        with app.app_context():
            app.config["USE_GPU_QUEUE"] = False
            mock_inspector = MagicMock()
            mock_inspect.return_value = mock_inspector
            mock_inspector.active_queues.return_value = {
                "worker1": [{"name": "cpu"}, {"name": "gpu"}]
            }

            result = _resolve_queue()
            assert result == "cpu"

    @patch("app.tasks.automation.celery_app.control.inspect")
    def test_resolve_queue_defaults_to_gpu_on_inspect_error(self, mock_inspect, app):
        """Should default to 'gpu' when inspection fails and USE_GPU_QUEUE is True."""
        with app.app_context():
            app.config["USE_GPU_QUEUE"] = True
            mock_inspect.side_effect = Exception("Inspect failed")

            result = _resolve_queue()
            assert result == "gpu"

    @patch("app.tasks.automation.celery_app.control.inspect")
    def test_resolve_queue_never_returns_celery_queue(self, mock_inspect, app):
        """Should never return 'celery' queue for render tasks."""
        with app.app_context():
            app.config["USE_GPU_QUEUE"] = False
            mock_inspector = MagicMock()
            mock_inspect.return_value = mock_inspector
            mock_inspector.active_queues.return_value = {
                "worker1": [{"name": "celery"}]
            }

            result = _resolve_queue()
            # Should still return configured default (cpu), not 'celery'
            assert result in ("gpu", "cpu")


class TestComputeNextRun:
    """Test scheduled task next-run calculation."""

    def test_compute_next_run_returns_none_when_disabled(self):
        """Should return None when task is disabled."""
        st = ScheduledTask(
            name="Test",
            task_id=1,
            user_id=1,
            enabled=False,
            schedule_type=ScheduleType.DAILY,
            daily_time="09:00",
        )
        now = datetime.utcnow()
        result = _compute_next_run(st, now)
        assert result is None

    def test_compute_next_run_once_returns_run_at_if_future(self):
        """Should return run_at for ONCE schedule if it's in the future."""
        future = datetime.utcnow() + timedelta(days=1)
        st = ScheduledTask(
            name="Test",
            task_id=1,
            user_id=1,
            enabled=True,
            schedule_type=ScheduleType.ONCE,
            run_at=future,
        )
        now = datetime.utcnow()
        result = _compute_next_run(st, now)
        assert result == future

    def test_compute_next_run_once_returns_none_if_past(self):
        """Should return None for ONCE schedule if run_at is in the past."""
        past = datetime.utcnow() - timedelta(days=1)
        st = ScheduledTask(
            name="Test",
            task_id=1,
            user_id=1,
            enabled=True,
            schedule_type=ScheduleType.ONCE,
            run_at=past,
        )
        now = datetime.utcnow()
        result = _compute_next_run(st, now)
        assert result is None

    def test_compute_next_run_daily_schedules_tomorrow_if_time_passed(self):
        """Should schedule for tomorrow if daily time has already passed today."""
        st = ScheduledTask(
            name="Test",
            task_id=1,
            user_id=1,
            enabled=True,
            schedule_type=ScheduleType.DAILY,
            daily_time="08:00",
            timezone="UTC",
        )
        # Set "now" to 10:00 UTC (after 08:00)
        now = datetime.utcnow().replace(hour=10, minute=0, second=0, microsecond=0)
        result = _compute_next_run(st, now)

        # Should be tomorrow at 08:00 UTC
        assert result is not None
        assert result.hour == 8
        assert result.minute == 0
        assert result.date() == (now + timedelta(days=1)).date()

    def test_compute_next_run_daily_schedules_today_if_time_not_passed(self):
        """Should schedule for today if daily time hasn't passed yet."""
        st = ScheduledTask(
            name="Test",
            task_id=1,
            user_id=1,
            enabled=True,
            schedule_type=ScheduleType.DAILY,
            daily_time="14:00",
            timezone="UTC",
        )
        # Set "now" to 10:00 UTC (before 14:00)
        now = datetime.utcnow().replace(hour=10, minute=0, second=0, microsecond=0)
        result = _compute_next_run(st, now)

        # Should be today at 14:00 UTC
        assert result is not None
        assert result.hour == 14
        assert result.minute == 0
        assert result.date() == now.date()

    def test_compute_next_run_weekly_schedules_next_occurrence(self):
        """Should schedule for next occurrence of weekly day."""
        st = ScheduledTask(
            name="Test",
            task_id=1,
            user_id=1,
            enabled=True,
            schedule_type=ScheduleType.WEEKLY,
            daily_time="09:00",
            weekly_day=0,  # Monday
            timezone="UTC",
        )
        # Set "now" to a Tuesday at 10:00
        now = datetime.utcnow().replace(hour=10, minute=0, second=0, microsecond=0)
        # Adjust to a known Tuesday
        while now.weekday() != 1:  # 1 = Tuesday
            now += timedelta(days=1)

        result = _compute_next_run(st, now)

        # Should be next Monday at 09:00
        assert result is not None
        assert result.weekday() == 0  # Monday
        assert result.hour == 9
        assert result.minute == 0

    def test_compute_next_run_monthly_schedules_next_month_if_day_passed(self):
        """Should schedule for next month if monthly day has passed."""
        st = ScheduledTask(
            name="Test",
            task_id=1,
            user_id=1,
            enabled=True,
            schedule_type=ScheduleType.MONTHLY,
            daily_time="09:00",
            monthly_day=15,
            timezone="UTC",
        )
        # Set "now" to the 20th of the month
        now = datetime.utcnow().replace(
            day=20, hour=10, minute=0, second=0, microsecond=0
        )
        result = _compute_next_run(st, now)

        # Should be the 15th of next month
        assert result is not None
        assert result.day == 15
        assert result.hour == 9
        # Should be in the next month
        if now.month == 12:
            assert result.month == 1
            assert result.year == now.year + 1
        else:
            assert result.month == now.month + 1
            assert result.year == now.year

    def test_compute_next_run_monthly_clamps_to_last_day_of_month(self):
        """Should clamp to last day of month if monthly_day exceeds month length."""
        st = ScheduledTask(
            name="Test",
            task_id=1,
            user_id=1,
            enabled=True,
            schedule_type=ScheduleType.MONTHLY,
            daily_time="09:00",
            monthly_day=31,  # Request day 31
            timezone="UTC",
        )
        # Set "now" to February (28/29 days)
        now = datetime(2024, 2, 1, 10, 0, 0)  # Feb 1, 2024
        result = _compute_next_run(st, now)

        # Should be Feb 29, 2024 (leap year)
        assert result is not None
        assert result.day == 29
        assert result.month == 2
        assert result.year == 2024


class TestRunCompilationTask:
    """Test compilation task execution (integration tests with heavy mocking)."""

    @patch("app.tasks.automation._get_db_session")
    def test_run_compilation_task_returns_error_for_missing_task(
        self, mock_get_session, app
    ):
        """Should raise ValueError when CompilationTask doesn't exist."""
        with app.app_context():
            from app.models import db as app_db

            mock_get_session.return_value = (app_db.session, app)

            try:
                run_compilation_task(99999)
                raise AssertionError("Should have raised ValueError")
            except ValueError as e:
                assert "not found" in str(e)

    @patch("app.tasks.automation._get_db_session")
    def test_run_compilation_task_skips_unsupported_source(
        self, mock_get_session, app, test_user
    ):
        """Should skip when source is not supported."""
        with app.app_context():
            from app.models import db as app_db

            ctask = CompilationTask(
                name="Unsupported Source",
                user_id=test_user,
                params={"source": "youtube", "clip_limit": 5},
            )
            app_db.session.add(ctask)
            app_db.session.commit()
            task_id = ctask.id

            mock_get_session.return_value = (app_db.session, app)

            result = run_compilation_task(task_id)

            assert result["status"] == "skipped"
            assert result["reason"] == "unsupported_source"


class TestScheduledTasksTick:
    """Test scheduled task tick processing."""

    @patch("app.tasks.automation._get_db_session")
    @patch("app.tasks.automation.run_compilation_task")
    def test_scheduled_tasks_tick_triggers_due_tasks(
        self, mock_run_task, mock_get_session, app, test_user
    ):
        """Should trigger tasks that are due to run."""
        with app.app_context():
            from app.models import db as app_db

            ctask = CompilationTask(name="Auto Task", user_id=test_user, params={})
            app_db.session.add(ctask)
            app_db.session.commit()

            # Create a scheduled task that's due now
            past = datetime.utcnow() - timedelta(minutes=5)
            st = ScheduledTask(
                name="Due Task",
                task_id=ctask.id,
                user_id=test_user,
                enabled=True,
                schedule_type=ScheduleType.DAILY,
                daily_time="00:00",
                next_run_at=past,
            )
            app_db.session.add(st)
            app_db.session.commit()

            mock_get_session.return_value = (app_db.session, app)
            mock_run_task.apply_async.return_value = MagicMock()

            result = scheduled_tasks_tick()

            assert result["status"] == "ok"
            assert result["triggered"] >= 1
            assert result["examined"] >= 1
            mock_run_task.apply_async.assert_called()

    @patch("app.tasks.automation._get_db_session")
    @patch("app.tasks.automation.run_compilation_task")
    def test_scheduled_tasks_tick_disables_once_tasks_after_execution(
        self, mock_run_task, mock_get_session, app, test_user
    ):
        """Should disable ONCE tasks after they execute."""
        with app.app_context():
            from app.models import db as app_db

            ctask = CompilationTask(name="One-time Task", user_id=test_user, params={})
            app_db.session.add(ctask)
            app_db.session.commit()

            past = datetime.utcnow() - timedelta(minutes=5)
            st = ScheduledTask(
                name="Once Task",
                task_id=ctask.id,
                user_id=test_user,
                enabled=True,
                schedule_type=ScheduleType.ONCE,
                run_at=past,
                next_run_at=past,
            )
            app_db.session.add(st)
            app_db.session.commit()
            st_id = st.id

            mock_get_session.return_value = (app_db.session, app)
            mock_run_task.apply_async.return_value = MagicMock()

            scheduled_tasks_tick()

            # Refresh from database
            st_after = app_db.session.query(ScheduledTask).get(st_id)
            assert st_after.enabled is False

    @patch("app.tasks.automation._get_db_session")
    def test_scheduled_tasks_tick_skips_disabled_tasks(
        self, mock_get_session, app, test_user
    ):
        """Should not trigger disabled tasks."""
        with app.app_context():
            from app.models import db as app_db

            ctask = CompilationTask(name="Disabled Task", user_id=test_user, params={})
            app_db.session.add(ctask)
            app_db.session.commit()

            past = datetime.utcnow() - timedelta(minutes=5)
            st = ScheduledTask(
                name="Disabled",
                task_id=ctask.id,
                user_id=test_user,
                enabled=False,
                schedule_type=ScheduleType.DAILY,
                daily_time="00:00",
                next_run_at=past,
            )
            app_db.session.add(st)
            app_db.session.commit()

            mock_get_session.return_value = (app_db.session, app)

            result = scheduled_tasks_tick()

            assert result["triggered"] == 0

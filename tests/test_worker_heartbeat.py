"""Tests for worker version checking and heartbeat monitoring."""
from unittest.mock import MagicMock, patch

from app.worker_version_check import (
    check_queue_health,
    get_active_workers,
    get_compatible_workers,
    parse_worker_version,
)


class TestParseWorkerVersion:
    """Test worker version parsing from worker names."""

    def test_parse_worker_version_extracts_version_from_tagged_name(self):
        """Should extract version from celery-v0.12.0@hostname format."""
        base_name, version = parse_worker_version("celery-v0.12.0@hostname")
        assert base_name == "celery"
        assert version == "0.12.0"

    def test_parse_worker_version_returns_none_for_untagged_worker(self):
        """Should return None version for celery@hostname format."""
        base_name, version = parse_worker_version("celery@hostname")
        assert base_name == "celery"
        assert version is None

    def test_parse_worker_version_handles_complex_version_tags(self):
        """Should handle version tags with multiple segments."""
        base_name, version = parse_worker_version("celery-v1.2.3-beta@host")
        assert base_name == "celery"
        assert version == "1.2.3-beta"

    def test_parse_worker_version_handles_worker_without_hostname(self):
        """Should handle worker names without @ separator."""
        base_name, version = parse_worker_version("celery-worker")
        assert base_name == "celery-worker"
        assert version is None


class TestGetActiveWorkers:
    """Test active worker discovery and version compatibility."""

    @patch("app.worker_version_check.celery_app.control.inspect")
    @patch("app.worker_version_check.__version__", "0.12.0")
    def test_get_active_workers_returns_compatible_workers(self, mock_inspect):
        """Should mark workers with matching version as compatible."""
        mock_inspector = MagicMock()
        mock_inspect.return_value = mock_inspector
        mock_inspector.active_queues.return_value = {
            "celery-v0.12.0@host1": [{"name": "gpu"}, {"name": "cpu"}],
            "celery-v0.12.0@host2": [{"name": "celery"}],
        }

        result = get_active_workers()

        assert len(result) == 2
        assert result["celery-v0.12.0@host1"]["compatible"] is True
        assert result["celery-v0.12.0@host1"]["version"] == "0.12.0"
        assert result["celery-v0.12.0@host1"]["queues"] == ["gpu", "cpu"]
        assert result["celery-v0.12.0@host2"]["compatible"] is True

    @patch("app.worker_version_check.celery_app.control.inspect")
    @patch("app.worker_version_check.__version__", "0.12.0")
    def test_get_active_workers_marks_version_mismatch_as_incompatible(
        self, mock_inspect
    ):
        """Should mark workers with different version as incompatible."""
        mock_inspector = MagicMock()
        mock_inspect.return_value = mock_inspector
        mock_inspector.active_queues.return_value = {
            "celery-v0.11.0@oldhost": [{"name": "gpu"}],
            "celery-v0.12.0@newhost": [{"name": "gpu"}],
        }

        result = get_active_workers()

        assert result["celery-v0.11.0@oldhost"]["compatible"] is False
        assert (
            result["celery-v0.11.0@oldhost"]["incompatible_reason"]
            == "version_mismatch"
        )
        assert result["celery-v0.12.0@newhost"]["compatible"] is True

    @patch("app.worker_version_check.celery_app.control.inspect")
    @patch("app.worker_version_check.__version__", "0.12.0")
    def test_get_active_workers_marks_untagged_workers_as_incompatible(
        self, mock_inspect
    ):
        """Should mark workers without version tags as incompatible."""
        mock_inspector = MagicMock()
        mock_inspect.return_value = mock_inspector
        mock_inspector.active_queues.return_value = {
            "celery@untagged-host": [{"name": "celery"}],
        }

        result = get_active_workers()

        assert result["celery@untagged-host"]["compatible"] is False
        assert result["celery@untagged-host"]["version"] is None
        assert result["celery@untagged-host"]["incompatible_reason"] == "no_version_tag"

    @patch("app.worker_version_check.celery_app.control.inspect")
    def test_get_active_workers_returns_empty_when_inspector_unavailable(
        self, mock_inspect
    ):
        """Should return empty dict when inspector is unavailable."""
        mock_inspect.return_value = None

        result = get_active_workers()

        assert result == {}

    @patch("app.worker_version_check.celery_app.control.inspect")
    @patch("app.worker_version_check.__version__", "0.12.0")
    def test_get_active_workers_handles_string_queue_format(self, mock_inspect):
        """Should handle queues as strings instead of dicts."""
        mock_inspector = MagicMock()
        mock_inspect.return_value = mock_inspector
        mock_inspector.active_queues.return_value = {
            "celery-v0.12.0@host": ["gpu", "cpu"],  # Strings instead of dicts
        }

        result = get_active_workers()

        assert result["celery-v0.12.0@host"]["queues"] == ["gpu", "cpu"]
        assert result["celery-v0.12.0@host"]["compatible"] is True


class TestGetCompatibleWorkers:
    """Test compatible worker filtering by queue."""

    @patch("app.worker_version_check.get_active_workers")
    def test_get_compatible_workers_returns_only_compatible_for_queue(
        self, mock_get_active
    ):
        """Should return only compatible workers for specified queue."""
        mock_get_active.return_value = {
            "celery-v0.12.0@host1": {
                "queues": ["gpu", "cpu"],
                "version": "0.12.0",
                "compatible": True,
                "base_name": "celery",
            },
            "celery-v0.11.0@host2": {
                "queues": ["gpu"],
                "version": "0.11.0",
                "compatible": False,
                "base_name": "celery",
            },
            "celery-v0.12.0@host3": {
                "queues": ["celery"],
                "version": "0.12.0",
                "compatible": True,
                "base_name": "celery",
            },
        }

        result = get_compatible_workers("gpu")

        assert len(result) == 1
        assert "celery-v0.12.0@host1" in result
        assert "celery-v0.11.0@host2" not in result  # Incompatible version
        assert "celery-v0.12.0@host3" not in result  # Wrong queue

    @patch("app.worker_version_check.get_active_workers")
    def test_get_compatible_workers_returns_empty_for_nonexistent_queue(
        self, mock_get_active
    ):
        """Should return empty list when no workers handle the queue."""
        mock_get_active.return_value = {
            "celery-v0.12.0@host1": {
                "queues": ["cpu"],
                "version": "0.12.0",
                "compatible": True,
                "base_name": "celery",
            }
        }

        result = get_compatible_workers("gpu")

        assert result == []


class TestCheckQueueHealth:
    """Test queue health checking."""

    @patch("app.worker_version_check.get_active_workers")
    def test_check_queue_health_returns_healthy_when_sufficient_workers(
        self, mock_get_active
    ):
        """Should return healthy=True when minimum workers are available."""
        mock_get_active.return_value = {
            "celery-v0.12.0@host1": {
                "queues": ["gpu"],
                "version": "0.12.0",
                "compatible": True,
                "base_name": "celery",
            },
            "celery-v0.12.0@host2": {
                "queues": ["gpu"],
                "version": "0.12.0",
                "compatible": True,
                "base_name": "celery",
            },
        }

        result = check_queue_health("gpu", min_workers=1)

        assert result["healthy"] is True
        assert result["compatible_workers"] == 2
        assert result["incompatible_workers"] == 0
        assert len(result["worker_names"]) == 2

    @patch("app.worker_version_check.get_active_workers")
    def test_check_queue_health_returns_unhealthy_when_insufficient_workers(
        self, mock_get_active
    ):
        """Should return healthy=False when fewer than minimum workers."""
        mock_get_active.return_value = {
            "celery-v0.12.0@host1": {
                "queues": ["gpu"],
                "version": "0.12.0",
                "compatible": True,
                "base_name": "celery",
            }
        }

        result = check_queue_health("gpu", min_workers=2)

        assert result["healthy"] is False
        assert result["compatible_workers"] == 1

    @patch("app.worker_version_check.get_active_workers")
    def test_check_queue_health_counts_incompatible_workers(self, mock_get_active):
        """Should count incompatible workers separately."""
        mock_get_active.return_value = {
            "celery-v0.12.0@host1": {
                "queues": ["gpu"],
                "version": "0.12.0",
                "compatible": True,
                "base_name": "celery",
            },
            "celery-v0.11.0@host2": {
                "queues": ["gpu"],
                "version": "0.11.0",
                "compatible": False,
                "base_name": "celery",
            },
            "celery@host3": {
                "queues": ["gpu"],
                "version": None,
                "compatible": False,
                "base_name": "celery",
            },
        }

        result = check_queue_health("gpu", min_workers=1)

        assert result["healthy"] is True
        assert result["compatible_workers"] == 1
        assert result["incompatible_workers"] == 2
        assert len(result["worker_names"]) == 1
        assert "celery-v0.12.0@host1" in result["worker_names"]

    @patch("app.worker_version_check.get_active_workers")
    def test_check_queue_health_ignores_workers_for_other_queues(self, mock_get_active):
        """Should only count workers handling the specified queue."""
        mock_get_active.return_value = {
            "celery-v0.12.0@gpu-worker": {
                "queues": ["gpu"],
                "version": "0.12.0",
                "compatible": True,
                "base_name": "celery",
            },
            "celery-v0.12.0@cpu-worker": {
                "queues": ["cpu"],
                "version": "0.12.0",
                "compatible": True,
                "base_name": "celery",
            },
        }

        result = check_queue_health("gpu", min_workers=1)

        assert result["healthy"] is True
        assert result["compatible_workers"] == 1
        assert "celery-v0.12.0@gpu-worker" in result["worker_names"]
        assert "celery-v0.12.0@cpu-worker" not in result["worker_names"]

    @patch("app.worker_version_check.get_active_workers")
    def test_check_queue_health_returns_unhealthy_when_no_workers(
        self, mock_get_active
    ):
        """Should return unhealthy when no workers are active."""
        mock_get_active.return_value = {}

        result = check_queue_health("gpu", min_workers=1)

        assert result["healthy"] is False
        assert result["compatible_workers"] == 0
        assert result["incompatible_workers"] == 0
        assert result["worker_names"] == []

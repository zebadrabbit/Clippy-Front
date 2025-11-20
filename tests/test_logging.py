"""Tests for logging configuration and rotation."""
import logging
import os
import tempfile
from logging.handlers import RotatingFileHandler
from unittest.mock import patch

from app.logging_config import (
    attach_celery_file_logging,
    attach_named_file_logging,
    configure_logging,
    get_log_dir,
)


class TestGetLogDir:
    """Test log directory resolution."""

    def test_get_log_dir_returns_override_when_provided(self):
        """Should return override argument when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = get_log_dir(instance_path="/some/path", override=tmpdir)
            assert result == tmpdir

    def test_get_log_dir_returns_env_var_when_no_override(self):
        """Should return LOG_DIR env var when no override provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"LOG_DIR": tmpdir}):
                result = get_log_dir(instance_path="/some/path")
                assert result == tmpdir

    def test_get_log_dir_returns_instance_path_logs_by_default(self):
        """Should return instance_path/logs when no override or env var."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {}, clear=True):
                result = get_log_dir(instance_path=tmpdir)
                expected = os.path.join(tmpdir, "logs")
                assert result == expected

    def test_get_log_dir_creates_directory_if_missing(self):
        """Should create the log directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = os.path.join(tmpdir, "new_logs")
            result = get_log_dir(instance_path=tmpdir, override=log_dir)
            assert os.path.exists(result)
            assert os.path.isdir(result)


class TestConfigureLogging:
    """Test logging configuration for Flask app."""

    def test_configure_logging_skips_in_testing_mode(self, app):
        """Should skip file logging when TESTING=True."""
        # The conftest.py fixture already sets TESTING=True
        result = configure_logging(app, role="web")

        assert result["log_dir"] == ""
        assert result["app_log"] == ""
        assert result["worker_log"] == ""

    def test_configure_logging_creates_log_files_in_production_mode(self):
        """Should create log files when not in testing mode."""
        from app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            test_app = create_app()
            test_app.config["TESTING"] = False
            test_app.instance_path = tmpdir

            # Reset the global flag to allow configuration
            import app.logging_config

            original_flag = app.logging_config._LOGGING_CONFIGURED
            try:
                app.logging_config._LOGGING_CONFIGURED = False

                result = configure_logging(test_app, role="web")

                assert result["log_dir"] == os.path.join(tmpdir, "logs")
                assert result["app_log"] == os.path.join(tmpdir, "logs", "app.log")
                assert result["worker_log"] == os.path.join(
                    tmpdir, "logs", "worker.log"
                )
                assert os.path.exists(result["log_dir"])
            finally:
                # Restore original flag
                app.logging_config._LOGGING_CONFIGURED = original_flag

    def test_configure_logging_sets_log_level_from_config(self):
        """Should respect LOG_LEVEL from app config."""
        from app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            test_app = create_app()
            test_app.config["TESTING"] = False
            test_app.config["LOG_LEVEL"] = "DEBUG"
            test_app.instance_path = tmpdir

            import app.logging_config

            original_flag = app.logging_config._LOGGING_CONFIGURED
            try:
                app.logging_config._LOGGING_CONFIGURED = False

                configure_logging(test_app, role="web")

                # Root logger should be at DEBUG level
                root_logger = logging.getLogger()
                assert root_logger.level == logging.DEBUG
            finally:
                app.logging_config._LOGGING_CONFIGURED = original_flag
                # Reset root logger
                root_logger.setLevel(logging.WARNING)

    def test_configure_logging_silences_werkzeug_unless_debug(self):
        """Should set Werkzeug logger to WARNING unless LOG_LEVEL is DEBUG."""
        from app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            test_app = create_app()
            test_app.config["TESTING"] = False
            test_app.config["LOG_LEVEL"] = "INFO"
            test_app.instance_path = tmpdir

            import app.logging_config

            original_flag = app.logging_config._LOGGING_CONFIGURED
            try:
                app.logging_config._LOGGING_CONFIGURED = False

                configure_logging(test_app, role="web")

                werkzeug_logger = logging.getLogger("werkzeug")
                assert werkzeug_logger.level == logging.WARNING
            finally:
                app.logging_config._LOGGING_CONFIGURED = original_flag

    def test_configure_logging_only_runs_once_per_process(self):
        """Should not add duplicate handlers on subsequent calls."""
        from app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            test_app = create_app()
            test_app.config["TESTING"] = False
            test_app.instance_path = tmpdir

            import app.logging_config

            original_flag = app.logging_config._LOGGING_CONFIGURED
            try:
                app.logging_config._LOGGING_CONFIGURED = False

                root_logger = logging.getLogger()
                initial_handler_count = len(root_logger.handlers)

                # First call
                configure_logging(test_app, role="web")
                first_call_count = len(root_logger.handlers)

                # Second call
                configure_logging(test_app, role="web")
                second_call_count = len(root_logger.handlers)

                # Should not add more handlers on second call
                assert first_call_count > initial_handler_count
                assert second_call_count == first_call_count
            finally:
                app.logging_config._LOGGING_CONFIGURED = original_flag


class TestAttachCeleryFileLogging:
    """Test Celery logger attachment."""

    def test_attach_celery_file_logging_adds_rotating_handler(self):
        """Should add a RotatingFileHandler to the logger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = logging.getLogger("test_celery_logger")
            logger.handlers.clear()

            attach_celery_file_logging(logger, tmpdir)

            # Check that a RotatingFileHandler was added
            rotating_handlers = [
                h for h in logger.handlers if isinstance(h, RotatingFileHandler)
            ]
            assert len(rotating_handlers) == 1
            assert rotating_handlers[0].baseFilename == os.path.join(
                tmpdir, "logs", "worker.log"
            )

    def test_attach_celery_file_logging_avoids_duplicates(self):
        """Should not add duplicate handlers for the same file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = logging.getLogger("test_celery_logger_dupe")
            logger.handlers.clear()

            # Attach twice
            attach_celery_file_logging(logger, tmpdir)
            attach_celery_file_logging(logger, tmpdir)

            # Should only have one handler
            rotating_handlers = [
                h for h in logger.handlers if isinstance(h, RotatingFileHandler)
            ]
            assert len(rotating_handlers) == 1

    def test_attach_celery_file_logging_respects_log_level_env(self):
        """Should use LOG_LEVEL from environment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = logging.getLogger("test_celery_logger_level")
            logger.handlers.clear()

            with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
                attach_celery_file_logging(logger, tmpdir)

                rotating_handlers = [
                    h for h in logger.handlers if isinstance(h, RotatingFileHandler)
                ]
                assert rotating_handlers[0].level == logging.DEBUG


class TestAttachNamedFileLogging:
    """Test named file logger attachment."""

    def test_attach_named_file_logging_creates_custom_log_file(self):
        """Should create a handler for a custom log filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = logging.getLogger("test_named_logger")
            logger.handlers.clear()

            attach_named_file_logging(logger, tmpdir, "custom.log")

            rotating_handlers = [
                h for h in logger.handlers if isinstance(h, RotatingFileHandler)
            ]
            assert len(rotating_handlers) == 1
            assert rotating_handlers[0].baseFilename == os.path.join(
                tmpdir, "logs", "custom.log"
            )

    def test_attach_named_file_logging_avoids_duplicates(self):
        """Should not add duplicate handlers for the same named file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = logging.getLogger("test_named_logger_dupe")
            logger.handlers.clear()

            attach_named_file_logging(logger, tmpdir, "beat.log")
            attach_named_file_logging(logger, tmpdir, "beat.log")

            rotating_handlers = [
                h for h in logger.handlers if isinstance(h, RotatingFileHandler)
            ]
            assert len(rotating_handlers) == 1

    def test_attach_named_file_logging_allows_multiple_files(self):
        """Should allow multiple handlers for different filenames."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = logging.getLogger("test_named_logger_multi")
            logger.handlers.clear()

            attach_named_file_logging(logger, tmpdir, "beat.log")
            attach_named_file_logging(logger, tmpdir, "scheduler.log")

            rotating_handlers = [
                h for h in logger.handlers if isinstance(h, RotatingFileHandler)
            ]
            assert len(rotating_handlers) == 2

            filenames = {h.baseFilename for h in rotating_handlers}
            assert os.path.join(tmpdir, "logs", "beat.log") in filenames
            assert os.path.join(tmpdir, "logs", "scheduler.log") in filenames


class TestRotatingFileHandler:
    """Test that rotating file handlers are configured correctly."""

    def test_rotating_handler_has_correct_rotation_settings(self):
        """Should configure 10MB max size and 5 backups."""
        from app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            test_app = create_app()
            test_app.config["TESTING"] = False
            test_app.instance_path = tmpdir

            import app.logging_config

            original_flag = app.logging_config._LOGGING_CONFIGURED
            try:
                app.logging_config._LOGGING_CONFIGURED = False

                configure_logging(test_app, role="web")

                root_logger = logging.getLogger()
                rotating_handlers = [
                    h
                    for h in root_logger.handlers
                    if isinstance(h, RotatingFileHandler)
                ]

                # Check that at least one handler has correct settings
                assert len(rotating_handlers) > 0
                handler = rotating_handlers[0]
                assert handler.maxBytes == 10 * 1024 * 1024  # 10 MB
                assert handler.backupCount == 5
            finally:
                app.logging_config._LOGGING_CONFIGURED = original_flag

    def test_rotating_handler_has_correct_format(self):
        """Should use the expected log format."""
        from app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            test_app = create_app()
            test_app.config["TESTING"] = False
            test_app.instance_path = tmpdir

            import app.logging_config

            original_flag = app.logging_config._LOGGING_CONFIGURED
            try:
                app.logging_config._LOGGING_CONFIGURED = False

                configure_logging(test_app, role="web")

                root_logger = logging.getLogger()
                rotating_handlers = [
                    h
                    for h in root_logger.handlers
                    if isinstance(h, RotatingFileHandler)
                ]

                handler = rotating_handlers[0]
                formatter = handler.formatter
                assert formatter is not None
                # Check that format includes expected fields
                format_str = formatter._fmt
                assert "%(asctime)s" in format_str
                assert "%(levelname)s" in format_str
                assert "%(processName)s" in format_str
                assert "%(message)s" in format_str
            finally:
                app.logging_config._LOGGING_CONFIGURED = original_flag

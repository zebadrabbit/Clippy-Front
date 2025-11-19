# ruff: noqa: I001
"""
Centralized logging configuration with rotating file handlers.

This module configures consistent, size-rotating log files for both the Flask
web app and Celery workers. Logs are written under the instance's logs/
directory by default, and can be overridden via LOG_DIR.

Usage:
    from app.logging_config import configure_logging
    configure_logging(app, role="web")

For Celery workers, use the provided helper in celery signals to attach
handlers to Celery's logger hierarchy.
"""
import logging
import os
from logging.handlers import RotatingFileHandler


# Module-level guard to avoid duplicate handlers per process
_LOGGING_CONFIGURED = False


def _ensure_dir(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        # Non-fatal; logging will fallback to stderr if directory is not writable
        pass


def get_log_dir(instance_path: str, override: str | None = None) -> str:
    """Resolve the directory where log files will be stored.

    Order of preference:
    1) explicit override argument
    2) LOG_DIR env var
    3) <instance_path>/logs
    """
    base = override or os.environ.get("LOG_DIR")
    if not base:
        base = os.path.join(instance_path, "logs")
    _ensure_dir(base)
    return base


def _build_file_handler(path: str, level: int) -> RotatingFileHandler:
    # 10 MB per file, keep 5 backups by default
    handler = RotatingFileHandler(path, maxBytes=10 * 1024 * 1024, backupCount=5)
    handler.setLevel(level)
    fmt = (
        "%(asctime)s [%(levelname)s] %(processName)s %(name)s: "
        "%(message)s (%(filename)s:%(lineno)d)"
    )
    handler.setFormatter(logging.Formatter(fmt))
    return handler


def configure_logging(app, role: str = "web") -> dict:
    """Configure rotating file logging for the application.

    - Creates instance/logs/ if missing
    - Attaches a RotatingFileHandler to both app.logger and the root logger
    - Avoids duplicate handler attachment per process

    Args:
        app: Flask app instance (must have .instance_path and .config)
        role: "web" or "worker" for log file naming

    Returns:
        dict with keys: log_dir, app_log, worker_log
    """
    global _LOGGING_CONFIGURED
    # Never configure file logging in tests to keep them hermetic
    if app.config.get("TESTING"):
        return {
            "log_dir": "",
            "app_log": "",
            "worker_log": "",
        }

    log_dir = get_log_dir(app.instance_path)
    app_log_path = os.path.join(log_dir, "app.log")
    worker_log_path = os.path.join(log_dir, "worker.log")

    # Determine base logging level from config or env
    level_name = str(app.config.get("LOG_LEVEL", os.environ.get("LOG_LEVEL", "INFO")))
    level = getattr(logging, level_name.upper(), logging.INFO)

    # Attach handlers only once per process to prevent duplication
    if not _LOGGING_CONFIGURED:
        try:
            root = logging.getLogger()
            root.setLevel(level)

            # Root handler: app.log for general logs
            root.addHandler(_build_file_handler(app_log_path, level))

            # Specific handler for worker logs (still attach to root so messages propagate)
            # Celery's own logger will also add handlers; we add one more for unified file.
            root.addHandler(_build_file_handler(worker_log_path, level))

            # Silence noisy Werkzeug request logs unless we're in DEBUG mode
            # These GET /api/* polling requests overwhelm INFO logs
            werkzeug_logger = logging.getLogger("werkzeug")
            if level > logging.DEBUG:
                werkzeug_logger.setLevel(logging.WARNING)

            _LOGGING_CONFIGURED = True
        except Exception:
            # If file handler cannot be created, keep default stderr logging
            _LOGGING_CONFIGURED = True

    # Ensure app.logger is at least at the configured level
    try:
        app.logger.setLevel(level)
    except Exception:
        pass

    # Light hint in the log about where files are emitted (debug-level to avoid noise)
    try:
        app.logger.debug("Logging to %s (app.log, worker.log)", log_dir)
    except Exception:
        pass

    return {
        "log_dir": log_dir,
        "app_log": app_log_path,
        "worker_log": worker_log_path,
    }


def attach_celery_file_logging(logger, instance_path: str) -> None:
    """Attach a rotating file handler to a given Celery logger.

    This is safe to call multiple times; it checks for an existing handler
    pointing to the target file.
    """
    try:
        log_dir = get_log_dir(instance_path)
        target = os.path.join(log_dir, "worker.log")
        level_name = os.environ.get("LOG_LEVEL", "INFO")
        level = getattr(logging, level_name.upper(), logging.INFO)

        # Avoid duplicates
        for h in logger.handlers:
            if isinstance(h, RotatingFileHandler):
                try:
                    if getattr(h, "baseFilename", None) == target:
                        return
                except Exception:
                    continue

        logger.addHandler(_build_file_handler(target, level))
    except Exception:
        # Non-fatal: Celery will still log to stderr
        pass


def attach_named_file_logging(logger, instance_path: str, filename: str) -> None:
    """Attach a rotating file handler for an arbitrary log filename.

    Useful for separating logs like 'beat.log'. Safe to call multiple times.
    """
    try:
        log_dir = get_log_dir(instance_path)
        target = os.path.join(log_dir, filename)
        level_name = os.environ.get("LOG_LEVEL", "INFO")
        level = getattr(logging, level_name.upper(), logging.INFO)
        for h in logger.handlers:
            if isinstance(h, RotatingFileHandler):
                try:
                    if getattr(h, "baseFilename", None) == target:
                        return
                except Exception:
                    continue
        logger.addHandler(_build_file_handler(target, level))
    except Exception:
        pass

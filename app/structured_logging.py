"""
Structured logging configuration using structlog.

This module provides a robust, production-ready logging system with:
- Structured JSON output for easy parsing and analysis
- Context-aware logging (request IDs, user IDs, task IDs, etc.)
- Automatic log level filtering by component
- Clean human-readable console output in development
- Efficient log rotation and archiving
- Integration with Flask and Celery

Usage in Flask:
    from app.structured_logging import configure_structlog
    configure_structlog(app, role="web")

Usage in Celery:
    from app.structured_logging import configure_structlog_celery
    configure_structlog_celery(instance_path)

Usage in code:
    import structlog
    logger = structlog.get_logger(__name__)
    logger.info("user_action", action="download_clip", clip_id=123, user_id=5)
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

try:
    from pythonjsonlogger.json import JsonFormatter as jsonlogger
except ImportError:
    # Fallback for older versions
    from pythonjsonlogger import jsonlogger  # type: ignore

# Module-level guard to avoid duplicate configuration
_STRUCTLOG_CONFIGURED = False


def _ensure_dir(path: str) -> None:
    """Ensure directory exists."""
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
    except Exception:
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


def _add_request_context(logger, method_name, event_dict):
    """Add Flask request context to log events."""
    try:
        from flask import g, has_request_context, request

        if has_request_context():
            event_dict["endpoint"] = request.endpoint
            event_dict["method"] = request.method
            event_dict["path"] = request.path
            event_dict["remote_addr"] = request.remote_addr

            # Add request ID if available
            if hasattr(g, "request_id"):
                event_dict["request_id"] = g.request_id

            # Add current user if available
            try:
                from flask_login import current_user

                if current_user and current_user.is_authenticated:
                    event_dict["user_id"] = current_user.id
                    event_dict["username"] = current_user.username
            except Exception:
                pass
    except Exception:
        pass
    return event_dict


def _add_celery_context(logger, method_name, event_dict):
    """Add Celery task context to log events."""
    try:
        from celery import current_task

        if current_task and current_task.request:
            task_req = current_task.request
            event_dict["task_id"] = task_req.id
            event_dict["task_name"] = task_req.task
            if hasattr(task_req, "retries"):
                event_dict["task_retries"] = task_req.retries
    except Exception:
        pass
    return event_dict


def _filter_health_checks(logger, method_name, event_dict):
    """Filter out noisy health check and polling requests at INFO level."""
    # Only filter at INFO level and above (not DEBUG)
    if event_dict.get("level") in ("info", "warning"):
        endpoint = event_dict.get("endpoint", "")
        path = event_dict.get("path", "")

        # Skip logging for health checks and frequent polling
        noisy_patterns = [
            "/api/health",
            "/api/tasks/",
            "/api/jobs/recent",
            "/api/projects/",
            "/health",
        ]

        for pattern in noisy_patterns:
            if pattern in path or pattern in endpoint:
                raise structlog.DropEvent

    return event_dict


def _censor_sensitive_data(logger, method_name, event_dict):
    """Remove or redact sensitive data from logs."""
    sensitive_keys = {
        "password",
        "api_key",
        "secret",
        "token",
        "authorization",
        "cookie",
        "csrf_token",
    }

    for key in list(event_dict.keys()):
        if any(sens in key.lower() for sens in sensitive_keys):
            event_dict[key] = "***REDACTED***"

    return event_dict


def _build_json_handler(path: str, level: int) -> RotatingFileHandler:
    """Build a rotating file handler with JSON formatting."""
    # 50 MB per file, keep 10 backups (500 MB total)
    handler = RotatingFileHandler(path, maxBytes=50 * 1024 * 1024, backupCount=10)
    handler.setLevel(level)

    # Use JSON formatter for structured output
    try:
        formatter = jsonlogger(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    except TypeError:
        # Older version signature
        formatter = jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    handler.setFormatter(formatter)
    return handler


def _build_console_handler(
    level: int, use_colors: bool = True
) -> logging.StreamHandler:
    """Build a console handler with human-readable formatting."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if use_colors and sys.stderr.isatty():
        # Use colored console output for development
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)-8s] %(name)-25s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
    else:
        # Simple format for non-TTY or production
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    return handler


def get_log_level(app_config: dict | None = None) -> int:
    """Determine log level from config or environment."""
    level_name = "INFO"

    # Priority: app config > env var > default
    if app_config and "LOG_LEVEL" in app_config:
        level_name = str(app_config["LOG_LEVEL"])
    else:
        level_name = os.environ.get("LOG_LEVEL", "INFO")

    return getattr(logging, level_name.upper(), logging.INFO)


def configure_component_loggers(base_level: int) -> None:
    """Configure log levels for specific components.

    This allows fine-grained control over verbosity:
    - Werkzeug: only warnings (suppress request logs)
    - SQLAlchemy: only warnings (suppress query logs unless DEBUG)
    - Celery: info level
    - App: use base level
    """
    # Werkzeug (Flask's request logger) - suppress unless ERROR
    logging.getLogger("werkzeug").setLevel(
        logging.DEBUG if base_level <= logging.DEBUG else logging.WARNING
    )

    # SQLAlchemy - suppress query spam unless in DEBUG
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if base_level <= logging.DEBUG else logging.WARNING
    )

    # Celery - always at INFO minimum
    logging.getLogger("celery").setLevel(min(base_level, logging.INFO))

    # urllib3 and requests - reduce noise
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    # Discord.py can be very verbose
    logging.getLogger("discord").setLevel(logging.WARNING)

    # yt-dlp is extremely noisy
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)


def configure_structlog(app, role: str = "web") -> dict:
    """Configure structlog for Flask application.

    Args:
        app: Flask app instance (must have .instance_path and .config)
        role: "web" or "worker" for context identification

    Returns:
        dict with keys: log_dir, app_log, worker_log, error_log
    """
    global _STRUCTLOG_CONFIGURED

    # Never configure file logging in tests
    if app.config.get("TESTING"):
        # Configure minimal structlog for tests
        if not _STRUCTLOG_CONFIGURED:
            structlog.configure(
                processors=[
                    structlog.processors.add_log_level,
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.dev.ConsoleRenderer(),
                ],
                wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
                context_class=dict,
                logger_factory=structlog.PrintLoggerFactory(),
                cache_logger_on_first_use=True,
            )
            _STRUCTLOG_CONFIGURED = True
        return {
            "log_dir": "",
            "app_log": "",
            "worker_log": "",
            "error_log": "",
        }

    log_dir = get_log_dir(app.instance_path)
    app_log_path = os.path.join(log_dir, "app.json")
    worker_log_path = os.path.join(log_dir, "worker.json")
    error_log_path = os.path.join(log_dir, "error.json")

    level = get_log_level(app.config)

    # Configure standard logging first (structlog wraps it)
    if not _STRUCTLOG_CONFIGURED:
        root = logging.getLogger()
        root.setLevel(level)
        root.handlers.clear()  # Remove any existing handlers

        # JSON handlers for parsing/analysis
        root.addHandler(_build_json_handler(app_log_path, level))

        # Separate error log (WARNING and above only)
        root.addHandler(_build_json_handler(error_log_path, logging.WARNING))

        # Console handler for development visibility
        is_dev = app.debug or app.config.get("ENV") == "development"
        root.addHandler(_build_console_handler(level, use_colors=is_dev))

        # Configure component-specific log levels
        configure_component_loggers(level)

        # Configure structlog processors
        processors = [
            # Add log level to event dict
            structlog.processors.add_log_level,
            # Add timestamp
            structlog.processors.TimeStamper(fmt="iso"),
            # Add logger name
            structlog.stdlib.add_logger_name,
            # Add source location (file:line)
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.LINENO,
                }
            ),
            # Add Flask request context
            _add_request_context,
            # Add Celery task context
            _add_celery_context,
            # Filter out noisy endpoints
            _filter_health_checks,
            # Censor sensitive data
            _censor_sensitive_data,
            # Format for stdlib logging
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]

        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(level),
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        _STRUCTLOG_CONFIGURED = True

    # Light debug message (won't show unless LOG_LEVEL=DEBUG)
    logger = structlog.get_logger(__name__)
    logger.debug(
        "logging_configured",
        role=role,
        log_dir=log_dir,
        level=logging.getLevelName(level),
    )

    return {
        "log_dir": log_dir,
        "app_log": app_log_path,
        "worker_log": worker_log_path,
        "error_log": error_log_path,
    }


def configure_structlog_celery(instance_path: str) -> None:
    """Configure structlog for Celery workers.

    Args:
        instance_path: Path to instance directory for log files
    """
    global _STRUCTLOG_CONFIGURED

    if _STRUCTLOG_CONFIGURED:
        return

    log_dir = get_log_dir(instance_path)
    worker_log_path = os.path.join(log_dir, "worker.json")
    error_log_path = os.path.join(log_dir, "error.json")

    level_name = os.environ.get("LOG_LEVEL", "INFO")
    level = getattr(logging, level_name.upper(), logging.INFO)

    # Configure standard logging
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # JSON handlers
    root.addHandler(_build_json_handler(worker_log_path, level))
    root.addHandler(_build_json_handler(error_log_path, logging.WARNING))

    # Console for worker visibility
    root.addHandler(_build_console_handler(level, use_colors=False))

    # Configure component loggers
    configure_component_loggers(level)

    # Configure structlog
    processors = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
        structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.LINENO,
            }
        ),
        _add_celery_context,
        _censor_sensitive_data,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _STRUCTLOG_CONFIGURED = True

    logger = structlog.get_logger(__name__)
    logger.debug("celery_logging_configured", log_dir=log_dir, level=level_name)


def get_logger(name: str = None):
    """Get a structlog logger instance.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)

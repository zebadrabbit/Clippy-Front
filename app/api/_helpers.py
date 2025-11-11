"""Small helper utilities for API modules.

Keep lightweight helpers here so route modules can import useful helpers
without pulling in heavy app state (avoid circular imports).
"""


def log_exception(logger, msg: str, exc: BaseException | None = None) -> None:
    """Log an exception safely and include stack trace when possible.

    This wraps common logging patterns to ensure consistent messages and to
    avoid raising from logging itself. Prefer calling code to pass the
    module's logger (e.g., current_app.logger) and the caught exception.

    Args:
        logger: Any logger-like object with `.exception` and `.error`.
        msg: Short context message describing where/what failed.
        exc: Optional exception instance to include.
    """
    try:
        if exc is not None:
            # .exception logs the stack trace automatically for the active exception
            logger.exception(f"{msg}: {exc}")
        else:
            logger.exception(msg)
    except Exception:
        # Last-resort: if the logger itself fails, try a safe .error call
        try:
            logger.error(f"(logging-failed) {msg}")
        except Exception:
            # Give up silently rather than raise from a logging helper
            pass

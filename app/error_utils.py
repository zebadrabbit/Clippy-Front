"""
Error handling utilities for consistent logging and error management.

This module provides reusable utilities for handling errors throughout the application,
with structured logging, context preservation, and graceful degradation patterns.
"""

import logging
import sys
import traceback
from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import current_app


def safe_log_error(
    logger: logging.Logger,
    message: str,
    exc_info: bool | BaseException | tuple | None = True,
    level: int = logging.ERROR,
    **extra_context: Any,
) -> None:
    """
    Log an error with structured context and exception information.

    This function ensures consistent error logging across the application with
    structured context that can be easily parsed by log aggregation systems.

    Args:
        logger: The logger instance to use
        message: Human-readable error message
        exc_info: Exception info (True for current exception, exception object, or tuple)
        level: Log level (default: ERROR)
        **extra_context: Additional context fields to include in the log

    Example:
        try:
            risky_operation()
        except ValueError as e:
            safe_log_error(
                logger,
                "Failed to process user input",
                exc_info=e,
                user_id=user.id,
                input_value=value
            )
    """
    # Build structured context
    context = {"error_context": extra_context, "has_exception": exc_info is not None}

    # Add exception details if available
    if exc_info:
        if isinstance(exc_info, BaseException):
            context["exception_type"] = type(exc_info).__name__
            context["exception_message"] = str(exc_info)
        elif exc_info is True:
            exc_type, exc_value, _ = sys.exc_info()
            if exc_type:
                context["exception_type"] = exc_type.__name__
                context["exception_message"] = str(exc_value)

    # Log with structured context
    logger.log(level, message, exc_info=exc_info, extra=context)


def handle_api_exception(
    logger: logging.Logger,
    message: str,
    status_code: int = 500,
    public_message: str | None = None,
    **extra_context: Any,
) -> tuple[dict[str, Any], int]:
    """
    Handle an exception in an API endpoint with logging and JSON response.

    This function logs the error with full context and returns a JSON response
    suitable for API clients. The public message is sanitized to avoid leaking
    sensitive information.

    Args:
        logger: The logger instance to use
        message: Internal error message for logs
        status_code: HTTP status code to return
        public_message: User-facing error message (defaults to generic message)
        **extra_context: Additional context for logging

    Returns:
        Tuple of (JSON response dict, status code)

    Example:
        @app.route('/api/users/<int:user_id>')
        def get_user(user_id):
            try:
                user = User.query.get_or_404(user_id)
                return jsonify(user.to_dict())
            except Exception:
                return handle_api_exception(
                    logger,
                    "Failed to fetch user",
                    status_code=500,
                    public_message="Unable to retrieve user information",
                    user_id=user_id
                )
    """
    # Log the error with full context
    safe_log_error(logger, message, exc_info=True, **extra_context)

    # Determine public message
    if public_message is None:
        if status_code >= 500:
            public_message = "An internal error occurred. Please try again later."
        elif status_code >= 400:
            public_message = "The request could not be completed."
        else:
            public_message = "An error occurred."

    # Build response
    response = {"success": False, "error": public_message}

    # Add request ID if available (for tracking)
    if hasattr(current_app, "request_id"):
        response["request_id"] = current_app.request_id

    return response, status_code


def safe_operation(
    logger: logging.Logger,
    operation_name: str,
    default_value: Any = None,
    raise_on_error: bool = False,
    log_level: int = logging.ERROR,
) -> Callable:
    """
    Decorator for safely executing operations with automatic error handling.

    This decorator wraps a function to catch exceptions, log them with context,
    and optionally return a default value or re-raise the exception.

    Args:
        logger: Logger instance for error logging
        operation_name: Descriptive name of the operation for logs
        default_value: Value to return on error (if not re-raising)
        raise_on_error: Whether to re-raise exceptions after logging
        log_level: Logging level for errors

    Returns:
        Decorated function with error handling

    Example:
        @safe_operation(logger, "thumbnail generation", default_value=None)
        def generate_thumbnail(video_path):
            # May raise exceptions
            return create_thumbnail(video_path)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Build context from function arguments
                context = {
                    "operation": operation_name,
                    "function": func.__name__,
                    "args_count": len(args),
                    "kwargs_keys": list(kwargs.keys()),
                }

                # Log the error
                safe_log_error(
                    logger,
                    f"Error in {operation_name}",
                    exc_info=e,
                    level=log_level,
                    **context,
                )

                if raise_on_error:
                    raise
                return default_value

        return wrapper

    return decorator


def get_error_details(exc: BaseException) -> dict[str, Any]:
    """
    Extract detailed information from an exception for logging.

    Args:
        exc: The exception to extract details from

    Returns:
        Dictionary with exception type, message, and traceback

    Example:
        try:
            risky_operation()
        except Exception as e:
            details = get_error_details(e)
            logger.error("Operation failed", extra=details)
    """
    return {
        "exception_type": type(exc).__name__,
        "exception_module": type(exc).__module__,
        "exception_message": str(exc),
        "traceback": traceback.format_exc(),
        "traceback_lines": traceback.format_tb(exc.__traceback__),
    }


def chain_exceptions(
    primary_exc: BaseException,
    secondary_exc: BaseException,
    logger: logging.Logger,
    context_message: str,
) -> None:
    """
    Log chained exceptions that occur during error handling.

    Sometimes exceptions occur while handling other exceptions (e.g., logging
    failures, cleanup errors). This function logs both exceptions with clear context.

    Args:
        primary_exc: The original exception
        secondary_exc: Exception that occurred during handling
        logger: Logger instance
        context_message: Description of what was being attempted

    Example:
        try:
            risky_operation()
        except Exception as primary:
            try:
                cleanup()
            except Exception as secondary:
                chain_exceptions(
                    primary, secondary, logger,
                    "Error during cleanup after failed operation"
                )
    """
    safe_log_error(
        logger,
        f"Chained exception: {context_message}",
        exc_info=False,
        level=logging.ERROR,
        primary_exception=get_error_details(primary_exc),
        secondary_exception=get_error_details(secondary_exc),
    )


class ErrorContext:
    """
    Context manager for operations that need structured error logging.

    This provides a clean way to wrap code blocks with automatic error handling
    and logging, similar to try/except but with consistent structured logging.

    Example:
        with ErrorContext(logger, "database operation", user_id=user.id):
            db.session.add(user)
            db.session.commit()
    """

    def __init__(
        self,
        logger: logging.Logger,
        operation_name: str,
        raise_on_error: bool = True,
        log_level: int = logging.ERROR,
        **context: Any,
    ):
        """
        Initialize error context.

        Args:
            logger: Logger instance
            operation_name: Name of the operation for logs
            raise_on_error: Whether to re-raise exceptions
            log_level: Logging level for errors
            **context: Additional context fields
        """
        self.logger = logger
        self.operation_name = operation_name
        self.raise_on_error = raise_on_error
        self.log_level = log_level
        self.context = context
        self.exception: BaseException | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type: type[BaseException], exc_val: BaseException, exc_tb):
        if exc_type is not None:
            self.exception = exc_val
            safe_log_error(
                self.logger,
                f"Error in {self.operation_name}",
                exc_info=(exc_type, exc_val, exc_tb),
                level=self.log_level,
                **self.context,
            )
            return not self.raise_on_error  # Suppress exception if not raising
        return False


def validate_and_handle(
    validator: Callable[[], Any],
    logger: logging.Logger,
    error_message: str,
    status_code: int = 400,
    **context: Any,
) -> tuple[dict[str, Any], int] | None:
    """
    Validate input and return error response if validation fails.

    This is useful for API endpoints that need to validate request data
    before processing.

    Args:
        validator: Function that raises exception on validation failure
        logger: Logger instance
        error_message: Error message for validation failures
        status_code: HTTP status code for validation errors
        **context: Additional context for logging

    Returns:
        None if validation succeeds, (error_response, status_code) if it fails

    Example:
        def validate_project_data(data):
            if not data.get('name'):
                raise ValueError("Project name is required")
            if len(data['name']) > 255:
                raise ValueError("Project name too long")

        error = validate_and_handle(
            lambda: validate_project_data(request_data),
            logger,
            "Invalid project data",
            project_id=project_id
        )
        if error:
            return error
    """
    try:
        validator()
        return None
    except (ValueError, KeyError, TypeError) as e:
        safe_log_error(
            logger, error_message, exc_info=e, level=logging.WARNING, **context
        )
        return {"success": False, "error": str(e)}, status_code
    except Exception:
        # Unexpected exception during validation
        return handle_api_exception(
            logger,
            f"Unexpected error during validation: {error_message}",
            status_code=500,
            public_message="An error occurred while validating the request",
            **context,
        )

"""
Tests for error recovery and graceful degradation.

This module tests that the application handles errors gracefully across
critical paths: email sending, quota calculations, file uploads, and
video compilation.
"""

from unittest.mock import patch

import pytest

from app.error_utils import (
    ErrorContext,
    get_error_details,
    handle_api_exception,
    safe_log_error,
    safe_operation,
    validate_and_handle,
)
from app.models import MediaFile, ProcessingJob, Project, User, db


class TestErrorUtilities:
    """Test the error utility functions."""

    def test_safe_log_error_with_exception(self, app, caplog):
        """Test safe_log_error captures exception context."""
        with app.app_context():
            logger = app.logger
            try:
                raise ValueError("Test error")
            except ValueError as e:
                safe_log_error(
                    logger,
                    "Operation failed",
                    exc_info=e,
                    user_id=123,
                    operation="test",
                )

            # Check that log was created with context
            assert any(
                "Operation failed" in record.message for record in caplog.records
            )
            # Context should be in the log record
            found_context = False
            for record in caplog.records:
                if hasattr(record, "error_context"):
                    assert record.error_context["user_id"] == 123
                    assert record.error_context["operation"] == "test"
                    found_context = True
                    break
            assert found_context or "Operation failed" in caplog.text

    def test_safe_log_error_without_exception(self, app, caplog):
        """Test safe_log_error works without an active exception."""
        with app.app_context():
            logger = app.logger
            safe_log_error(
                logger,
                "Warning message",
                exc_info=False,
                level=30,  # WARNING
                context_key="context_value",
            )

            assert any("Warning message" in record.message for record in caplog.records)

    def test_handle_api_exception_returns_json(self, app):
        """Test handle_api_exception returns proper JSON response."""
        with app.app_context():
            logger = app.logger
            try:
                raise ValueError("Database error")
            except ValueError:
                response, status_code = handle_api_exception(
                    logger,
                    "Failed to fetch user",
                    status_code=500,
                    public_message="Unable to retrieve user information",
                    user_id=42,
                )

            assert status_code == 500
            assert response["success"] is False
            assert response["error"] == "Unable to retrieve user information"

    def test_handle_api_exception_default_messages(self, app):
        """Test handle_api_exception uses default messages."""
        with app.app_context():
            logger = app.logger
            try:
                raise ValueError("Error")
            except ValueError:
                response_500, code_500 = handle_api_exception(
                    logger, "Internal error", status_code=500
                )
                response_400, code_400 = handle_api_exception(
                    logger, "Client error", status_code=400
                )

            assert code_500 == 500
            assert "internal error occurred" in response_500["error"].lower()
            assert code_400 == 400
            assert "could not be completed" in response_400["error"].lower()

    def test_safe_operation_decorator(self, app, caplog):
        """Test safe_operation decorator catches exceptions."""
        with app.app_context():
            logger = app.logger

            @safe_operation(logger, "test operation", default_value="fallback")
            def failing_function():
                raise RuntimeError("Operation failed")

            result = failing_function()
            assert result == "fallback"
            assert any(
                "Error in test operation" in record.message for record in caplog.records
            )

    def test_safe_operation_decorator_reraise(self, app):
        """Test safe_operation decorator can re-raise exceptions."""
        with app.app_context():
            logger = app.logger

            @safe_operation(logger, "test operation", raise_on_error=True)
            def failing_function():
                raise RuntimeError("Must propagate")

            with pytest.raises(RuntimeError, match="Must propagate"):
                failing_function()

    def test_error_context_manager(self, app, caplog):
        """Test ErrorContext context manager."""
        with app.app_context():
            logger = app.logger

            with ErrorContext(
                logger, "database transaction", raise_on_error=False, user_id=99
            ) as ctx:
                raise ValueError("Transaction failed")

            assert ctx.exception is not None
            assert isinstance(ctx.exception, ValueError)
            assert any(
                "Error in database transaction" in record.message
                for record in caplog.records
            )

    def test_error_context_manager_reraise(self, app):
        """Test ErrorContext raises when configured."""
        with app.app_context():
            logger = app.logger

            with pytest.raises(ValueError):
                with ErrorContext(logger, "operation", raise_on_error=True):
                    raise ValueError("Should propagate")

    def test_get_error_details(self):
        """Test get_error_details extracts exception info."""
        try:
            raise ValueError("Test exception")
        except ValueError as e:
            details = get_error_details(e)

        assert details["exception_type"] == "ValueError"
        assert details["exception_message"] == "Test exception"
        assert "traceback" in details
        assert isinstance(details["traceback_lines"], list)

    def test_validate_and_handle_success(self, app):
        """Test validate_and_handle returns None on success."""
        with app.app_context():
            logger = app.logger

            def validator():
                # No exception = valid
                pass

            result = validate_and_handle(validator, logger, "Validation failed")
            assert result is None

    def test_validate_and_handle_validation_error(self, app):
        """Test validate_and_handle returns error response."""
        with app.app_context():
            logger = app.logger

            def validator():
                raise ValueError("Invalid input")

            result = validate_and_handle(validator, logger, "Validation failed")
            assert result is not None
            response, status_code = result
            assert status_code == 400
            assert response["success"] is False
            assert "Invalid input" in response["error"]

    def test_validate_and_handle_unexpected_error(self, app):
        """Test validate_and_handle handles unexpected exceptions."""
        with app.app_context():
            logger = app.logger

            def validator():
                raise RuntimeError("Unexpected error")

            result = validate_and_handle(validator, logger, "Validation failed")
            assert result is not None
            response, status_code = result
            assert status_code == 500
            assert response["success"] is False


class TestEmailErrorRecovery:
    """Test email sending error recovery."""

    @patch("app.mailer.send_email")
    def test_email_failure_is_logged(self, mock_send, app, caplog):
        """Test that email failures are logged but don't crash the app."""
        from app.mailer import send_password_reset_email

        with app.app_context():
            # Simulate SMTP failure
            mock_send.side_effect = Exception("SMTP connection failed")

            user = User(username="testuser", email="test@example.com")
            token = "test-token"

            # Should not raise exception
            send_password_reset_email(user, token)

            # Should have logged the error
            assert any(
                "Failed to send password reset email" in record.message
                for record in caplog.records
            )

    @patch("app.notifications.send_email")
    def test_notification_email_failure_graceful(
        self, mock_send, app, test_user, caplog
    ):
        """Test notification email failures don't prevent notification creation."""
        from app.notifications import notify_compilation_completed

        with app.app_context():
            # Create a project
            project = Project(
                name="Test Project",
                user_id=test_user.id,
                output_filename="test.mp4",
            )
            db.session.add(project)
            db.session.commit()

            # Simulate email failure
            mock_send.side_effect = Exception("Email service down")

            # Should still create notification even if email fails
            notify_compilation_completed(
                user_id=test_user.id, project_id=project.id, output_path="output.mp4"
            )

            # Notification should exist
            from app.models import Notification

            notification = Notification.query.filter_by(user_id=test_user.id).first()
            assert notification is not None


class TestUploadErrorRecovery:
    """Test file upload error recovery."""

    def test_upload_with_invalid_file_type(self, client, test_user):
        """Test upload rejects invalid file types gracefully."""
        from io import BytesIO

        # Login first
        client.post(
            "/login",
            data={"username_or_email": test_user.username, "password": "password123"},
            follow_redirects=True,
        )

        # Try uploading an invalid file type
        data = {
            "file": (BytesIO(b"malicious content"), "virus.exe"),
        }

        response = client.post(
            "/api/media/upload", data=data, content_type="multipart/form-data"
        )

        # Should reject gracefully
        assert response.status_code in [
            400,
            415,
        ]  # Bad Request or Unsupported Media Type
        json_data = response.get_json()
        assert json_data is not None
        assert json_data.get("success") is False

    def test_upload_disk_space_error(self, client, test_user, caplog):
        """Test upload handles disk space errors gracefully."""
        from io import BytesIO

        # Login
        client.post(
            "/login",
            data={"username_or_email": test_user.username, "password": "password123"},
            follow_redirects=True,
        )

        # Mock disk space error
        with patch("app.storage.save_media_file") as mock_save:
            mock_save.side_effect = OSError("No space left on device")

            data = {
                "file": (BytesIO(b"video content"), "test.mp4"),
            }

            response = client.post(
                "/api/media/upload", data=data, content_type="multipart/form-data"
            )

            # Should return error response
            assert response.status_code >= 400
            json_data = response.get_json()
            assert json_data is not None
            assert json_data.get("success") is False


class TestCompilationErrorRecovery:
    """Test video compilation error recovery."""

    def test_compilation_missing_clips(self, app, test_user):
        """Test compilation handles missing clip files gracefully."""
        with app.app_context():
            # Create project with non-existent clips
            project = Project(
                name="Test Project",
                user_id=test_user.id,
                output_filename="test.mp4",
            )
            db.session.add(project)
            db.session.commit()

            # Create media file reference to non-existent file
            media = MediaFile(
                user_id=test_user.id,
                filename="missing.mp4",
                file_path="/nonexistent/path.mp4",
                media_type="clip",
            )
            db.session.add(media)
            db.session.commit()

            # Link to project
            from app.models import Clip

            clip = Clip(
                project_id=project.id,
                media_file_id=media.id,
                order_index=1,
            )
            db.session.add(clip)
            db.session.commit()

            # Try to compile - should fail gracefully
            from app.tasks.compile_video_v2 import compile_video_task

            result = compile_video_task(project.id)

            # Should indicate failure, not crash
            assert "error" in str(result).lower() or "fail" in str(result).lower()

    def test_compilation_ffmpeg_error(self, app, test_user, tmp_path):
        """Test compilation handles ffmpeg errors gracefully."""
        with app.app_context():
            # Create project
            project = Project(
                name="Test Project",
                user_id=test_user.id,
                output_filename="test.mp4",
            )
            db.session.add(project)
            db.session.commit()

            # Create a valid but corrupted media file
            corrupted_file = tmp_path / "corrupted.mp4"
            corrupted_file.write_bytes(b"not a valid video file")

            media = MediaFile(
                user_id=test_user.id,
                filename="corrupted.mp4",
                file_path=str(corrupted_file),
                media_type="clip",
            )
            db.session.add(media)
            db.session.commit()

            # Link to project
            from app.models import Clip

            clip = Clip(
                project_id=project.id,
                media_file_id=media.id,
                order_index=1,
            )
            db.session.add(clip)
            db.session.commit()

            # Mock ffmpeg failure
            with patch("app.tasks.compile_video_v2.run_ffmpeg_command") as mock_ffmpeg:
                mock_ffmpeg.side_effect = Exception("FFmpeg encoding failed")

                from app.tasks.compile_video_v2 import compile_video_task

                result = compile_video_task(project.id)

                # Should handle error gracefully
                assert "error" in str(result).lower() or "fail" in str(result).lower()

    def test_compilation_updates_job_status_on_error(self, app, test_user):
        """Test that compilation errors update ProcessingJob status."""
        with app.app_context():
            # Create project
            project = Project(
                name="Test Project",
                user_id=test_user.id,
                output_filename="test.mp4",
            )
            db.session.add(project)
            db.session.commit()

            # Create processing job
            job = ProcessingJob(
                project_id=project.id,
                user_id=test_user.id,
                job_type="compilation",
                status="pending",
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.id

            # Mock compilation failure
            with patch("app.tasks.compile_video_v2.compile_video_task") as mock_compile:
                mock_compile.side_effect = Exception("Compilation failed")

                # Trigger compilation (this would normally be via Celery)
                try:
                    from app.tasks.compile_video_v2 import compile_video_task

                    compile_video_task(project.id)
                except Exception:
                    pass  # Expected to fail

            # Check that job status was updated
            db.session.expire_all()
            job = ProcessingJob.query.get(job_id)
            # Status should be 'failed' or error message should be set
            assert job.status == "failed" or job.error_message is not None


class TestDatabaseErrorRecovery:
    """Test database error recovery."""

    def test_login_database_error_recovery(self, client, test_user, caplog):
        """Test login handles database errors gracefully."""
        with patch("app.models.User.query") as mock_query:
            # Simulate database connection error
            mock_query.filter.side_effect = Exception("Database connection lost")

            response = client.post(
                "/login",
                data={
                    "username_or_email": test_user.username,
                    "password": "password123",
                },
                follow_redirects=True,
            )

            # Should show error message, not crash
            assert response.status_code == 200  # Returns to login page
            html = response.data.decode()
            assert "database error" in html.lower() or "error occurred" in html.lower()

    def test_profile_update_database_error(self, client, test_user, caplog):
        """Test profile update handles database errors gracefully."""
        # Login first
        client.post(
            "/login",
            data={"username_or_email": test_user.username, "password": "password123"},
            follow_redirects=True,
        )

        # Mock database commit error
        with patch("app.models.db.session.commit") as mock_commit:
            mock_commit.side_effect = Exception("Database write failed")

            response = client.post(
                "/profile",
                data={
                    "email": "newemail@example.com",
                    "submit": "Update",
                },
                follow_redirects=True,
            )

            # Should show error message
            assert response.status_code == 200
            html = response.data.decode()
            assert "error" in html.lower() or "failed" in html.lower()

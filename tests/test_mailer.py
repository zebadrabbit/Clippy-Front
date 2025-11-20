"""Tests for email/mailer functionality."""
import smtplib
from unittest.mock import MagicMock, patch

from app import mailer


class TestMailerConfiguration:
    """Test mailer configuration detection."""

    def test_is_configured_returns_true_when_all_settings_present(self, app):
        """Should return True when all SMTP settings are configured."""
        with app.app_context():
            app.config["SMTP_HOST"] = "smtp.example.com"
            app.config["SMTP_PORT"] = 587
            app.config["SMTP_USERNAME"] = "user@example.com"
            app.config["SMTP_PASSWORD"] = "secret"
            assert mailer.is_configured() is True

    def test_is_configured_returns_false_when_host_missing(self, app):
        """Should return False when SMTP_HOST is not set."""
        with app.app_context():
            app.config["SMTP_HOST"] = None
            app.config["SMTP_PORT"] = 587
            app.config["SMTP_USERNAME"] = "user@example.com"
            app.config["SMTP_PASSWORD"] = "secret"
            assert mailer.is_configured() is False

    def test_is_configured_returns_false_when_port_missing(self, app):
        """Should return False when SMTP_PORT is not set."""
        with app.app_context():
            app.config["SMTP_HOST"] = "smtp.example.com"
            app.config["SMTP_PORT"] = None
            app.config["SMTP_USERNAME"] = "user@example.com"
            app.config["SMTP_PASSWORD"] = "secret"
            assert mailer.is_configured() is False

    def test_is_configured_returns_false_when_username_missing(self, app):
        """Should return False when SMTP_USERNAME is not set."""
        with app.app_context():
            app.config["SMTP_HOST"] = "smtp.example.com"
            app.config["SMTP_PORT"] = 587
            app.config["SMTP_USERNAME"] = None
            app.config["SMTP_PASSWORD"] = "secret"
            assert mailer.is_configured() is False

    def test_is_configured_returns_false_when_password_missing(self, app):
        """Should return False when SMTP_PASSWORD is not set."""
        with app.app_context():
            app.config["SMTP_HOST"] = "smtp.example.com"
            app.config["SMTP_PORT"] = 587
            app.config["SMTP_USERNAME"] = "user@example.com"
            app.config["SMTP_PASSWORD"] = None
            assert mailer.is_configured() is False


class TestSendEmail:
    """Test email sending functionality."""

    def _setup_smtp_config(self, app):
        """Helper to set up valid SMTP configuration."""
        app.config["SMTP_HOST"] = "smtp.example.com"
        app.config["SMTP_PORT"] = 587
        app.config["SMTP_USE_TLS"] = True
        app.config["SMTP_USE_SSL"] = False
        app.config["SMTP_USERNAME"] = "user@example.com"
        app.config["SMTP_PASSWORD"] = "secret"
        app.config["EMAIL_FROM_ADDRESS"] = "noreply@example.com"

    @patch("app.mailer.smtplib.SMTP")
    def test_send_email_with_tls_success(self, mock_smtp, app):
        """Should successfully send email using SMTP with STARTTLS."""
        with app.app_context():
            self._setup_smtp_config(app)
            mock_smtp_instance = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_smtp_instance

            result = mailer.send_email(
                to_address="recipient@example.com",
                subject="Test Subject",
                text="Test body",
            )

            assert result is True
            mock_smtp.assert_called_once_with("smtp.example.com", 587)
            mock_smtp_instance.starttls.assert_called_once()
            mock_smtp_instance.login.assert_called_once_with(
                "user@example.com", "secret"
            )
            mock_smtp_instance.send_message.assert_called_once()

    @patch("app.mailer.smtplib.SMTP_SSL")
    def test_send_email_with_ssl_success(self, mock_smtp_ssl, app):
        """Should successfully send email using SMTP_SSL."""
        with app.app_context():
            self._setup_smtp_config(app)
            app.config["SMTP_USE_TLS"] = False
            app.config["SMTP_USE_SSL"] = True
            app.config["SMTP_PORT"] = 465
            mock_smtp_instance = MagicMock()
            mock_smtp_ssl.return_value.__enter__.return_value = mock_smtp_instance

            result = mailer.send_email(
                to_address="recipient@example.com",
                subject="Test Subject",
                text="Test body",
            )

            assert result is True
            mock_smtp_ssl.assert_called_once_with("smtp.example.com", 465)
            mock_smtp_instance.login.assert_called_once_with(
                "user@example.com", "secret"
            )
            mock_smtp_instance.send_message.assert_called_once()

    @patch("app.mailer.smtplib.SMTP")
    def test_send_email_with_html_content(self, mock_smtp, app):
        """Should send email with both HTML and text content."""
        with app.app_context():
            self._setup_smtp_config(app)
            mock_smtp_instance = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_smtp_instance

            result = mailer.send_email(
                to_address="recipient@example.com",
                subject="HTML Email",
                html="<p>HTML content</p>",
                text="Text content",
            )

            assert result is True
            mock_smtp_instance.send_message.assert_called_once()
            # Verify the message has both text and HTML
            sent_msg = mock_smtp_instance.send_message.call_args[0][0]
            assert sent_msg["Subject"] == "HTML Email"
            assert sent_msg["To"] == "recipient@example.com"

    @patch("app.mailer.smtplib.SMTP")
    def test_send_email_html_only_generates_fallback_text(self, mock_smtp, app):
        """Should generate fallback text when only HTML is provided."""
        with app.app_context():
            self._setup_smtp_config(app)
            mock_smtp_instance = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_smtp_instance

            result = mailer.send_email(
                to_address="recipient@example.com",
                subject="HTML Only",
                html="<p>HTML content</p>",
            )

            assert result is True
            mock_smtp_instance.send_message.assert_called_once()

    @patch("app.mailer.smtplib.SMTP")
    def test_send_email_custom_from_address(self, mock_smtp, app):
        """Should use custom from_address when provided."""
        with app.app_context():
            self._setup_smtp_config(app)
            mock_smtp_instance = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_smtp_instance

            result = mailer.send_email(
                to_address="recipient@example.com",
                subject="Custom From",
                text="Body",
                from_address="custom@example.com",
            )

            assert result is True
            sent_msg = mock_smtp_instance.send_message.call_args[0][0]
            assert sent_msg["From"] == "custom@example.com"

    def test_send_email_returns_false_when_not_configured(self, app):
        """Should return False when SMTP is not configured."""
        with app.app_context():
            app.config["SMTP_HOST"] = None
            result = mailer.send_email(
                to_address="recipient@example.com",
                subject="Test",
                text="Body",
            )
            assert result is False

    @patch("app.mailer.smtplib.SMTP")
    def test_send_email_returns_false_on_smtp_exception(self, mock_smtp, app):
        """Should return False and log error when SMTP raises exception."""
        with app.app_context():
            self._setup_smtp_config(app)
            mock_smtp.return_value.__enter__.side_effect = smtplib.SMTPException(
                "Connection failed"
            )

            result = mailer.send_email(
                to_address="recipient@example.com",
                subject="Test",
                text="Body",
            )

            assert result is False

    @patch("app.mailer.smtplib.SMTP")
    def test_send_email_handles_login_failure(self, mock_smtp, app):
        """Should return False when SMTP login fails."""
        with app.app_context():
            self._setup_smtp_config(app)
            mock_smtp_instance = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_smtp_instance
            mock_smtp_instance.login.side_effect = smtplib.SMTPAuthenticationError(
                535, b"Authentication failed"
            )

            result = mailer.send_email(
                to_address="recipient@example.com",
                subject="Test",
                text="Body",
            )

            assert result is False

    @patch("app.mailer.smtplib.SMTP")
    def test_send_email_without_tls_or_ssl(self, mock_smtp, app):
        """Should send email without TLS/SSL when both are disabled."""
        with app.app_context():
            self._setup_smtp_config(app)
            app.config["SMTP_USE_TLS"] = False
            app.config["SMTP_USE_SSL"] = False
            mock_smtp_instance = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_smtp_instance

            result = mailer.send_email(
                to_address="recipient@example.com",
                subject="No TLS",
                text="Body",
            )

            assert result is True
            mock_smtp_instance.starttls.assert_not_called()


class TestVerificationEmail:
    """Test verification email sending."""

    @patch("app.mailer.send_email")
    def test_send_verification_email_calls_send_email(self, mock_send_email, app):
        """Should call send_email with correct verification template."""
        with app.app_context():
            mock_send_email.return_value = True

            result = mailer.send_verification_email(
                to_address="user@example.com",
                username="testuser",
                verify_url="https://example.com/verify?token=abc123",
            )

            assert result is True
            mock_send_email.assert_called_once()
            args, kwargs = mock_send_email.call_args
            assert args[0] == "user@example.com"
            assert args[1] == "Verify your email address"
            assert "testuser" in kwargs["html"]
            assert "https://example.com/verify?token=abc123" in kwargs["html"]
            assert "testuser" in kwargs["text"]
            assert "https://example.com/verify?token=abc123" in kwargs["text"]

    @patch("app.mailer.send_email")
    def test_send_verification_email_returns_false_on_failure(
        self, mock_send_email, app
    ):
        """Should return False when underlying send_email fails."""
        with app.app_context():
            mock_send_email.return_value = False

            result = mailer.send_verification_email(
                to_address="user@example.com",
                username="testuser",
                verify_url="https://example.com/verify",
            )

            assert result is False


class TestGetHelper:
    """Test the _get configuration helper."""

    def test_get_returns_config_value_when_present(self, app):
        """Should return config value when key exists."""
        with app.app_context():
            app.config["TEST_KEY"] = "test_value"
            result = mailer._get("TEST_KEY")
            assert result == "test_value"

    def test_get_returns_default_when_key_missing(self, app):
        """Should return default value when key doesn't exist."""
        with app.app_context():
            result = mailer._get("NONEXISTENT_KEY", "default")
            assert result == "default"

    def test_get_returns_none_when_no_default_and_key_missing(self, app):
        """Should return None when key doesn't exist and no default provided."""
        with app.app_context():
            result = mailer._get("NONEXISTENT_KEY")
            assert result is None

"""
Flask application factory and configuration.
"""
from flask import Flask
from flask_cors import CORS

from config.settings import Config


def create_app(config_class=Config):
    """
    Create and configure Flask application.

    Args:
        config_class: Configuration class to use

    Returns:
        Flask: Configured Flask application
    """
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    CORS(app)

    # Register blueprints
    from app.api.routes import api_bp

    app.register_blueprint(api_bp, url_prefix="/api")

    return app

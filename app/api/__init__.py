from flask import Blueprint

# Single blueprint instance for API routes. Other modules import this
# blueprint and register routes on it.
api_bp = Blueprint("api", __name__)

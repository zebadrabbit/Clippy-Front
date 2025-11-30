"""
Analytics blueprint for clip and engagement insights.
"""
from flask import Blueprint

analytics_bp = Blueprint("analytics", __name__, url_prefix="/analytics")

from app.analytics import routes  # noqa: E402, F401

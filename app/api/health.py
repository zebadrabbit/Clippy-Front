"""Health endpoints for the API blueprint.

Mounts served by this module:

- GET /health
    - Purpose: simple liveness/health-check used by load balancers and orchestration
        to verify the API process is running.
    - Parameters: none

This module keeps a very small surface area so it can be imported safely by
infrastructure checks without pulling in heavy application code.
"""

from flask import jsonify

from app.api import api_bp


@api_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint.

    Returns a JSON payload with a short status message. No auth required.
    """
    return jsonify({"status": "healthy", "message": "Clippy API is running"})

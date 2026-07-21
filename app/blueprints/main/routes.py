"""
Main blueprint routes.

The application root redirects to the dashboard once it exists.
The /health endpoint is kept here as it belongs to no specific module.
"""
import logging

from flask import current_app, redirect, url_for

from . import main_bp

logger = logging.getLogger(__name__)


@main_bp.route("/", methods=["GET"])
def index():
    """Redirect root to the dashboard."""
    return redirect(url_for("dashboard.index"))


@main_bp.route("/health", methods=["GET"])
def health():
    """
    Lightweight health-check endpoint.
    Used by Docker Compose / load balancers – no DB query.
    """
    return {"status": "ok", "version": current_app.config["APP_VERSION"]}, 200

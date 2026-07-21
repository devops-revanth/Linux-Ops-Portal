"""
Main blueprint routes.

Foundation phase – only the landing / coming-soon page is wired up.
Additional routes (dashboard, inventory, patching …) will be added in
subsequent modules as separate blueprints.
"""
import logging

from flask import current_app, render_template

from . import main_bp

logger = logging.getLogger(__name__)


@main_bp.route("/", methods=["GET"])
def index():
    """Application root – renders the portal landing page."""
    current_app.logger.debug("Rendering index page")
    return render_template(
        "main/index.html",
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


@main_bp.route("/health", methods=["GET"])
def health():
    """
    Lightweight health-check endpoint.

    Used by Docker Compose / load balancers to verify the app is alive.
    Returns HTTP 200 with a plain-text body – no DB query needed here.
    """
    return {"status": "ok", "version": current_app.config["APP_VERSION"]}, 200

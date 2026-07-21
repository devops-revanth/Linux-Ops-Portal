"""Dashboard blueprint routes."""
import logging

from flask import current_app, render_template

from . import dashboard_bp
from .queries import get_dashboard_stats

logger = logging.getLogger(__name__)


@dashboard_bp.route("/dashboard", methods=["GET"])
def index():
    """Main dashboard view – aggregated server and patching statistics."""
    current_app.logger.debug("Rendering dashboard")
    stats = get_dashboard_stats()
    return render_template(
        "dashboard/index.html",
        stats=stats,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )

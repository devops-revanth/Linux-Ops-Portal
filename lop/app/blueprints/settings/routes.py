"""Settings blueprint routes."""
import logging

from flask import current_app, render_template

from . import settings_bp
from ...models.environment import Environment
from ...models.location import Location

logger = logging.getLogger(__name__)


@settings_bp.route("/settings", methods=["GET"])
def index():
    """Settings overview – manage locations and environments."""
    locations = (
        Location.query
        .filter_by(is_active=True)
        .order_by(Location.name)
        .all()
    )
    environments = (
        Environment.query
        .filter_by(is_active=True)
        .order_by(Environment.id)
        .all()
    )
    return render_template(
        "settings/index.html",
        locations=locations,
        environments=environments,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )

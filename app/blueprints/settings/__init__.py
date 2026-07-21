"""Settings blueprint – registered at /settings."""
from flask import Blueprint
from flask_login import login_required

settings_bp = Blueprint("settings", __name__, template_folder="../../templates")

# Protect every route in this blueprint
settings_bp.before_request(login_required(lambda: None))

from . import routes  # noqa: E402, F401

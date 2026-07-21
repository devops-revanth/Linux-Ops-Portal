"""Dashboard blueprint – registered at /dashboard."""
from flask import Blueprint
from flask_login import login_required

dashboard_bp = Blueprint("dashboard", __name__, template_folder="../../templates")

# Protect every route in this blueprint
dashboard_bp.before_request(login_required(lambda: None))

from . import routes  # noqa: E402, F401

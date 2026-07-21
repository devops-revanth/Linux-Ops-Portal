"""Reports blueprint – registered at /reports."""
from flask import Blueprint
from flask_login import login_required

reports_bp = Blueprint("reports", __name__, template_folder="../../templates")

# Protect every route in this blueprint
reports_bp.before_request(login_required(lambda: None))

from . import routes  # noqa: E402, F401

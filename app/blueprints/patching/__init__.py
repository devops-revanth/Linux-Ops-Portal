"""Patching blueprint – registered at /patching."""
from flask import Blueprint
from flask_login import login_required

patching_bp = Blueprint("patching", __name__, template_folder="../../templates")

# Protect every route in this blueprint
patching_bp.before_request(login_required(lambda: None))

from . import routes  # noqa: E402, F401

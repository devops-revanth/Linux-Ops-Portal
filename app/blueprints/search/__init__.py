"""Search blueprint – registered at /search."""
from flask import Blueprint
from flask_login import login_required

search_bp = Blueprint("search", __name__, template_folder="../../templates")

# Protect every route in this blueprint
search_bp.before_request(login_required(lambda: None))

from . import routes  # noqa: E402, F401

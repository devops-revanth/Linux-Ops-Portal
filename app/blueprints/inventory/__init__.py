"""Inventory blueprint – registered at /inventory."""
from flask import Blueprint
from flask_login import login_required

inventory_bp = Blueprint("inventory", __name__, template_folder="../../templates")

# Protect every route in this blueprint
inventory_bp.before_request(login_required(lambda: None))

from . import routes  # noqa: E402, F401

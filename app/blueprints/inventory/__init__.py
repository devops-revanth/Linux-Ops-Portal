"""Inventory blueprint – registered at /inventory."""
from flask import Blueprint

inventory_bp = Blueprint("inventory", __name__, template_folder="../../templates")

from . import routes  # noqa: E402, F401

"""Patching blueprint – registered at /patching."""
from flask import Blueprint

patching_bp = Blueprint("patching", __name__, template_folder="../../templates")

from . import routes  # noqa: E402, F401

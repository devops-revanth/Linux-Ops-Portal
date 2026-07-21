"""Main blueprint – registered at the application root (/)."""
from flask import Blueprint

main_bp = Blueprint("main", __name__, template_folder="../../templates")

from . import routes  # noqa: E402, F401  (import routes to register them)

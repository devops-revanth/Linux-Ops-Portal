"""Reports blueprint – registered at /reports."""
from flask import Blueprint

reports_bp = Blueprint("reports", __name__, template_folder="../../templates")

from . import routes  # noqa: E402, F401

"""Ansible Operations workspace blueprint — Phase 3."""
from flask import Blueprint

ops_bp = Blueprint("ops", __name__, template_folder="../../templates")

from . import routes  # noqa: F401, E402  (must be after Blueprint creation)

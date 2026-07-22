"""Packages blueprint."""
from flask import Blueprint
from flask_login import login_required

packages_bp = Blueprint("packages", __name__)
packages_bp.before_request(login_required(lambda: None))

from . import routes  # noqa: E402, F401

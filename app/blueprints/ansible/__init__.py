"""Ansible blueprint package."""
from flask import Blueprint

ansible_bp = Blueprint("ansible", __name__)

from . import routes  # noqa: E402, F401

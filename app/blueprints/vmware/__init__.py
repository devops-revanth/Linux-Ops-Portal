"""VMware vCenter blueprint."""
from flask import Blueprint

vmware_bp = Blueprint("vmware", __name__)

from . import routes  # noqa: E402, F401

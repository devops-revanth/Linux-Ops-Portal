"""Inventory blueprint routes."""
import logging

from flask import current_app, render_template, request

from . import inventory_bp
from .queries import DEFAULT_ORDER, DEFAULT_SORT, InventoryFilters, get_inventory_page

logger = logging.getLogger(__name__)


@inventory_bp.route("/inventory", methods=["GET"])
def index():
    """Server inventory list with search, filter, sort, and pagination."""
    per_page = current_app.config.get("ITEMS_PER_PAGE", 25)

    # ── Parse query-string parameters ────────────────────────────────
    search      = request.args.get("q", "").strip()
    location_id = request.args.get("location_id", type=int)
    env_id      = request.args.get("env_id",      type=int)
    status      = request.args.get("status",      "").strip()
    sort        = request.args.get("sort",  DEFAULT_SORT)
    order       = request.args.get("order", DEFAULT_ORDER)
    page        = request.args.get("page",  1, type=int)

    # Guard against invalid values
    if order not in ("asc", "desc"):
        order = DEFAULT_ORDER
    if page < 1:
        page = 1

    filters = InventoryFilters(
        search=search,
        location_id=location_id,
        env_id=env_id,
        status=status,
        sort=sort,
        order=order,
    )

    inventory = get_inventory_page(filters, page=page, per_page=per_page)

    return render_template(
        "inventory/index.html",
        inventory=inventory,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )

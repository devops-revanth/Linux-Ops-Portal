"""Packages blueprint routes."""
import logging

from flask import current_app, render_template, request

from . import packages_bp
from .queries import (
    DEFAULT_ORDER,
    DEFAULT_SORT,
    VALID_SORTS,
    PackagesFilters,
    get_fleet_summary,
    get_servers_package_summary,
)

logger = logging.getLogger(__name__)

VALID_PER_PAGE   = {10, 20, 25, 50, 100}
PER_PAGE_OPTIONS = [10, 20, 25, 50, 100]


@packages_bp.route("/packages", methods=["GET"])
def index():
    """Fleet package management dashboard."""
    per_page_raw = request.args.get("per_page", type=int)
    per_page = (
        per_page_raw
        if per_page_raw in VALID_PER_PAGE
        else current_app.config.get("ITEMS_PER_PAGE", 25)
    )

    page  = max(1, request.args.get("page",  1, type=int))
    q     = request.args.get("q",     "").strip()
    sort  = request.args.get("sort",  DEFAULT_SORT)
    order = request.args.get("order", DEFAULT_ORDER)

    if sort  not in VALID_SORTS:    sort  = DEFAULT_SORT
    if order not in ("asc", "desc"): order = DEFAULT_ORDER

    filters = PackagesFilters(search=q, sort=sort, order=order)
    fleet   = get_fleet_summary()
    servers = get_servers_package_summary(filters, page=page, per_page=per_page)

    return render_template(
        "packages/index.html",
        fleet=fleet,
        servers=servers,
        filters=filters,
        per_page=per_page,
        per_page_options=PER_PAGE_OPTIONS,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )

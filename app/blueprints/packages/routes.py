"""Packages blueprint routes."""
import logging

from flask import current_app, render_template, request

from . import packages_bp
from .queries import (
    DEFAULT_ORDER,
    DEFAULT_SORT,
    PackagesFilters,
    get_installed_page,
    get_recently_installed_page,
    get_updates_page,
)

logger = logging.getLogger(__name__)

VALID_TABS     = {"installed", "updates", "recently-installed"}
VALID_PER_PAGE = {10, 20, 25, 50, 100}
PER_PAGE_OPTIONS = [10, 20, 25, 50, 100]


@packages_bp.route("/packages", methods=["GET"])
def index():
    """Package inventory — Installed / Available Updates / Recently Installed."""
    tab = request.args.get("tab", "installed")
    if tab not in VALID_TABS:
        tab = "installed"

    per_page_raw = request.args.get("per_page", type=int)
    per_page = (
        per_page_raw
        if per_page_raw in VALID_PER_PAGE
        else current_app.config.get("ITEMS_PER_PAGE", 25)
    )

    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1

    search = request.args.get("q", "").strip()
    sort   = request.args.get("sort",  DEFAULT_SORT)
    order  = request.args.get("order", DEFAULT_ORDER)
    if order not in ("asc", "desc"):
        order = DEFAULT_ORDER

    filters = PackagesFilters(search=search, sort=sort, order=order)

    installed = updates = recently = None

    if tab == "installed":
        installed = get_installed_page(filters, page=page, per_page=per_page)
    elif tab == "updates":
        updates = get_updates_page(filters, page=page, per_page=per_page)
    else:
        recently = get_recently_installed_page(filters, page=page, per_page=per_page)

    return render_template(
        "packages/index.html",
        tab=tab,
        installed=installed,
        updates=updates,
        recently=recently,
        filters=filters,
        page=page,
        per_page=per_page,
        per_page_options=PER_PAGE_OPTIONS,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )

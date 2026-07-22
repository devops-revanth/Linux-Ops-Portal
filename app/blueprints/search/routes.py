"""Search blueprint routes."""
import logging

from flask import current_app, render_template, request

from . import search_bp
from .queries import DEFAULT_ORDER, DEFAULT_SORT, SearchFilters, get_search_page

logger = logging.getLogger(__name__)


@search_bp.route("/search", methods=["GET"])
def index():
    """Global search — filterable, sortable, paginated."""
    per_page = current_app.config.get("ITEMS_PER_PAGE", 25)

    search = request.args.get("q",     "").strip()
    sort   = request.args.get("sort",  DEFAULT_SORT)
    order  = request.args.get("order", DEFAULT_ORDER)
    page   = request.args.get("page",  1, type=int)

    if order not in ("asc", "desc"):
        order = DEFAULT_ORDER
    if page < 1:
        page = 1

    filters = SearchFilters(search=search, sort=sort, order=order)

    results = get_search_page(filters, page=page, per_page=per_page)

    return render_template(
        "search/index.html",
        results=results,
        search_type=results.filters.search_type,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )

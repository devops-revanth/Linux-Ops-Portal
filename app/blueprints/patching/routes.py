"""Patching blueprint routes."""
import logging

from flask import current_app, render_template, request

from . import patching_bp
from .queries import DEFAULT_ORDER, DEFAULT_SORT, PatchingFilters, get_patching_page

logger = logging.getLogger(__name__)


@patching_bp.route("/patching", methods=["GET"])
def index():
    """Patch compliance view — filterable, sortable, paginated."""
    per_page = current_app.config.get("ITEMS_PER_PAGE", 25)

    search       = request.args.get("q",            "").strip()
    location_id  = request.args.get("location_id",  type=int)
    env_id       = request.args.get("env_id",       type=int)
    patch_status = request.args.get("patch_status", "").strip()
    sort         = request.args.get("sort",  DEFAULT_SORT)
    order        = request.args.get("order", DEFAULT_ORDER)
    page         = request.args.get("page",  1, type=int)

    if order not in ("asc", "desc"):
        order = DEFAULT_ORDER
    if page < 1:
        page = 1

    filters = PatchingFilters(
        search=search,
        location_id=location_id,
        env_id=env_id,
        patch_status=patch_status,
        sort=sort,
        order=order,
    )

    patching = get_patching_page(filters, page=page, per_page=per_page)

    return render_template(
        "patching/index.html",
        patching=patching,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )

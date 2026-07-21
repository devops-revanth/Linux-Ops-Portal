"""Patching blueprint routes."""
import logging

from flask import current_app, flash, redirect, render_template, request, url_for

from . import patching_bp
from .queries import DEFAULT_ORDER, DEFAULT_SORT, PatchingFilters, get_patching_page
from ...audit import log_action
from ...extensions import db
from ...models.server import Server

logger = logging.getLogger(__name__)

VALID_STATUSES = {"active", "inactive", "maintenance", "decommissioned"}


def _parse_server_ids(raw: list[str]) -> list[int]:
    ids = []
    for v in raw:
        try:
            i = int(v)
            if i > 0:
                ids.append(i)
        except (TypeError, ValueError):
            pass
    return ids


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


# ── Bulk actions ─────────────────────────────────────────────────────────── #

@patching_bp.route("/patching/bulk-active", methods=["POST"])
def bulk_active():
    """Mark selected servers as Active."""
    ids = _parse_server_ids(request.form.getlist("server_ids"))
    if not ids:
        flash("No servers selected.", "warning")
        return redirect(url_for("patching.index"))
    try:
        updated = (
            Server.query.filter(Server.id.in_(ids))
            .update({"status": "active"}, synchronize_session="fetch")
        )
        log_action("patching.bulk_active", target=f"{updated} server(s)")
        db.session.commit()
        flash(f"{updated} server{'s' if updated != 1 else ''} marked as Active.", "success")
        logger.info("Bulk active: %d server(s) — ids=%s", updated, ids)
    except Exception:
        db.session.rollback()
        logger.exception("Bulk active failed for ids=%s", ids)
        flash("An error occurred while updating server status.", "danger")
    return redirect(url_for("patching.index"))


@patching_bp.route("/patching/bulk-maintenance", methods=["POST"])
def bulk_maintenance():
    """Mark selected servers as Maintenance."""
    ids = _parse_server_ids(request.form.getlist("server_ids"))
    if not ids:
        flash("No servers selected.", "warning")
        return redirect(url_for("patching.index"))
    try:
        updated = (
            Server.query.filter(Server.id.in_(ids))
            .update({"status": "maintenance"}, synchronize_session="fetch")
        )
        log_action("patching.bulk_maintenance", target=f"{updated} server(s)")
        db.session.commit()
        flash(f"{updated} server{'s' if updated != 1 else ''} marked as Maintenance.", "success")
        logger.info("Bulk maintenance: %d server(s) — ids=%s", updated, ids)
    except Exception:
        db.session.rollback()
        logger.exception("Bulk maintenance failed for ids=%s", ids)
        flash("An error occurred while updating server status.", "danger")
    return redirect(url_for("patching.index"))

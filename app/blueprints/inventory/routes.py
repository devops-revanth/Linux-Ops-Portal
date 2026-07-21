"""Inventory blueprint routes."""
import logging

from flask import current_app, flash, redirect, render_template, request, url_for

from . import inventory_bp
from .queries import DEFAULT_ORDER, DEFAULT_SORT, InventoryFilters, get_inventory_page
from ...audit import log_action
from ...extensions import db
from ...models.environment import Environment
from ...models.location import Location
from ...models.note import Note
from ...models.owner import Owner
from ...models.server import Server
from ...utils import sort_envs

logger = logging.getLogger(__name__)

VALID_STATUSES = {"active", "inactive", "maintenance", "decommissioned"}


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _parse_server_ids(raw: list[str]) -> list[int]:
    """Parse a list of raw string IDs into positive integers, dropping invalid entries."""
    ids = []
    for v in raw:
        try:
            i = int(v)
            if i > 0:
                ids.append(i)
        except (TypeError, ValueError):
            pass
    return ids


# ── Inventory list ────────────────────────────────────────────────────────── #

@inventory_bp.route("/inventory", methods=["GET"])
def index():
    """Server inventory list with search, filter, sort, and pagination."""
    per_page = current_app.config.get("ITEMS_PER_PAGE", 25)

    search      = request.args.get("q", "").strip()
    location_id = request.args.get("location_id", type=int)
    env_id      = request.args.get("env_id",      type=int)
    status      = request.args.get("status",      "").strip()
    sort        = request.args.get("sort",  DEFAULT_SORT)
    order       = request.args.get("order", DEFAULT_ORDER)
    page        = request.args.get("page",  1, type=int)

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


# ── Add server ────────────────────────────────────────────────────────────── #

@inventory_bp.route("/inventory/add", methods=["POST"])
def add_server():
    """Create a new server record from the Add Server form."""
    hostname   = request.form.get("hostname",   "").strip()
    ip_address = request.form.get("ip_address", "").strip()

    # ── Basic validation ──────────────────────────────────────────────
    errors = []
    if not hostname:
        errors.append("Hostname is required.")
    if not ip_address:
        errors.append("IP address is required.")

    if not errors:
        # Uniqueness check
        if Server.query.filter_by(hostname=hostname).first():
            errors.append(f'A server with hostname "{hostname}" already exists.')

    if errors:
        for msg in errors:
            flash(msg, "danger")
        return redirect(url_for("inventory.index"))

    # ── Parse optional fields ─────────────────────────────────────────
    env_id      = request.form.get("environment_id", type=int) or None
    location_id = request.form.get("location_id",    type=int) or None
    owner_id    = request.form.get("owner_id",        type=int) or None
    status      = request.form.get("status", "active").strip()
    if status not in VALID_STATUSES:
        status = "active"

    cpu_count_raw = request.form.get("cpu_count", "").strip()
    ram_gb_raw    = request.form.get("ram_gb",    "").strip()

    try:
        cpu_count = int(cpu_count_raw)   if cpu_count_raw else None
        ram_gb    = float(ram_gb_raw)    if ram_gb_raw    else None
    except ValueError:
        cpu_count = None
        ram_gb    = None

    server = Server(
        hostname         = hostname,
        ip_address       = ip_address,
        environment_id   = env_id,
        location_id      = location_id,
        owner_id         = owner_id,
        operating_system = request.form.get("operating_system", "").strip() or None,
        kernel_version   = request.form.get("kernel_version",   "").strip() or None,
        cpu_count        = cpu_count,
        ram_gb           = ram_gb,
        status           = status,
    )

    try:
        db.session.add(server)
        log_action("inventory.server.add", target=hostname, details=ip_address)
        db.session.commit()
        flash(f'Server "{hostname}" added successfully.', "success")
        logger.info("Server created: %s (%s)", hostname, ip_address)
    except Exception:
        db.session.rollback()
        logger.exception("Failed to create server %s", hostname)
        flash("An error occurred while saving the server. Please try again.", "danger")

    return redirect(url_for("inventory.index"))


# ── Server detail ─────────────────────────────────────────────────────────── #

@inventory_bp.route("/inventory/<int:server_id>", methods=["GET"])
def server_detail(server_id: int):
    """Full server detail page — hardware, patching, packages, and notes."""
    server = Server.query.get_or_404(server_id)
    locations    = Location.query.filter_by(is_active=True).order_by(Location.name).all()
    environments = sort_envs(Environment.query.filter_by(is_active=True).all())
    owners       = Owner.query.filter_by(is_active=True).order_by(Owner.name).all()
    return render_template(
        "inventory/server_detail.html",
        server=server,
        locations=locations,
        environments=environments,
        owners=owners,
        statuses=list(VALID_STATUSES),
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


# ── Edit server ───────────────────────────────────────────────────────────── #

@inventory_bp.route("/inventory/<int:server_id>/edit", methods=["POST"])
def edit_server(server_id: int):
    """Update an existing server record."""
    server = Server.query.get_or_404(server_id)

    hostname   = request.form.get("hostname",   "").strip()
    ip_address = request.form.get("ip_address", "").strip()

    errors = []
    if not hostname:
        errors.append("Hostname is required.")
    if not ip_address:
        errors.append("IP address is required.")

    if not errors:
        existing = Server.query.filter(
            Server.hostname == hostname, Server.id != server_id
        ).first()
        if existing:
            errors.append(f'Hostname "{hostname}" is already used by another server.')

    if errors:
        for msg in errors:
            flash(msg, "danger")
        return redirect(url_for("inventory.server_detail", server_id=server_id))

    status = request.form.get("status", server.status).strip()
    if status not in VALID_STATUSES:
        status = server.status

    cpu_count_raw = request.form.get("cpu_count", "").strip()
    ram_gb_raw    = request.form.get("ram_gb",    "").strip()
    try:
        cpu_count = int(cpu_count_raw)   if cpu_count_raw else None
        ram_gb    = float(ram_gb_raw)    if ram_gb_raw    else None
    except ValueError:
        cpu_count = None
        ram_gb    = None

    server.hostname          = hostname
    server.ip_address        = ip_address
    server.fqdn              = request.form.get("fqdn",              "").strip() or None
    server.environment_id    = request.form.get("environment_id",    type=int) or None
    server.location_id       = request.form.get("location_id",       type=int) or None
    server.owner_id          = request.form.get("owner_id",          type=int) or None
    server.operating_system  = request.form.get("operating_system",  "").strip() or None
    server.os_version        = request.form.get("os_version",        "").strip() or None
    server.kernel_version    = request.form.get("kernel_version",    "").strip() or None
    server.cpu_model         = request.form.get("cpu_model",         "").strip() or None
    server.cpu_count         = cpu_count
    server.ram_gb            = ram_gb
    server.status            = status

    try:
        log_action("inventory.server.edit", target=server.hostname)
        db.session.commit()
        flash(f'Server "{server.hostname}" updated successfully.', "success")
        logger.info("Server updated: id=%d hostname=%s", server_id, server.hostname)
    except Exception:
        db.session.rollback()
        logger.exception("Failed to update server id=%d", server_id)
        flash("An error occurred while saving the server. Please try again.", "danger")

    return redirect(url_for("inventory.server_detail", server_id=server_id))


# ── Delete server ─────────────────────────────────────────────────────────── #

@inventory_bp.route("/inventory/<int:server_id>/delete", methods=["POST"])
def delete_server(server_id: int):
    """Permanently delete a server and all related records."""
    server = Server.query.get_or_404(server_id)
    hostname = server.hostname
    try:
        db.session.delete(server)
        log_action("inventory.server.delete", target=hostname)
        db.session.commit()
        flash(f'Server "{hostname}" has been deleted.', "success")
        logger.info("Server deleted: id=%d hostname=%s", server_id, hostname)
    except Exception:
        db.session.rollback()
        logger.exception("Failed to delete server id=%d", server_id)
        flash("An error occurred while deleting the server. Please try again.", "danger")
    return redirect(url_for("inventory.index"))


# ── Bulk actions ─────────────────────────────────────────────────────────── #

@inventory_bp.route("/inventory/bulk-delete", methods=["POST"])
def bulk_delete():
    """Permanently delete multiple servers."""
    ids = _parse_server_ids(request.form.getlist("server_ids"))
    if not ids:
        flash("No servers selected.", "warning")
        return redirect(url_for("inventory.index"))

    try:
        servers = Server.query.filter(Server.id.in_(ids)).all()
        count = len(servers)
        hostnames = [s.hostname for s in servers]
        for srv in servers:
            db.session.delete(srv)
        detail = ", ".join(hostnames[:10]) + (" …" if count > 10 else "")
        log_action("inventory.server.bulk_delete", target=f"{count} server(s)", details=detail)
        db.session.commit()
        flash(
            f"Deleted {count} server{'s' if count != 1 else ''}: "
            + ", ".join(hostnames[:5])
            + (" …" if count > 5 else ""),
            "success",
        )
        logger.info("Bulk delete: %d server(s) removed — ids=%s", count, ids)
    except Exception:
        db.session.rollback()
        logger.exception("Bulk delete failed for ids=%s", ids)
        flash("An error occurred while deleting the selected servers.", "danger")

    return redirect(url_for("inventory.index"))


@inventory_bp.route("/inventory/bulk-env", methods=["POST"])
def bulk_env():
    """Assign an environment to multiple servers."""
    ids = _parse_server_ids(request.form.getlist("server_ids"))
    env_id = request.form.get("environment_id", type=int)
    if not ids:
        flash("No servers selected.", "warning")
        return redirect(url_for("inventory.index"))

    # env_id=None clears the environment (allowed)
    if env_id is not None:
        env = Environment.query.get(env_id)
        if env is None:
            flash("Selected environment not found.", "danger")
            return redirect(url_for("inventory.index"))
        env_name = env.name
    else:
        env_name = "None"

    try:
        updated = (
            Server.query.filter(Server.id.in_(ids))
            .update({"environment_id": env_id}, synchronize_session="fetch")
        )
        log_action(
            "inventory.server.bulk_env",
            target=f"{updated} server(s)",
            details=f"environment → {env_name}",
        )
        db.session.commit()
        flash(
            f"Environment set to \"{env_name}\" for {updated} server{'s' if updated != 1 else ''}.",
            "success",
        )
        logger.info("Bulk env: env_id=%s applied to %d server(s) — ids=%s", env_id, updated, ids)
    except Exception:
        db.session.rollback()
        logger.exception("Bulk env failed for ids=%s", ids)
        flash("An error occurred while updating the environment.", "danger")

    return redirect(url_for("inventory.index"))


@inventory_bp.route("/inventory/bulk-location", methods=["POST"])
def bulk_location():
    """Assign a location to multiple servers."""
    ids = _parse_server_ids(request.form.getlist("server_ids"))
    location_id = request.form.get("location_id", type=int)
    if not ids:
        flash("No servers selected.", "warning")
        return redirect(url_for("inventory.index"))

    if location_id is not None:
        loc = Location.query.get(location_id)
        if loc is None:
            flash("Selected location not found.", "danger")
            return redirect(url_for("inventory.index"))
        loc_name = loc.name
    else:
        loc_name = "None"

    try:
        updated = (
            Server.query.filter(Server.id.in_(ids))
            .update({"location_id": location_id}, synchronize_session="fetch")
        )
        log_action(
            "inventory.server.bulk_location",
            target=f"{updated} server(s)",
            details=f"location → {loc_name}",
        )
        db.session.commit()
        flash(
            f"Location set to \"{loc_name}\" for {updated} server{'s' if updated != 1 else ''}.",
            "success",
        )
        logger.info("Bulk location: loc_id=%s applied to %d server(s) — ids=%s", location_id, updated, ids)
    except Exception:
        db.session.rollback()
        logger.exception("Bulk location failed for ids=%s", ids)
        flash("An error occurred while updating the location.", "danger")

    return redirect(url_for("inventory.index"))


# ── Notes: add ───────────────────────────────────────────────────────────── #

@inventory_bp.route("/inventory/<int:server_id>/notes/add", methods=["POST"])
def add_note(server_id: int):
    """Add a note to a server."""
    server = Server.query.get_or_404(server_id)
    body   = request.form.get("body", "").strip()
    author = request.form.get("author", "").strip() or None

    if not body:
        flash("Note body cannot be empty.", "danger")
        return redirect(url_for("inventory.server_detail", server_id=server_id))

    note = Note(server_id=server.id, body=body, author=author)
    try:
        db.session.add(note)
        log_action("inventory.note.add", target=server.hostname)
        db.session.commit()
        flash("Note added.", "success")
        logger.info("Note added to server id=%d", server_id)
    except Exception:
        db.session.rollback()
        logger.exception("Failed to add note to server id=%d", server_id)
        flash("An error occurred while saving the note.", "danger")

    return redirect(url_for("inventory.server_detail", server_id=server_id) + "#notes")


# ── Notes: delete ────────────────────────────────────────────────────────── #

@inventory_bp.route("/inventory/<int:server_id>/notes/<int:note_id>/delete", methods=["POST"])
def delete_note(server_id: int, note_id: int):
    """Delete a note from a server."""
    note = Note.query.filter_by(id=note_id, server_id=server_id).first_or_404()
    try:
        db.session.delete(note)
        log_action("inventory.note.delete", target=f"server id={server_id}")
        db.session.commit()
        flash("Note deleted.", "success")
        logger.info("Note id=%d deleted from server id=%d", note_id, server_id)
    except Exception:
        db.session.rollback()
        logger.exception("Failed to delete note id=%d", note_id)
        flash("An error occurred while deleting the note.", "danger")

    return redirect(url_for("inventory.server_detail", server_id=server_id) + "#notes")

"""Inventory blueprint routes."""
import logging

from flask import current_app, flash, redirect, render_template, request, url_for

from . import inventory_bp
from .queries import DEFAULT_ORDER, DEFAULT_SORT, InventoryFilters, get_inventory_page
from ...extensions import db
from ...models.environment import Environment
from ...models.location import Location
from ...models.owner import Owner
from ...models.server import Server

logger = logging.getLogger(__name__)

VALID_STATUSES = {"active", "inactive", "maintenance", "decommissioned"}


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
        db.session.commit()
        flash(f'Server "{hostname}" added successfully.', "success")
        logger.info("Server created: %s (%s)", hostname, ip_address)
    except Exception:
        db.session.rollback()
        logger.exception("Failed to create server %s", hostname)
        flash("An error occurred while saving the server. Please try again.", "danger")

    return redirect(url_for("inventory.index"))


# ── Server detail placeholder ─────────────────────────────────────────────── #

@inventory_bp.route("/inventory/<int:server_id>", methods=["GET"])
def server_detail(server_id: int):
    """Server detail page — placeholder until the Server Details module is built."""
    server = Server.query.get_or_404(server_id)
    return render_template(
        "inventory/server_detail_placeholder.html",
        server=server,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )

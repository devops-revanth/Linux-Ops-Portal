"""
VMware vCenter blueprint routes — Phase 4 multi-vCenter.

New management page at /settings/vmware/ with full CRUD for VmwareConnection.
Old single-config endpoints kept as redirects for backward compat.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required

from . import vmware_bp
from ...audit import commit_audit
from ...extensions import db
from ...models.vmware_connection import SYNC_SCHEDULE_CHOICES, VmwareConnection
from ...models.vmware_config import VmwareSyncLog
from ...models.location import Location
from ...models.environment import Environment
from ...services.vmware_service import VmwareService, is_sync_running

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _redirect_list(anchor: str = "") -> "Response":
    url = url_for("vmware.connections_list")
    return redirect(url + (f"#{anchor}" if anchor else ""))


def _reschedule_all() -> None:
    """Push all connection schedules to APScheduler."""
    try:
        from ...scheduler import reschedule_vmware_connections
        reschedule_vmware_connections(current_app._get_current_object())
    except Exception as exc:
        logger.debug("Could not reschedule VMware connections: %s", exc)


# ── Connections list page ─────────────────────────────────────────────────── #

@vmware_bp.route("/settings/vmware/", methods=["GET"])
@login_required
def connections_list():
    connections = (
        VmwareConnection.query
        .outerjoin(Location, VmwareConnection.location_id == Location.id)
        .order_by(Location.name, VmwareConnection.name)
        .all()
    )
    locations    = Location.query.filter_by(is_active=True).order_by(Location.name).all()
    environments = Environment.query.filter_by(is_active=True).order_by(Environment.name).all()

    # Per-connection running state
    running_ids = {cid for cid in [c.id for c in connections] if is_sync_running(cid)}

    return render_template(
        "vmware/connections.html",
        connections      = connections,
        locations        = locations,
        environments     = environments,
        running_ids      = running_ids,
        sync_schedules   = SYNC_SCHEDULE_CHOICES,
        app_name         = current_app.config["APP_NAME"],
        app_version      = current_app.config["APP_VERSION"],
    )


# ── Create ────────────────────────────────────────────────────────────────── #

@vmware_bp.route("/settings/vmware/connections", methods=["POST"])
@login_required
def connection_create():
    try:
        name         = request.form.get("name", "").strip()
        vcenter_host = request.form.get("vcenter_host", "").strip()
        port         = int(request.form.get("port", 443) or 443)
        username     = request.form.get("username", "").strip()
        password     = request.form.get("password", "")
        ignore_ssl   = request.form.get("ignore_ssl") == "1"
        enabled      = request.form.get("enabled") == "1"
        sync_sched   = request.form.get("sync_schedule", "disabled")
        loc_id       = request.form.get("location_id", "")
        env_id       = request.form.get("default_environment_id", "")

        if not name or not vcenter_host:
            flash("Name and vCenter Host are required.", "warning")
            return _redirect_list()

        if not loc_id:
            flash("Location is required.", "warning")
            return _redirect_list()

        valid_schedules = {v for v, _ in SYNC_SCHEDULE_CHOICES}
        if sync_sched not in valid_schedules:
            sync_sched = "disabled"

        # Check for duplicate location + host
        existing = VmwareConnection.query.filter_by(
            location_id=int(loc_id), vcenter_host=vcenter_host
        ).first()
        if existing:
            flash(
                f"A vCenter connection for '{vcenter_host}' in that location already exists.",
                "warning",
            )
            return _redirect_list()

        conn = VmwareConnection(
            name        = name,
            vcenter_host = vcenter_host,
            port        = port,
            username    = username,
            ignore_ssl  = ignore_ssl,
            enabled     = enabled,
            sync_schedule = sync_sched,
            location_id  = int(loc_id),
            default_environment_id = int(env_id) if env_id else None,
        )
        if password:
            conn.set_password(password)

        db.session.add(conn)
        db.session.commit()
        _reschedule_all()

        flash(f"vCenter '{name}' added.", "success")
        commit_audit(
            "vmware.connection.added",
            target=vcenter_host,
            details=f"name={name} location_id={loc_id} schedule={sync_sched}",
        )
    except Exception as exc:
        db.session.rollback()
        logger.exception("Failed to create VMware connection")
        flash(f"Error adding vCenter: {exc}", "danger")

    return _redirect_list()


# ── Update ────────────────────────────────────────────────────────────────── #

@vmware_bp.route("/settings/vmware/connections/<int:conn_id>/update", methods=["POST"])
@login_required
def connection_update(conn_id: int):
    conn = VmwareConnection.query.get_or_404(conn_id)
    try:
        name         = request.form.get("name", "").strip()
        vcenter_host = request.form.get("vcenter_host", "").strip()
        port         = int(request.form.get("port", 443) or 443)
        username     = request.form.get("username", "").strip()
        password     = request.form.get("password", "")
        ignore_ssl   = request.form.get("ignore_ssl") == "1"
        enabled      = request.form.get("enabled") == "1"
        sync_sched   = request.form.get("sync_schedule", "disabled")
        loc_id       = request.form.get("location_id", "")
        env_id       = request.form.get("default_environment_id", "")

        if not name or not vcenter_host:
            flash("Name and vCenter Host are required.", "warning")
            return _redirect_list()

        if not loc_id:
            flash("Location is required.", "warning")
            return _redirect_list()

        valid_schedules = {v for v, _ in SYNC_SCHEDULE_CHOICES}
        if sync_sched not in valid_schedules:
            sync_sched = "disabled"

        # Check duplicate (excluding self)
        dup = VmwareConnection.query.filter(
            VmwareConnection.location_id == int(loc_id),
            VmwareConnection.vcenter_host == vcenter_host,
            VmwareConnection.id != conn_id,
        ).first()
        if dup:
            flash(
                f"A vCenter connection for '{vcenter_host}' in that location already exists.",
                "warning",
            )
            return _redirect_list()

        conn.name         = name
        conn.vcenter_host = vcenter_host
        conn.port         = port
        conn.username     = username
        conn.ignore_ssl   = ignore_ssl
        conn.enabled      = enabled
        conn.sync_schedule = sync_sched
        conn.location_id  = int(loc_id)
        conn.default_environment_id = int(env_id) if env_id else None

        if password:
            conn.set_password(password)

        db.session.commit()
        _reschedule_all()

        flash(f"vCenter '{name}' updated.", "success")
        commit_audit(
            "vmware.connection.updated",
            target=vcenter_host,
            details=f"name={name} schedule={sync_sched} enabled={enabled}",
        )
    except Exception as exc:
        db.session.rollback()
        logger.exception("Failed to update VMware connection %d", conn_id)
        flash(f"Error updating vCenter: {exc}", "danger")

    return _redirect_list()


# ── Delete ────────────────────────────────────────────────────────────────── #

@vmware_bp.route("/settings/vmware/connections/<int:conn_id>/delete", methods=["POST"])
@login_required
def connection_delete(conn_id: int):
    conn = VmwareConnection.query.get_or_404(conn_id)
    try:
        name = conn.name
        host = conn.vcenter_host

        # Remove from scheduler before deleting
        try:
            from ...scheduler import remove_vmware_connection_job
            remove_vmware_connection_job(current_app._get_current_object(), conn_id)
        except Exception:
            pass

        db.session.delete(conn)
        db.session.commit()

        flash(f"vCenter '{name}' deleted.", "success")
        commit_audit(
            "vmware.connection.deleted",
            target=host,
            details=f"name={name} id={conn_id}",
        )
    except Exception as exc:
        db.session.rollback()
        logger.exception("Failed to delete VMware connection %d", conn_id)
        flash(f"Error deleting vCenter: {exc}", "danger")

    return _redirect_list()


# ── Toggle enable / disable ───────────────────────────────────────────────── #

@vmware_bp.route("/settings/vmware/connections/<int:conn_id>/toggle", methods=["POST"])
@login_required
def connection_toggle(conn_id: int):
    conn = VmwareConnection.query.get_or_404(conn_id)
    try:
        conn.enabled = not conn.enabled
        db.session.commit()
        _reschedule_all()

        state = "enabled" if conn.enabled else "disabled"
        flash(f"vCenter '{conn.name}' {state}.", "success")
        commit_audit(
            f"vmware.connection.{'enable' if conn.enabled else 'disable'}",
            target=conn.vcenter_host,
            details=f"name={conn.name}",
        )
    except Exception as exc:
        db.session.rollback()
        flash(f"Error: {exc}", "danger")

    return _redirect_list()


# ── Test connection (AJAX) ────────────────────────────────────────────────── #

@vmware_bp.route("/settings/vmware/connections/<int:conn_id>/test", methods=["POST"])
@login_required
def connection_test(conn_id: int):
    conn = VmwareConnection.query.get_or_404(conn_id)

    # Prefer submitted values so user can test unsaved changes
    host       = request.form.get("vcenter_host", conn.vcenter_host or "").strip()
    port       = int(request.form.get("port", conn.port or 443) or 443)
    username   = request.form.get("username", conn.username or "").strip()
    submitted_pwd = request.form.get("password", "")
    password   = submitted_pwd if submitted_pwd else (conn.get_password() or "")
    ignore_ssl = (
        request.form.get("ignore_ssl") == "1"
        if "ignore_ssl" in request.form
        else conn.ignore_ssl
    )

    if not host:
        return jsonify({"success": False, "message": "vCenter host is required."})

    svc = VmwareService(
        vcenter_host=host, port=port,
        username=username, password=password,
        ignore_ssl=ignore_ssl,
        connection_name=conn.name,
        connection_id=conn.id,
    )
    success, message, status = svc.test_connection()

    # Persist connection status
    try:
        conn.connection_status = status
        conn.last_test_at      = datetime.now(timezone.utc)
        db.session.commit()
    except Exception:
        db.session.rollback()

    commit_audit(
        "vmware.connection.test",
        target=host,
        details=f"name={conn.name} result={status}",
    )
    return jsonify({"success": success, "message": message, "status": status})


# ── Sync now ──────────────────────────────────────────────────────────────── #

@vmware_bp.route("/settings/vmware/connections/<int:conn_id>/sync", methods=["POST"])
@login_required
def connection_sync(conn_id: int):
    conn = VmwareConnection.query.get_or_404(conn_id)

    if not conn.enabled:
        return jsonify({"success": False, "message": "Connection is disabled."})

    if not conn.vcenter_host or not conn.username:
        return jsonify({"success": False, "message": "Connection settings are incomplete."})

    if is_sync_running(conn_id):
        return jsonify({"success": False, "message": "Sync already in progress."})

    svc = VmwareService.from_connection(conn)
    started, msg = svc.sync_now(
        current_app._get_current_object(), triggered_by="manual"
    )
    commit_audit(
        "vmware.sync.started",
        target=conn.vcenter_host,
        details=f"name={conn.name} triggered_by=manual",
    )
    return jsonify({"success": started, "message": msg})


# ── Status poll (AJAX) ────────────────────────────────────────────────────── #

@vmware_bp.route("/settings/vmware/connections/<int:conn_id>/status")
@login_required
def connection_status(conn_id: int):
    conn = VmwareConnection.query.get(conn_id)
    if conn is None:
        return jsonify({"error": "Not found"}), 404

    last_log = (
        VmwareSyncLog.query
        .filter_by(connection_id=conn_id)
        .order_by(VmwareSyncLog.started_at.desc())
        .first()
    )
    return jsonify({
        "running":           is_sync_running(conn_id),
        "connection_status": conn.connection_status,
        "last_sync_ok":      conn.last_sync_ok_at.isoformat() if conn.last_sync_ok_at else None,
        "last_sync_fail":    conn.last_sync_fail_at.isoformat() if conn.last_sync_fail_at else None,
        "last_sync_vms":     conn.last_sync_vms or 0,
        "last_sync_secs":    conn.last_sync_duration_s,
        "log": {
            "status":   last_log.status,
            "imported": last_log.vms_imported,
            "updated":  last_log.vms_updated,
            "skipped":  last_log.vms_skipped,
            "error":    last_log.error_message,
        } if last_log else None,
    })


# ── Backward-compat redirects (old single-config URLs) ───────────────────── #

@vmware_bp.route("/settings/vmware/save", methods=["POST"])
@login_required
def save_vmware():
    flash("VMware settings are now managed from the VMware Connections page.", "info")
    return redirect(url_for("vmware.connections_list"))


@vmware_bp.route("/settings/vmware/toggle", methods=["POST"])
@login_required
def toggle_vmware():
    return redirect(url_for("vmware.connections_list"))


@vmware_bp.route("/settings/vmware/test", methods=["POST"])
@login_required
def test_vmware():
    return jsonify({"success": False, "message": "Use the per-connection test endpoint."})


@vmware_bp.route("/settings/vmware/sync", methods=["POST"])
@login_required
def sync_vmware():
    flash("Use 'Sync Now' on the VMware Connections page.", "info")
    return redirect(url_for("vmware.connections_list"))


@vmware_bp.route("/settings/vmware/sync/status")
@login_required
def vmware_sync_status():
    """Legacy poll endpoint — returns aggregate running state."""
    running = is_sync_running()
    from ...models.vmware_connection import VmwareConnection
    conns = VmwareConnection.query.all()
    connected = sum(1 for c in conns if c.connection_status == "Connected")
    last_ok   = max((c.last_sync_ok_at for c in conns if c.last_sync_ok_at), default=None)
    total_vms = sum(c.last_sync_vms or 0 for c in conns)
    return jsonify({
        "running":           running,
        "connection_status": "Connected" if connected else "Not Connected",
        "last_sync_ok":      last_ok.isoformat() if last_ok else None,
        "last_sync_vms":     total_vms,
    })

"""
VMware vCenter blueprint routes.

All routes live under /settings/vmware/… so they sit alongside
other settings sections.  The blueprint is registered with url_prefix=""
so URLs are built relative to the app root.
"""
from __future__ import annotations

import logging

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required

from . import vmware_bp
from ...audit import commit_audit
from ...extensions import db
from ...models.vmware_config import (
    SYNC_SCHEDULE_CHOICES,
    VmwareConfig,
    VmwareSyncLog,
)
from ...models.location import Location
from ...models.environment import Environment
from ...services.vmware_service import VmwareService, is_sync_running

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _get_vmware_config() -> VmwareConfig | None:
    try:
        return VmwareConfig.get()
    except Exception:
        return None


def _redirect_vmware(anchor: str = "vmware-vcenter") -> "Response":
    return redirect(url_for("settings.index") + f"#{anchor}")


# ── Save ──────────────────────────────────────────────────────────────────── #

@vmware_bp.route("/settings/vmware/save", methods=["POST"])
@login_required
def save_vmware():
    """Save vCenter connection settings."""
    try:
        cfg = _get_vmware_config() or VmwareConfig()
        db.session.add(cfg)

        enabled = request.form.get("enabled") == "1"
        cfg.enabled        = enabled
        cfg.vcenter_host   = request.form.get("vcenter_host", "").strip()
        cfg.port           = int(request.form.get("port", 443) or 443)
        cfg.username       = request.form.get("username", "").strip()
        cfg.ignore_ssl     = request.form.get("ignore_ssl") == "1"

        # Only overwrite password if a new one was submitted
        new_pwd = request.form.get("password", "")
        if new_pwd:
            cfg.set_password(new_pwd)

        loc_id = request.form.get("default_location_id", "")
        env_id = request.form.get("default_environment_id", "")
        cfg.default_location_id    = int(loc_id) if loc_id else None
        cfg.default_environment_id = int(env_id) if env_id else None

        schedule = request.form.get("sync_schedule", "disabled")
        valid_schedules = {v for v, _ in SYNC_SCHEDULE_CHOICES}
        cfg.sync_schedule = schedule if schedule in valid_schedules else "disabled"

        db.session.commit()

        # Reschedule background job if APScheduler is configured
        try:
            _reschedule(cfg)
        except Exception:
            pass

        flash("VMware vCenter settings saved.", "success")
        commit_audit("settings.vmware.save", target=cfg.vcenter_host)
    except Exception as exc:
        db.session.rollback()
        logger.exception("Failed to save VMware config")
        flash(f"Error saving VMware settings: {exc}", "danger")

    return _redirect_vmware()


# ── Enable / Disable toggle ───────────────────────────────────────────────── #

@vmware_bp.route("/settings/vmware/toggle", methods=["POST"])
@login_required
def toggle_vmware():
    """Enable or disable VMware integration."""
    enabled = request.form.get("enabled") == "1"
    try:
        cfg = _get_vmware_config() or VmwareConfig()
        cfg.enabled = enabled
        db.session.add(cfg)
        db.session.commit()
        state = "enabled" if enabled else "disabled"
        flash(f"VMware integration {state}.", "success")
        commit_audit(f"settings.vmware.{'enable' if enabled else 'disable'}")
        try:
            _reschedule(cfg)
        except Exception:
            pass
    except Exception as exc:
        db.session.rollback()
        flash(f"Error: {exc}", "danger")
    return _redirect_vmware()


# ── Test connection (AJAX) ────────────────────────────────────────────────── #

@vmware_bp.route("/settings/vmware/test", methods=["POST"])
@login_required
def test_vmware():
    """AJAX: test the vCenter connection.  Returns JSON."""
    cfg = _get_vmware_config()
    if cfg is None:
        return jsonify({"success": False, "message": "No VMware configuration found."})

    # Use submitted form values so the user can test before saving
    host     = request.form.get("vcenter_host", cfg.vcenter_host or "").strip()
    port     = int(request.form.get("port", cfg.port or 443) or 443)
    username = request.form.get("username", cfg.username or "").strip()
    password = request.form.get("password", "").strip() or cfg.get_password() or ""
    ignore_ssl = request.form.get("ignore_ssl") == "1" if "ignore_ssl" in request.form \
        else cfg.ignore_ssl

    if not host:
        return jsonify({"success": False, "message": "vCenter host is required."})

    svc = VmwareService(
        vcenter_host=host, port=port,
        username=username, password=password,
        ignore_ssl=ignore_ssl,
    )
    success, message, status = svc.test_connection()

    # Persist status
    try:
        from datetime import datetime, timezone
        cfg.connection_status = status
        cfg.last_test_at = datetime.now(timezone.utc)
        db.session.commit()
    except Exception:
        db.session.rollback()

    commit_audit(
        "vmware.connection.test",
        target=host,
        details=f"success={success}: {message}",
    )

    return jsonify({"success": success, "message": message, "status": status})


# ── Sync now ──────────────────────────────────────────────────────────────── #

@vmware_bp.route("/settings/vmware/sync", methods=["POST"])
@login_required
def sync_vmware():
    """Trigger a manual VMware sync in the background."""
    cfg = _get_vmware_config()
    if cfg is None or not cfg.enabled:
        flash("VMware integration is not enabled.", "warning")
        return _redirect_vmware()

    if not cfg.vcenter_host or not cfg.username:
        flash("VMware connection settings are incomplete.", "warning")
        return _redirect_vmware()

    if is_sync_running():
        flash("A sync is already in progress. Please wait.", "info")
        return _redirect_vmware()

    svc = VmwareService.from_config(cfg)
    started, msg = svc.sync_now(current_app._get_current_object(), triggered_by="manual")
    if started:
        flash("VMware sync started. Results will appear in the sync log.", "success")
    else:
        flash(f"Could not start sync: {msg}", "warning")

    return _redirect_vmware()


# ── Sync status (AJAX poll) ───────────────────────────────────────────────── #

@vmware_bp.route("/settings/vmware/sync/status")
@login_required
def vmware_sync_status():
    """AJAX: return current sync state and most recent log entry."""
    cfg = _get_vmware_config()
    last_log = (
        VmwareSyncLog.query
        .order_by(VmwareSyncLog.started_at.desc())
        .first()
    )
    return jsonify({
        "running":          is_sync_running(),
        "connection_status": cfg.connection_status if cfg else "Not Tested",
        "last_sync_ok":     cfg.last_sync_ok_at.isoformat() if cfg and cfg.last_sync_ok_at else None,
        "last_sync_fail":   cfg.last_sync_fail_at.isoformat() if cfg and cfg.last_sync_fail_at else None,
        "last_sync_vms":    cfg.last_sync_vms if cfg else 0,
        "last_sync_secs":   cfg.last_sync_duration_s if cfg else None,
        "log": {
            "status":    last_log.status,
            "imported":  last_log.vms_imported,
            "updated":   last_log.vms_updated,
            "skipped":   last_log.vms_skipped,
            "error":     last_log.error_message,
        } if last_log else None,
    })


# ── APScheduler integration ───────────────────────────────────────────────── #

def _reschedule(cfg: VmwareConfig) -> None:
    """Update the APScheduler job to match the configured schedule."""
    try:
        from flask_apscheduler import APScheduler  # type: ignore
        scheduler = current_app.extensions.get("apscheduler")
        if scheduler is None:
            return
        job_id = "vmware_scheduled_sync"
        scheduler.remove_job(job_id)
    except Exception:
        pass  # scheduler not configured or job didn't exist

    if not cfg.enabled or cfg.sync_schedule == "disabled":
        return

    schedule_map = {
        "hourly": {"trigger": "interval", "hours": 1},
        "6h":     {"trigger": "interval", "hours": 6},
        "12h":    {"trigger": "interval", "hours": 12},
        "daily":  {"trigger": "interval", "hours": 24},
    }
    kwargs = schedule_map.get(cfg.sync_schedule)
    if not kwargs:
        return

    try:
        from flask_apscheduler import APScheduler  # type: ignore
        scheduler = current_app.extensions.get("apscheduler")
        if scheduler:
            scheduler.add_job(
                id=job_id,
                func=_run_scheduled_sync,
                **kwargs,
                replace_existing=True,
            )
    except Exception:
        pass


def _run_scheduled_sync() -> None:
    """APScheduler job target — runs VMware sync with app context."""
    try:
        from flask import current_app
        cfg = VmwareConfig.get()
        if not cfg or not cfg.enabled:
            return
        svc = VmwareService.from_config(cfg)
        svc.sync_now(current_app._get_current_object(), triggered_by="scheduled")
    except Exception as exc:
        logger.error("Scheduled VMware sync failed: %s", exc)

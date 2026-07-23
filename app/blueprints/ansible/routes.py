"""
Ansible integration blueprint routes.

All routes live under /settings/ansible/… to sit alongside other
settings sections.  The blueprint is registered with no url_prefix.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import threading

from flask import jsonify, flash, redirect, request, url_for, current_app
from flask_login import login_required, current_user

from . import ansible_bp
from ...audit import commit_audit
from ...extensions import db
from ...models.ansible_config import (
    AnsibleConfig,
    AnsibleInventoryHost,
    AUTH_METHOD_CHOICES,
    INVENTORY_SOURCE_CHOICES,
)
from ...services.ansible_service import AnsibleService

logger = logging.getLogger(__name__)

# Thread-safe flag: True while a fact collection run is in progress
_fact_collection_running = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _get_cfg() -> AnsibleConfig | None:
    try:
        return AnsibleConfig.get()
    except Exception:
        return None


def _redirect_ansible() -> "Response":
    return redirect(url_for("settings.index") + "#ansible-section")


def _build_service(cfg: AnsibleConfig, form=None) -> AnsibleService:
    """
    Build an AnsibleService from saved config, optionally overlaying
    submitted form values (so users can test before saving).
    """
    f = form or {}
    host        = f.get("control_node", cfg.control_node or "").strip()
    port        = int(f.get("port", cfg.port or 22) or 22)
    username    = f.get("username", cfg.username or "").strip()
    auth_method = f.get("auth_method", cfg.auth_method or "key")
    inv_path    = f.get("inventory_path", cfg.inventory_path or "/etc/ansible/hosts").strip()
    pb_dir      = f.get("playbook_dir", cfg.playbook_dir or "/etc/ansible/playbooks").strip()
    hkc         = f.get("host_key_checking", str(cfg.host_key_checking)) not in ("0", "false", "False")
    timeout     = int(f.get("connection_timeout", cfg.connection_timeout or 30) or 30)

    # Passwords: use submitted value; fall back to stored if blank
    ssh_pwd = f.get("ssh_password", "")
    if not ssh_pwd:
        ssh_pwd = cfg.get_ssh_password() or ""

    ssh_key = f.get("ssh_private_key", "").strip()
    if not ssh_key:
        ssh_key = cfg.get_ssh_private_key() or ""

    return AnsibleService(
        host              = host,
        port              = port,
        username          = username,
        auth_method       = auth_method,
        ssh_password      = ssh_pwd,
        ssh_private_key   = ssh_key,
        host_key_checking = hkc,
        timeout           = timeout,
        inventory_path    = inv_path,
        playbook_dir      = pb_dir,
    )


# ── Save settings ─────────────────────────────────────────────────────────── #

@ansible_bp.route("/settings/ansible/save", methods=["POST"])
@login_required
def save_ansible():
    """Save Ansible connection settings."""
    try:
        cfg = _get_cfg() or AnsibleConfig()
        db.session.add(cfg)

        cfg.enabled          = request.form.get("enabled") == "1"
        cfg.control_node     = request.form.get("control_node", "").strip()
        cfg.port             = int(request.form.get("port", 22) or 22)
        cfg.username         = request.form.get("username", "").strip()
        cfg.auth_method      = request.form.get("auth_method", "key")
        cfg.host_key_checking = request.form.get("host_key_checking") == "1"
        cfg.connection_timeout = int(request.form.get("connection_timeout", 30) or 30)

        # Inventory settings
        inv_src = request.form.get("inventory_source", "static")
        valid_sources = {v for v, _ in INVENTORY_SOURCE_CHOICES}
        cfg.inventory_source = inv_src if inv_src in valid_sources else "static"
        cfg.inventory_path   = request.form.get("inventory_path", "/etc/ansible/hosts").strip()
        cfg.playbook_dir     = request.form.get("playbook_dir", "/etc/ansible/playbooks").strip()
        cfg.collections_dir  = request.form.get("collections_dir", "").strip() or None

        # Vault
        cfg.vault_enabled = request.form.get("vault_enabled") == "1"
        new_vault_pwd = request.form.get("vault_password", "")
        if new_vault_pwd:
            cfg.set_vault_password(new_vault_pwd)

        # Credentials — only overwrite when explicitly submitted
        valid_methods = {v for v, _ in AUTH_METHOD_CHOICES}
        if cfg.auth_method not in valid_methods:
            cfg.auth_method = "key"

        new_pwd = request.form.get("ssh_password", "")
        if new_pwd:
            cfg.set_ssh_password(new_pwd)

        new_key = request.form.get("ssh_private_key", "").strip()
        if new_key:
            cfg.set_ssh_private_key(new_key)

        db.session.commit()

        flash("Ansible settings saved.", "success")
        commit_audit(
            "settings.ansible.save",
            target=cfg.control_node,
            details=f"enabled={cfg.enabled} auth={cfg.auth_method} inv={cfg.inventory_source}",
        )
    except Exception as exc:
        db.session.rollback()
        logger.exception("Failed to save Ansible config")
        flash(f"Error saving Ansible settings: {exc}", "danger")

    return _redirect_ansible()


# ── Test connection (AJAX) ─────────────────────────────────────────────────── #

@ansible_bp.route("/settings/ansible/test", methods=["POST"])
@login_required
def test_ansible():
    """AJAX: test SSH connectivity and Ansible installation. Always returns JSON."""
    try:
        cfg = _get_cfg()
        if cfg is None:
            return jsonify({"success": False, "message": "No Ansible configuration found.", "checks": []})

        host = (request.form.get("control_node") or cfg.control_node or "").strip()
        if not host:
            return jsonify({"success": False, "message": "Control node host is required.", "checks": []})

        svc    = _build_service(cfg, form=request.form)
        result = svc.test_connection()

        # Persist status and version info — never the credentials.
        # Failures here must not prevent the JSON response from reaching the client.
        try:
            cfg.connection_status = result["status"]
            cfg.last_test_at      = datetime.now(timezone.utc)
            if result["success"]:
                cfg.last_connected_at = datetime.now(timezone.utc)
                if result.get("ansible_version"):
                    cfg.ansible_version = result["ansible_version"]
                if result.get("python_version"):
                    cfg.python_version = result["python_version"]
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.warning("test_ansible: failed to persist connection status")

        # Audit log — also non-fatal
        try:
            commit_audit(
                "ansible.connection.test",
                target=host,
                details=f"status={result['status']}",
                result="success" if result["success"] else "failure",
            )
        except Exception:
            logger.warning("test_ansible: audit log failed")

        return jsonify({
            "success":         result["success"],
            "status":          result["status"],
            "message":         result["message"],
            "ansible_version": result.get("ansible_version"),
            "python_version":  result.get("python_version"),
            "checks":          result.get("checks", []),
        })

    except Exception as exc:
        # Catch-all: any unhandled exception (e.g. ValueError from bad form data,
        # unexpected AnsibleService error) must still return JSON so the browser
        # does not receive an HTML 500 error page.
        logger.exception("test_ansible: unexpected error")
        return jsonify({
            "success": False,
            "message": f"Unexpected error: {exc}",
            "checks":  [],
        }), 500


# ── Validate inventory (AJAX) ─────────────────────────────────────────────── #

@ansible_bp.route("/settings/ansible/validate", methods=["POST"])
@login_required
def validate_inventory():
    """AJAX: run ansible-inventory --list and return summary. Returns JSON."""
    cfg = _get_cfg()
    if cfg is None:
        return jsonify({"success": False, "message": "No Ansible configuration found."})

    svc    = _build_service(cfg, form=request.form)
    result = svc.validate_inventory()

    now = datetime.now(timezone.utc)

    # Persist results to DB; always update last_validation_at so the UI
    # reflects when validation was last attempted (successful or not).
    if result["success"] and result.get("hosts"):
        try:
            # Replace all existing host records atomically
            AnsibleInventoryHost.query.delete()
            for hostname in result["hosts"]:
                groups = [
                    g for g, hosts in result.get("raw_groups", {}).items()
                    if hostname in hosts
                ]
                db.session.add(AnsibleInventoryHost(
                    hostname      = hostname,
                    groups        = ", ".join(sorted(groups)) if groups else None,
                    discovered_at = now,
                ))
            cfg.last_inventory_hosts = result["host_count"]
            cfg.last_validation_at   = now
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.warning("Failed to persist Ansible inventory hosts: %s", exc)
    else:
        # Update timestamp even on failure so the UI shows when last attempted
        try:
            cfg.last_validation_at = now
            db.session.commit()
        except Exception:
            db.session.rollback()

    commit_audit(
        "ansible.inventory.validate",
        details=(
            f"success={result['success']} "
            f"hosts={result['host_count']} "
            f"groups={len(result['group_names'])}"
        ),
        result="success" if result["success"] else "failure",
    )

    return jsonify({
        "success":    result["success"],
        "host_count": result["host_count"],
        "groups":     result["group_names"],
        "hosts":      result["hosts"][:50],   # cap response size
        "errors":     result["errors"],
    })


# ── Discover playbooks (AJAX) ─────────────────────────────────────────────── #

@ansible_bp.route("/settings/ansible/discover", methods=["POST"])
@login_required
def discover_playbooks():
    """AJAX: find YAML playbooks in the playbook directory. Returns JSON."""
    cfg = _get_cfg()
    if cfg is None:
        return jsonify({"success": False, "playbooks": []})

    svc    = _build_service(cfg, form=request.form)
    disc   = svc.discover_playbooks()

    playbooks = disc.get("playbooks", [])
    errors    = disc.get("errors", [])
    connected = disc.get("connected", False)
    success   = connected and len(playbooks) > 0

    # Persist playbook count to config (only when we actually connected)
    if connected:
        try:
            cfg.last_playbooks_found = len(playbooks)
            db.session.commit()
        except Exception:
            db.session.rollback()

    commit_audit(
        "ansible.playbooks.discover",
        details=f"found={len(playbooks)} connected={connected}",
        result="success" if connected else "failure",
    )

    return jsonify({
        "success":   connected,
        "count":     len(playbooks),
        "playbooks": playbooks,
        "errors":    errors,
    })


# ── Collect Facts Now (AJAX) ───────────────────────────────────────────────── #

@ansible_bp.route("/settings/ansible/collect", methods=["POST"])
@login_required
def collect_facts():
    """
    AJAX: trigger a full Ansible fact collection run.

    Runs in a background thread so the HTTP response returns immediately.
    Returns JSON with job_id; the client polls /collect-status for progress.
    """
    cfg = _get_cfg()
    if cfg is None:
        return jsonify({"success": False, "message": "No Ansible configuration found."})

    if not cfg.enabled:
        return jsonify({"success": False, "message": "Ansible integration is not enabled."})

    if cfg.connection_status != "Connected":
        return jsonify({
            "success": False,
            "message": (
                f"Control node is not connected (status: {cfg.connection_status}). "
                f"Test the connection in the settings form first."
            )
        })

    # Reject if a collection is already running
    if not _fact_collection_running.acquire(blocking=False):
        return jsonify({
            "success": False,
            "message": "A fact collection is already in progress. Please wait."
        })

    app = current_app._get_current_object()

    def _run():
        try:
            from ...services.ansible_fact_service import collect_facts as _collect
            _collect(cfg, app, triggered_by="manual")
        except Exception as exc:
            logger.error("Background fact collection failed: %s", exc)
        finally:
            _fact_collection_running.release()

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    commit_audit(
        "ansible.facts.collect.trigger",
        details="triggered_by=manual (background thread started)",
        result="success",
    )

    return jsonify({
        "success": True,
        "message": "Fact collection started. This may take several minutes depending on inventory size.",
    })


@ansible_bp.route("/settings/ansible/collect-status", methods=["GET"])
@login_required
def collect_status():
    """AJAX: return the status of the last fact collection run, including live progress."""
    cfg = _get_cfg()
    if cfg is None:
        return jsonify({"running": False, "status": "Not Configured"})

    # Use the service's progress dict for live state
    from ...services.ansible_fact_service import get_progress
    prog = get_progress()
    running = prog.get("running", False)

    resp: dict = {
        "running":        running,
        "status":         getattr(cfg, "last_fact_sync_status", None) or "Never Run",
        "last_sync_at":   (
            cfg.last_fact_sync_at.isoformat()
            if getattr(cfg, "last_fact_sync_at", None) else None
        ),
        "servers_ok":     getattr(cfg, "last_fact_sync_ok", 0) or 0,
        "servers_failed": getattr(cfg, "last_fact_sync_failed", 0) or 0,
    }
    if running:
        total = prog.get("total", 0)
        done  = prog.get("done",  0)
        resp.update({
            "progress_total":   total,
            "progress_done":    done,
            "progress_pct":     int(done / total * 100) if total else 0,
            "current_host":     prog.get("current_host", ""),
        })
    return jsonify(resp)


@ansible_bp.route("/settings/ansible/failed-hosts", methods=["GET"])
@login_required
def failed_hosts():
    """AJAX: return servers where the last fact collection failed."""
    from ...models.server import Server
    try:
        rows = (
            Server.query
            .filter(Server.ansible_fact_status == "failed")
            .order_by(Server.hostname)
            .all()
        )
        return jsonify({
            "count": len(rows),
            "hosts": [
                {
                    "id":       s.id,
                    "hostname": s.hostname,
                    "error":    s.ansible_fact_error or "Unknown error",
                    "synced":   s.last_ansible_sync.isoformat() if s.last_ansible_sync else None,
                }
                for s in rows
            ],
        })
    except Exception as exc:
        logger.exception("failed-hosts query error")
        return jsonify({"error": str(exc), "hosts": []}), 500


@ansible_bp.route("/settings/ansible/retry-failed", methods=["POST"])
@login_required
def retry_failed():
    """
    AJAX: retry fact collection ONLY for hosts whose last run failed.
    Does NOT re-collect from successfully synced hosts.
    """
    cfg = _get_cfg()
    if cfg is None:
        return jsonify({"success": False, "message": "No Ansible configuration found."})
    if not cfg.enabled or cfg.connection_status != "Connected":
        return jsonify({"success": False, "message": "Control node is not connected."})

    from ...models.server import Server
    failed_hosts_qs = (
        Server.query
        .filter(Server.ansible_fact_status == "failed")
        .with_entities(Server.hostname, Server.fqdn)
        .all()
    )
    if not failed_hosts_qs:
        return jsonify({"success": False, "message": "No failed hosts to retry."})

    if not _fact_collection_running.acquire(blocking=False):
        return jsonify({"success": False, "message": "A collection is already in progress."})

    app = current_app._get_current_object()

    def _run():
        try:
            from ...services.ansible_fact_service import collect_facts as _collect
            _collect(cfg, app, triggered_by="retry-failed")
        except Exception as exc:
            logger.error("Retry-failed collection failed: %s", exc)
        finally:
            _fact_collection_running.release()

    threading.Thread(target=_run, daemon=True).start()
    commit_audit(
        "ansible.facts.retry.trigger",
        details=f"failed_hosts_count={len(failed_hosts_qs)}",
        result="success",
    )
    return jsonify({
        "success": True,
        "message": f"Retrying {len(failed_hosts_qs)} failed host(s) in the background.",
    })


@ansible_bp.route("/settings/ansible/history", methods=["GET"])
@login_required
def collection_history():
    """AJAX: return last N sync job records."""
    from ...models.ansible_facts import AnsibleSyncJob
    limit = min(request.args.get("limit", 20, type=int), 100)
    try:
        jobs = (
            AnsibleSyncJob.query
            .order_by(AnsibleSyncJob.started_at.desc())
            .limit(limit)
            .all()
        )
        def _dur(j):
            if j.completed_at and j.started_at:
                return int((j.completed_at - j.started_at).total_seconds())
            return None

        return jsonify({
            "jobs": [
                {
                    "id":              j.id,
                    "started_at":      j.started_at.isoformat(),
                    "completed_at":    j.completed_at.isoformat() if j.completed_at else None,
                    "duration_secs":   _dur(j),
                    "triggered_by":    j.triggered_by,
                    "status":          j.status,
                    "servers_total":   j.servers_total,
                    "servers_ok":      j.servers_ok,
                    "servers_failed":  j.servers_failed,
                    "packages_synced": j.packages_synced,
                    "error_message":   j.error_message,
                }
                for j in jobs
            ]
        })
    except Exception as exc:
        return jsonify({"error": str(exc), "jobs": []}), 500


@ansible_bp.route("/settings/ansible/drift", methods=["GET"])
@login_required
def inventory_drift():
    """
    AJAX: compare Ansible inventory hosts vs LOP servers.
    Returns counts and lists of hosts missing from each side.
    """
    try:
        from ...models.ansible_config import AnsibleInventoryHost
        from ...models.server import Server

        # All Ansible inventory hostnames (lowercase)
        inv_hosts = {
            h.hostname.lower()
            for h in AnsibleInventoryHost.query.with_entities(AnsibleInventoryHost.hostname).all()
            if h.hostname
        }

        # All LOP server identifiers (hostname + fqdn, lowercase)
        lop_servers = Server.query.with_entities(Server.hostname, Server.fqdn, Server.id).all()
        lop_keys: dict[str, int] = {}   # lowercased key → server_id
        for s in lop_servers:
            if s.hostname:
                lop_keys[s.hostname.lower()] = s.id
            if s.fqdn:
                lop_keys[s.fqdn.lower()] = s.id

        missing_in_lop     = sorted(inv_hosts - set(lop_keys.keys()))
        missing_in_ansible = sorted(
            s.hostname for s in lop_servers
            if s.hostname and s.hostname.lower() not in inv_hosts
            and (not s.fqdn or s.fqdn.lower() not in inv_hosts)
        )

        return jsonify({
            "inventory_hosts":    len(inv_hosts),
            "lop_servers":        len(lop_servers),
            "missing_in_lop":     missing_in_lop,
            "missing_in_ansible": missing_in_ansible,
        })
    except Exception as exc:
        logger.exception("drift query failed")
        return jsonify({"error": str(exc)}), 500


# ── Save Ansible settings + reschedule ────────────────────────────────────── #

@ansible_bp.route("/settings/ansible/reschedule", methods=["POST"])
@login_required
def save_ansible_schedule():
    """AJAX: save the sync schedule and restart the APScheduler job."""
    cfg = _get_cfg()
    if cfg is None:
        return jsonify({"success": False, "message": "No Ansible configuration found."})

    sync_enabled  = request.form.get("sync_enabled") == "1"
    sync_schedule = request.form.get("sync_schedule", "disabled")
    valid_schedules = {"hourly", "6h", "12h", "daily", "disabled"}
    if sync_schedule not in valid_schedules:
        sync_schedule = "disabled"

    try:
        cfg.sync_enabled  = sync_enabled
        cfg.sync_schedule = sync_schedule if sync_enabled else "disabled"
        db.session.commit()

        from ...scheduler import reschedule_ansible
        reschedule_ansible(
            current_app._get_current_object(),
            cfg.sync_schedule,
        )

        commit_audit(
            "ansible.schedule.save",
            details=f"sync_enabled={sync_enabled} schedule={cfg.sync_schedule}",
            result="success",
        )
        return jsonify({"success": True, "message": "Schedule saved."})
    except Exception as exc:
        db.session.rollback()
        logger.exception("Failed to save Ansible schedule")
        return jsonify({"success": False, "message": str(exc)})

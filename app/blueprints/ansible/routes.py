"""
Ansible integration blueprint routes.

All routes live under /settings/ansible/… to sit alongside other
settings sections.  The blueprint is registered with no url_prefix.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import jsonify, flash, redirect, request, url_for
from flask_login import login_required

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
    """AJAX: test SSH connectivity and Ansible installation. Returns JSON."""
    cfg = _get_cfg()
    if cfg is None:
        return jsonify({"success": False, "message": "No Ansible configuration found."})

    host = (request.form.get("control_node") or cfg.control_node or "").strip()
    if not host:
        return jsonify({"success": False, "message": "Control node host is required."})

    svc    = _build_service(cfg, form=request.form)
    result = svc.test_connection()

    # Persist status and version info — never the credentials
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

    commit_audit(
        "ansible.connection.test",
        target=host,
        details=f"result={result['status']}",
    )

    return jsonify({
        "success": result["success"],
        "status":  result["status"],
        "message": result["message"],
        "ansible_version": result.get("ansible_version"),
        "python_version":  result.get("python_version"),
        "checks":          result.get("checks", []),
    })


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

    # If successful, persist hosts into AnsibleInventoryHost table
    if result["success"] and result.get("hosts"):
        try:
            now = datetime.now(timezone.utc)
            # Replace all existing host records
            AnsibleInventoryHost.query.delete()
            for hostname in result["hosts"]:
                # Determine which groups this host belongs to
                groups = [
                    g for g, hosts in result.get("raw_groups", {}).items()
                    if hostname in hosts
                ]
                db.session.add(AnsibleInventoryHost(
                    hostname     = hostname,
                    groups       = ", ".join(sorted(groups)) if groups else None,
                    discovered_at = now,
                ))
            # Update config stats
            cfg.last_inventory_hosts = result["host_count"]
            cfg.last_validation_at   = now
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.warning("Failed to persist Ansible inventory hosts: %s", exc)

    commit_audit(
        "ansible.inventory.validate",
        details=(
            f"success={result['success']} "
            f"hosts={result['host_count']} "
            f"groups={len(result['group_names'])}"
        ),
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

    svc       = _build_service(cfg, form=request.form)
    playbooks = svc.discover_playbooks()

    # Persist playbook count to config
    try:
        cfg.last_playbooks_found = len(playbooks)
        db.session.commit()
    except Exception:
        db.session.rollback()

    commit_audit(
        "ansible.playbooks.discover",
        details=f"found={len(playbooks)}",
    )

    return jsonify({
        "success":   True,
        "count":     len(playbooks),
        "playbooks": playbooks,
    })

"""Settings blueprint routes — thin controllers only.

All database logic lives in queries.py.
Settings contains: Locations, Environments, Owners, Directory Services, API/Ansible Integration.
User Management is in the dedicated Users blueprint (/users).
"""
import logging

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required

from . import settings_bp
from .queries import (
    VALID_COLORS,
    add_environment,
    add_group_mapping,
    add_location,
    add_owner,
    delete_environment,
    delete_group_mapping,
    delete_location,
    delete_owner,
    edit_environment,
    edit_location,
    edit_owner,
    generate_api_token,
    get_settings_data,
    revoke_api_token,
    save_directory_config,
    toggle_directory_auth,
)
from ...audit import commit_audit
from ...freeipa import FreeIPAService
from ...models.directory_config import DIRECTORY_TYPES, DEFAULT_USER_FILTERS, DEFAULT_GROUP_FILTERS
from ...models.ldap_group_mapping import VALID_ROLES as MAPPING_VALID_ROLES

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _render_settings(new_token: str | None = None):
    data = get_settings_data()
    return render_template(
        "settings/index.html",
        locations           = data.locations,
        environments        = data.environments,
        owners              = data.owners,
        api_token           = data.api_token,
        new_token           = new_token,
        dir_config          = data.dir_config,
        group_mappings      = data.group_mappings,
        valid_colors        = VALID_COLORS,
        directory_types     = DIRECTORY_TYPES,
        mapping_valid_roles = MAPPING_VALID_ROLES,
        default_user_filters  = DEFAULT_USER_FILTERS,
        default_group_filters = DEFAULT_GROUP_FILTERS,
        app_name    = current_app.config["APP_NAME"],
        app_version = current_app.config["APP_VERSION"],
        app_base_url = current_app.config.get("APP_BASE_URL", "https://your-domain.example.com"),
    )


# ── Settings overview ─────────────────────────────────────────────────────── #

@settings_bp.route("/settings", methods=["GET"])
@login_required
def index():
    return _render_settings()


# ── Locations ─────────────────────────────────────────────────────────────── #

@settings_bp.route("/settings/locations/add", methods=["POST"])
@login_required
def add_location_route():
    name = request.form.get("name", "").strip()
    result = add_location(name=name, description=request.form.get("description", ""))
    if result.success:
        flash("Location added successfully.", "success")
        commit_audit("settings.location.add", target=name)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#locations")


@settings_bp.route("/settings/locations/<int:location_id>/edit", methods=["POST"])
@login_required
def edit_location_route(location_id: int):
    name = request.form.get("name", "").strip()
    result = edit_location(
        location_id=location_id, name=name,
        description=request.form.get("description", ""),
        is_active=request.form.get("is_active") == "1",
    )
    if result.success:
        flash("Location updated successfully.", "success")
        commit_audit("settings.location.edit", target=name)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#locations")


@settings_bp.route("/settings/locations/<int:location_id>/delete", methods=["POST"])
@login_required
def delete_location_route(location_id: int):
    result = delete_location(location_id)
    if result.success:
        flash("Location deleted.", "success")
        commit_audit("settings.location.delete", target=result.name)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#locations")


# ── Environments ──────────────────────────────────────────────────────────── #

@settings_bp.route("/settings/environments/add", methods=["POST"])
@login_required
def add_environment_route():
    name = request.form.get("name", "").strip()
    result = add_environment(name=name, label=request.form.get("label", ""), color=request.form.get("color", "secondary"))
    if result.success:
        flash("Environment added successfully.", "success")
        commit_audit("settings.environment.add", target=name)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#environments")


@settings_bp.route("/settings/environments/<int:env_id>/edit", methods=["POST"])
@login_required
def edit_environment_route(env_id: int):
    name = request.form.get("name", "").strip()
    result = edit_environment(
        env_id=env_id, name=name,
        label=request.form.get("label", ""),
        color=request.form.get("color", "secondary"),
        is_active=request.form.get("is_active") == "1",
    )
    if result.success:
        flash("Environment updated successfully.", "success")
        commit_audit("settings.environment.edit", target=name)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#environments")


@settings_bp.route("/settings/environments/<int:env_id>/delete", methods=["POST"])
@login_required
def delete_environment_route(env_id: int):
    result = delete_environment(env_id)
    if result.success:
        flash("Environment deleted.", "success")
        commit_audit("settings.environment.delete", target=result.name)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#environments")


# ── Owners ────────────────────────────────────────────────────────────────── #

@settings_bp.route("/settings/owners/add", methods=["POST"])
@login_required
def add_owner_route():
    name = request.form.get("name", "").strip()
    result = add_owner(name=name, email=request.form.get("email", ""))
    if result.success:
        flash("Owner added successfully.", "success")
        commit_audit("settings.owner.add", target=name)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#owners")


@settings_bp.route("/settings/owners/<int:owner_id>/edit", methods=["POST"])
@login_required
def edit_owner_route(owner_id: int):
    name = request.form.get("name", "").strip()
    result = edit_owner(
        owner_id=owner_id, name=name,
        email=request.form.get("email", ""),
        is_active=request.form.get("is_active") == "1",
    )
    if result.success:
        flash("Owner updated successfully.", "success")
        commit_audit("settings.owner.edit", target=name)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#owners")


@settings_bp.route("/settings/owners/<int:owner_id>/delete", methods=["POST"])
@login_required
def delete_owner_route(owner_id: int):
    result = delete_owner(owner_id)
    if result.success:
        flash("Owner deleted.", "success")
        commit_audit("settings.owner.delete", target=result.name)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#owners")


# ── API Token ──────────────────────────────────────────────────────────────── #

@settings_bp.route("/settings/api-token/generate", methods=["POST"])
@login_required
def generate_api_token_route():
    result, raw_token = generate_api_token()
    if result.success:
        flash("API token generated. Copy it now — it will not be shown again.", "success")
        commit_audit("settings.api_token.generate", target="API token")
        return _render_settings(new_token=raw_token)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#api-settings")


@settings_bp.route("/settings/api-token/revoke", methods=["POST"])
@login_required
def revoke_api_token_route():
    result = revoke_api_token()
    if result.success:
        flash("API token revoked.", "warning")
        commit_audit("settings.api_token.revoke", target="API token")
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#api-settings")


# ── Directory Services ─────────────────────────────────────────────────────── #

@settings_bp.route("/settings/directory/save", methods=["POST"])
@login_required
def save_directory_route():
    """Save the directory configuration and enable directory auth."""
    result = save_directory_config(request.form)
    if result.success:
        flash("Directory configuration saved and enabled.", "success")
        commit_audit("settings.directory.save", target=request.form.get("uri", ""))
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#directory-services")


@settings_bp.route("/settings/directory/toggle", methods=["POST"])
@login_required
def toggle_directory_route():
    """Enable or disable directory authentication."""
    enabled = request.form.get("enabled") == "1"
    result  = toggle_directory_auth(enabled)
    if result.success:
        state = "enabled" if enabled else "disabled"
        flash(f"Directory authentication {state}.", "success")
        commit_audit(f"settings.directory.{'enable' if enabled else 'disable'}")
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#directory-services")


@settings_bp.route("/settings/directory/test", methods=["POST"])
@login_required
def test_directory_connection():
    """AJAX: test the directory service-account bind."""
    svc    = FreeIPAService.from_db()
    result = svc.test_connection()
    if result.success:
        from datetime import datetime
        from ...models.directory_config import DirectoryConfig
        from ...extensions import db as _db
        cfg = DirectoryConfig.get()
        if cfg:
            cfg.last_connected_at = datetime.utcnow()
            try:
                _db.session.commit()
            except Exception:
                _db.session.rollback()
    commit_audit(
        "settings.directory.test_connection",
        target  = result.server,
        details = f"success={result.success}: {result.message}",
    )
    return jsonify({
        "success": result.success,
        "message": result.message,
        "server":  result.server,
        "base_dn": result.base_dn,
    })


@settings_bp.route("/settings/directory/group-mappings/add", methods=["POST"])
@login_required
def add_group_mapping_route():
    group_dn = request.form.get("group_dn", "").strip()
    role     = request.form.get("role", "operator").strip()
    result   = add_group_mapping(group_dn=group_dn, role=role)
    if result.success:
        flash("Group mapping added.", "success")
        commit_audit("settings.directory.group_mapping.add", target=group_dn, details=f"role={role}")
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#directory-services")


@settings_bp.route("/settings/directory/group-mappings/<int:mapping_id>/delete", methods=["POST"])
@login_required
def delete_group_mapping_route(mapping_id: int):
    result = delete_group_mapping(mapping_id)
    if result.success:
        flash("Group mapping deleted.", "success")
        commit_audit("settings.directory.group_mapping.delete", target=result.name)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#directory-services")

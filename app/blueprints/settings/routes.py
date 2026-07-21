"""Settings blueprint routes — thin controllers only.

All database logic lives in queries.py.
"""
import logging

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from . import settings_bp
from .queries import (
    VALID_COLORS,
    add_environment,
    add_location,
    add_owner,
    add_user,
    change_password,
    delete_environment,
    delete_location,
    delete_owner,
    delete_user,
    edit_environment,
    edit_location,
    edit_owner,
    generate_api_token,
    get_settings_data,
    revoke_api_token,
    toggle_user_active,
)
from ...audit import commit_audit
from ...freeipa import FreeIPAService

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _freeipa_info() -> dict:
    """Build FreeIPA status dict for the settings template."""
    cfg = current_app.config
    enabled = str(cfg.get("FREEIPA_ENABLED", "false")).lower() == "true"
    return {
        "enabled":      enabled,
        "uri":          cfg.get("FREEIPA_URI", "") if enabled else "",
        "base_dn":      cfg.get("FREEIPA_BASE_DN", "") if enabled else "",
        "bind_dn":      cfg.get("FREEIPA_BIND_DN", "") if enabled else "",
        "verify_cert":  str(cfg.get("FREEIPA_VERIFY_CERT", "true")).lower() != "false",
    }


def _render_settings(new_token: str | None = None):
    data = get_settings_data()
    return render_template(
        "settings/index.html",
        locations=data.locations,
        environments=data.environments,
        owners=data.owners,
        users=data.users,
        api_token=data.api_token,
        new_token=new_token,
        valid_colors=VALID_COLORS,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
        app_base_url=current_app.config.get("APP_BASE_URL", "https://your-domain.example.com"),
        freeipa=_freeipa_info(),
    )


# ── Settings overview ─────────────────────────────────────────────────────── #

@settings_bp.route("/settings", methods=["GET"])
def index():
    """Settings overview — manage locations, environments, owners, users, and API token."""
    return _render_settings()


# ── Locations ─────────────────────────────────────────────────────────────── #

@settings_bp.route("/settings/locations/add", methods=["POST"])
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
def edit_location_route(location_id: int):
    name = request.form.get("name", "").strip()
    result = edit_location(
        location_id=location_id,
        name=name,
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
def add_environment_route():
    name = request.form.get("name", "").strip()
    result = add_environment(
        name=name,
        label=request.form.get("label", ""),
        color=request.form.get("color", "secondary"),
    )
    if result.success:
        flash("Environment added successfully.", "success")
        commit_audit("settings.environment.add", target=name)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#environments")


@settings_bp.route("/settings/environments/<int:env_id>/edit", methods=["POST"])
def edit_environment_route(env_id: int):
    name = request.form.get("name", "").strip()
    result = edit_environment(
        env_id=env_id,
        name=name,
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
def edit_owner_route(owner_id: int):
    name = request.form.get("name", "").strip()
    result = edit_owner(
        owner_id=owner_id,
        name=name,
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
def delete_owner_route(owner_id: int):
    result = delete_owner(owner_id)
    if result.success:
        flash("Owner deleted.", "success")
        commit_audit("settings.owner.delete", target=result.name)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#owners")


# ── API Token ──────────────────────────────────────────────────────────── #

@settings_bp.route("/settings/api-token/generate", methods=["POST"])
def generate_api_token_route():
    """Generate (or regenerate) the API bearer token."""
    result, raw_token = generate_api_token()
    if result.success:
        flash("API token generated. Copy it now — it will not be shown again.", "success")
        commit_audit("settings.api_token.generate", target="API token")
        return _render_settings(new_token=raw_token)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#api-settings")


@settings_bp.route("/settings/api-token/revoke", methods=["POST"])
def revoke_api_token_route():
    """Revoke the active API token."""
    result = revoke_api_token()
    if result.success:
        flash("API token revoked. Ansible pushes will be rejected until a new token is generated.", "warning")
        commit_audit("settings.api_token.revoke", target="API token")
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#api-settings")


# ── User Management ────────────────────────────────────────────────────── #

@settings_bp.route("/settings/users/add", methods=["POST"])
def add_user_route():
    username = request.form.get("username", "").strip()
    result = add_user(username=username, password=request.form.get("password", ""))
    if result.success:
        flash("User account created successfully.", "success")
        commit_audit("settings.user.add", target=username)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#users")


@settings_bp.route("/settings/users/<int:user_id>/change-password", methods=["POST"])
def change_password_route(user_id: int):
    result = change_password(user_id=user_id, new_password=request.form.get("password", ""))
    if result.success:
        flash("Password updated successfully.", "success")
        commit_audit("settings.user.change_password", target=f"user id={user_id}")
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#users")


@settings_bp.route("/settings/users/<int:user_id>/toggle-active", methods=["POST"])
def toggle_user_active_route(user_id: int):
    is_active = request.form.get("is_active") == "1"
    result = toggle_user_active(
        user_id=user_id,
        is_active=is_active,
        current_user_id=current_user.id,
    )
    if result.success:
        state = "activated" if is_active else "deactivated"
        flash(f"User account {state}.", "success")
        commit_audit(
            "settings.user.activate" if is_active else "settings.user.deactivate",
            target=f"user id={user_id}",
        )
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#users")


@settings_bp.route("/settings/users/<int:user_id>/delete", methods=["POST"])
def delete_user_route(user_id: int):
    result = delete_user(user_id=user_id, current_user_id=current_user.id)
    if result.success:
        flash("User account deleted.", "success")
        commit_audit("settings.user.delete", target=result.name)
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#users")


# ── FreeIPA / Authentication ───────────────────────────────────────────── #

@settings_bp.route("/settings/freeipa/test", methods=["POST"])
def test_freeipa_connection():
    """AJAX endpoint: test the FreeIPA service-account bind and return JSON."""
    svc = FreeIPAService(current_app.config)
    result = svc.test_connection()
    commit_audit(
        "settings.freeipa.test_connection",
        target=current_app.config.get("FREEIPA_URI", ""),
        details=f"success={result.success}: {result.message}",
    )
    return jsonify({
        "success": result.success,
        "message": result.message,
        "server":  result.server,
        "base_dn": result.base_dn,
    })

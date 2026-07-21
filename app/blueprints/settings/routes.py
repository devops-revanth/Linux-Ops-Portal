"""Settings blueprint routes — thin controllers only.

All database logic lives in queries.py.
"""
import logging

from flask import current_app, flash, redirect, render_template, request, url_for

from . import settings_bp
from .queries import (
    VALID_COLORS,
    add_environment,
    add_location,
    add_owner,
    delete_environment,
    delete_location,
    delete_owner,
    edit_environment,
    edit_location,
    edit_owner,
    get_settings_data,
)

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _render_settings():
    data = get_settings_data()
    return render_template(
        "settings/index.html",
        locations=data.locations,
        environments=data.environments,
        owners=data.owners,
        valid_colors=VALID_COLORS,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


# ── Settings overview ─────────────────────────────────────────────────────── #

@settings_bp.route("/settings", methods=["GET"])
def index():
    """Settings overview — manage locations, environments, and owners."""
    return _render_settings()


# ── Locations ─────────────────────────────────────────────────────────────── #

@settings_bp.route("/settings/locations/add", methods=["POST"])
def add_location_route():
    result = add_location(
        name=request.form.get("name", ""),
        description=request.form.get("description", ""),
    )
    if result.success:
        flash("Location added successfully.", "success")
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#locations")


@settings_bp.route("/settings/locations/<int:location_id>/edit", methods=["POST"])
def edit_location_route(location_id: int):
    result = edit_location(
        location_id=location_id,
        name=request.form.get("name", ""),
        description=request.form.get("description", ""),
        is_active=request.form.get("is_active") == "1",
    )
    if result.success:
        flash("Location updated successfully.", "success")
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#locations")


@settings_bp.route("/settings/locations/<int:location_id>/delete", methods=["POST"])
def delete_location_route(location_id: int):
    result = delete_location(location_id)
    if result.success:
        flash("Location deleted.", "success")
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#locations")


# ── Environments ──────────────────────────────────────────────────────────── #

@settings_bp.route("/settings/environments/add", methods=["POST"])
def add_environment_route():
    result = add_environment(
        name=request.form.get("name", ""),
        label=request.form.get("label", ""),
        color=request.form.get("color", "secondary"),
    )
    if result.success:
        flash("Environment added successfully.", "success")
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#environments")


@settings_bp.route("/settings/environments/<int:env_id>/edit", methods=["POST"])
def edit_environment_route(env_id: int):
    result = edit_environment(
        env_id=env_id,
        name=request.form.get("name", ""),
        label=request.form.get("label", ""),
        color=request.form.get("color", "secondary"),
        is_active=request.form.get("is_active") == "1",
    )
    if result.success:
        flash("Environment updated successfully.", "success")
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#environments")


@settings_bp.route("/settings/environments/<int:env_id>/delete", methods=["POST"])
def delete_environment_route(env_id: int):
    result = delete_environment(env_id)
    if result.success:
        flash("Environment deleted.", "success")
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#environments")


# ── Owners ────────────────────────────────────────────────────────────────── #

@settings_bp.route("/settings/owners/add", methods=["POST"])
def add_owner_route():
    result = add_owner(
        name=request.form.get("name", ""),
        email=request.form.get("email", ""),
    )
    if result.success:
        flash("Owner added successfully.", "success")
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#owners")


@settings_bp.route("/settings/owners/<int:owner_id>/edit", methods=["POST"])
def edit_owner_route(owner_id: int):
    result = edit_owner(
        owner_id=owner_id,
        name=request.form.get("name", ""),
        email=request.form.get("email", ""),
        is_active=request.form.get("is_active") == "1",
    )
    if result.success:
        flash("Owner updated successfully.", "success")
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#owners")


@settings_bp.route("/settings/owners/<int:owner_id>/delete", methods=["POST"])
def delete_owner_route(owner_id: int):
    result = delete_owner(owner_id)
    if result.success:
        flash("Owner deleted.", "success")
    else:
        flash(result.error, "danger")
    return redirect(url_for("settings.index") + "#owners")

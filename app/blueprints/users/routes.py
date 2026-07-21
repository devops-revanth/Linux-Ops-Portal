"""User Management blueprint routes."""
from __future__ import annotations

import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import users_bp
from .queries import (
    VALID_ROLES,
    UserFilters,
    add_local_user,
    change_password,
    delete_user,
    edit_role,
    get_user,
    get_users_page,
    toggle_user_active,
)
from ...audit import commit_audit

logger = logging.getLogger(__name__)


# ── Index ─────────────────────────────────────────────────────────────────── #

@users_bp.route("/users")
@login_required
def index():
    """User list — searchable, filterable, sortable, paginated."""
    filters    = UserFilters.from_request(request.args)
    pagination = get_users_page(filters)
    return render_template(
        "users/index.html",
        filters    = filters,
        pagination = pagination,
        users      = pagination.items if pagination else [],
        valid_roles = VALID_ROLES,
    )


# ── Add local user ────────────────────────────────────────────────────────── #

@users_bp.route("/users/add", methods=["POST"])
@login_required
def add_user_route():
    username = request.form.get("username", "").strip()
    role     = request.form.get("role", "operator").strip()
    result   = add_local_user(
        username = username,
        password = request.form.get("password", ""),
        role     = role,
    )
    if result.success:
        flash("User account created successfully.", "success")
        commit_audit("users.add", target=username, details=f"role={role}")
    else:
        flash(result.error, "danger")
    return redirect(url_for("users.index"))


# ── Change password ───────────────────────────────────────────────────────── #

@users_bp.route("/users/<int:user_id>/change-password", methods=["POST"])
@login_required
def change_password_route(user_id: int):
    result = change_password(user_id=user_id, new_password=request.form.get("password", ""))
    if result.success:
        flash("Password updated successfully.", "success")
        commit_audit("users.change_password", target=f"user id={user_id}")
    else:
        flash(result.error, "danger")
    return redirect(url_for("users.index"))


# ── Edit role ─────────────────────────────────────────────────────────────── #

@users_bp.route("/users/<int:user_id>/edit-role", methods=["POST"])
@login_required
def edit_role_route(user_id: int):
    new_role = request.form.get("role", "").strip()
    user     = get_user(user_id)
    result   = edit_role(user_id=user_id, new_role=new_role)
    if result.success:
        flash("Role updated successfully.", "success")
        commit_audit(
            "users.edit_role",
            target  = user.username if user else f"id={user_id}",
            details = f"role={new_role}",
        )
    else:
        flash(result.error, "danger")
    return redirect(url_for("users.index"))


# ── Toggle active ─────────────────────────────────────────────────────────── #

@users_bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@login_required
def toggle_active_route(user_id: int):
    is_active = request.form.get("is_active") == "1"
    result = toggle_user_active(
        user_id=user_id, is_active=is_active, current_user_id=current_user.id
    )
    if result.success:
        state = "activated" if is_active else "deactivated"
        flash(f"User account {state}.", "success")
        commit_audit(
            f"users.{'activate' if is_active else 'deactivate'}",
            target=f"user id={user_id}",
        )
    else:
        flash(result.error, "danger")
    return redirect(url_for("users.index"))


# ── Delete ────────────────────────────────────────────────────────────────── #

@users_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user_route(user_id: int):
    result = delete_user(user_id=user_id, current_user_id=current_user.id)
    if result.success:
        flash("User account deleted.", "success")
        commit_audit("users.delete", target=result.name)
    else:
        flash(result.error, "danger")
    return redirect(url_for("users.index"))

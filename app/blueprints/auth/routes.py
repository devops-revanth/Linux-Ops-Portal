"""
Auth blueprint routes — login and logout.

Login flow:
  1. If FreeIPA is enabled, attempt LDAP authentication first.
     On success: create / update the local User row, then log in.
  2. Fall back to local password check (covers the emergency admin and
     any account explicitly set as auth_source="local").

Logout always clears the Flask-Login session.
"""
import logging
from datetime import datetime, timezone

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length
from flask_wtf import FlaskForm

from ...extensions import db
from ...models.user import User
from . import auth_bp

logger = logging.getLogger(__name__)


# ── WTForms login form ────────────────────────────────────────────────── #

class LoginForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[DataRequired(), Length(min=1, max=64)],
        render_kw={"placeholder": "admin", "autocomplete": "username"},
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired()],
        render_kw={"placeholder": "••••••••", "autocomplete": "current-password"},
    )
    remember_me = BooleanField("Remember me")
    submit = SubmitField("Sign in")


# ── FreeIPA helper ────────────────────────────────────────────────────── #

def _try_freeipa_login(username: str, password: str) -> "User | None":
    """
    Attempt FreeIPA LDAP authentication.

    On success: upsert the local User record (syncing role / display_name /
    email) and return it.  Returns None if FreeIPA is disabled, the user is
    not found, or the password is wrong.
    """
    from ...freeipa import FreeIPAService

    svc = FreeIPAService(current_app.config)
    if not svc.enabled:
        return None

    result = svc.authenticate(username, password)
    if not result.success:
        if result.error and "not found" not in result.error.lower():
            # Log LDAP errors that are not "user not found" — they may indicate
            # a misconfiguration or server problem.
            logger.warning("FreeIPA auth error for '%s': %s", username, result.error)
        return None

    # Upsert local User row — keep auth_source="ldap" to distinguish from local
    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(username=username, auth_source="ldap")
        user.set_unusable_password()
        db.session.add(user)
        logger.info("FreeIPA: auto-created local user record for '%s'", username)

    # Sync LDAP attributes on every login so changes propagate immediately
    user.role         = result.role
    user.display_name = result.display_name or None
    user.email        = result.email or None
    user.auth_source  = "ldap"
    user.last_login   = datetime.now(timezone.utc)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to upsert LDAP user record for '%s'", username)
        return None

    return user


# ── Routes ────────────────────────────────────────────────────────────── #

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Render login form (GET) or authenticate (POST)."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    if form.validate_on_submit():
        raw_username = form.username.data.strip()
        raw_password = form.password.data

        authenticated_user = None

        # ── Step 1: FreeIPA (LDAP) ────────────────────────────────────── #
        authenticated_user = _try_freeipa_login(raw_username, raw_password)

        # ── Step 2: Local fallback ────────────────────────────────────── #
        if authenticated_user is None:
            local_user = User.query.filter_by(username=raw_username).first()
            if local_user and local_user.is_active and local_user.check_password(raw_password):
                # Update last_login for local accounts too
                local_user.last_login = datetime.now(timezone.utc)
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                authenticated_user = local_user

        # ── Evaluate result ───────────────────────────────────────────── #
        if authenticated_user and authenticated_user.is_active:
            login_user(authenticated_user, remember=form.remember_me.data)
            logger.info(
                "User '%s' logged in from %s (source=%s)",
                authenticated_user.username,
                request.remote_addr,
                authenticated_user.auth_source,
            )
            next_page = request.args.get("next", "")
            if next_page and next_page.startswith("/") and not next_page.startswith("//"):
                return redirect(next_page)
            return redirect(url_for("dashboard.index"))
        else:
            logger.warning(
                "Failed login attempt for username='%s' from %s",
                raw_username, request.remote_addr,
            )
            flash("Invalid username or password.", "danger")

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
def logout():
    """Log out the current user and redirect to the login page."""
    username = current_user.username if current_user.is_authenticated else "unknown"
    logout_user()
    logger.info("User '%s' logged out", username)
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))

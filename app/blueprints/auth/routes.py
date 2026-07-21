"""
Auth blueprint routes — login and logout.

Login/logout endpoints are intentionally exempt from @login_required;
they must be reachable by unauthenticated users.
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length

from flask_wtf import FlaskForm

from ...models.user import User
from . import auth_bp

logger = logging.getLogger(__name__)


# ── WTForms login form ───────────────────────────────────────────────── #

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


# ── Routes ────────────────────────────────────────────────────────────── #

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Render login form (GET) or authenticate (POST)."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()
        if user and user.is_active and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            logger.info("User '%s' logged in from %s", user.username, request.remote_addr)
            # Honour the ?next= param but only if it's a relative URL (security)
            next_page = request.args.get("next", "")
            if next_page and next_page.startswith("/") and not next_page.startswith("//"):
                return redirect(next_page)
            return redirect(url_for("dashboard.index"))
        else:
            logger.warning(
                "Failed login attempt for username='%s' from %s",
                form.username.data, request.remote_addr,
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

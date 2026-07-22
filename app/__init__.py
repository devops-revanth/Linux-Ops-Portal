"""
Linux Operations Portal – Application Factory.

Usage:
    from app import create_app
    app = create_app("development")
"""
import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask

from .config import config
from .extensions import csrf, db, login_manager, migrate


def create_app(config_name: str | None = None) -> Flask:
    """
    Create and configure the Flask application.

    Args:
        config_name: One of 'development', 'production', 'testing'.
                     Falls back to the FLASK_ENV environment variable,
                     then to 'development'.

    Returns:
        A fully configured Flask application instance.
    """
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config[config_name])

    # ------------------------------------------------------------------ #
    # Logging (must happen before anything that uses app.logger)
    # ------------------------------------------------------------------ #
    _configure_logging(app)

    # ------------------------------------------------------------------ #
    # Extensions
    # ------------------------------------------------------------------ #
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Flask-Login
    login_manager.login_view = "auth.login"          # redirect destination
    login_manager.login_message = "Please sign in to access this page."
    login_manager.login_message_category = "warning"
    login_manager.init_app(app)

    # ------------------------------------------------------------------ #
    # Models – import so Alembic / Flask-Migrate can detect them
    # ------------------------------------------------------------------ #
    with app.app_context():
        from .models import (  # noqa: F401
            environment,
            location,
            note,
            owner,
            package,
            patching,
            server,
            user,
            vmware_config,
            vmware_connection,
            vmware_server_meta,
            ansible_config,
        )

        # User loader for Flask-Login
        from .models.user import User

        @login_manager.user_loader
        def load_user(user_id: str):  # noqa: ANN202
            return User.query.get(int(user_id))

        # Seed reference data on first run (idempotent).
        # Wrapped in try/except so flask db upgrade can import the app
        # before the schema has been applied.
        try:
            from .seeder import seed_all  # noqa: E402
            seed_all()
        except Exception as exc:  # noqa: BLE001
            app.logger.debug("Seeder skipped (tables not ready yet): %s", exc)

    # ------------------------------------------------------------------ #
    # Blueprints
    # ------------------------------------------------------------------ #
    from .blueprints.api import api_bp          # noqa: E402
    from .blueprints.audit import audit_bp      # noqa: E402
    from .blueprints.auth import auth_bp        # noqa: E402
    from .blueprints.dashboard import dashboard_bp  # noqa: E402
    from .blueprints.inventory import inventory_bp  # noqa: E402
    from .blueprints.main import main_bp        # noqa: E402
    from .blueprints.packages import packages_bp  # noqa: E402
    from .blueprints.reports import reports_bp  # noqa: E402
    from .blueprints.search import search_bp    # noqa: E402
    from .blueprints.settings import settings_bp  # noqa: E402
    from .blueprints.users import users_bp      # noqa: E402
    from .blueprints.vmware import vmware_bp    # noqa: E402
    from .blueprints.ansible import ansible_bp  # noqa: E402
    from .blueprints.ops import ops_bp          # noqa: E402

    app.register_blueprint(api_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(packages_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(vmware_bp)
    app.register_blueprint(ansible_bp)
    app.register_blueprint(ops_bp)

    # ------------------------------------------------------------------ #
    # Error handlers
    # ------------------------------------------------------------------ #
    _register_error_handlers(app)

    # ------------------------------------------------------------------ #
    # Jinja2 filters and context processors
    # ------------------------------------------------------------------ #
    _register_template_helpers(app)

    # ------------------------------------------------------------------ #
    # Background scheduler (VMware scheduled sync)
    # ------------------------------------------------------------------ #
    try:
        from .scheduler import init_scheduler
        init_scheduler(app)
    except Exception as _sched_exc:
        app.logger.debug("Scheduler init skipped: %s", _sched_exc)

    app.logger.info(
        "LOP started  env=%s  debug=%s", config_name, app.debug
    )

    return app


# --------------------------------------------------------------------------- #
# Private helpers
# --------------------------------------------------------------------------- #

def _register_template_helpers(app: Flask) -> None:
    """Register Jinja2 filters and context processors for timestamp display."""
    from datetime import datetime as _dt, timezone as _utc
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # Python 3.9+
    from .models.localization_config import (
        DATE_FORMAT_STRFTIME, TIME_FORMAT_STRFTIME,
    )

    def _get_regional_cfg():
        """Return (tz_name, date_fmt_key, time_fmt_key), cached on g per request."""
        import flask
        cached = flask.g.get("_lop_regional")
        if cached is None:
            try:
                from .models.localization_config import LocalizationConfig
                cfg = LocalizationConfig.get()
                cached = (cfg.timezone, cfg.date_format, cfg.time_format)
            except Exception:
                cached = ("UTC", "MMM_DD_YYYY", "12")
            flask.g._lop_regional = cached
        return cached

    def _to_local(dt) -> "_dt | None":
        """Convert a UTC-stored datetime to the configured local timezone."""
        if not isinstance(dt, _dt):
            return None
        tz_name, _, _ = _get_regional_cfg()
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, Exception):
            tz = ZoneInfo("UTC")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_utc.utc)
        return dt.astimezone(tz)

    def lop_ts(dt, date_only: bool = False) -> str:
        """
        Format a UTC datetime using the configured regional settings.

        Full (12h):  "Jul 21, 2026 08:55 AM CDT"
        Full (24h):  "21/07/2026 20:55 CDT"
        Date only:   "Jul 21, 2026"  (uses configured date format)
        """
        local = _to_local(dt)
        if local is None:
            return "—"
        _, date_key, time_key = _get_regional_cfg()
        date_fmt = DATE_FORMAT_STRFTIME.get(date_key, "%b %d, %Y")
        if date_only:
            return local.strftime(date_fmt)
        time_fmt = TIME_FORMAT_STRFTIME.get(time_key, "%I:%M %p")
        return local.strftime(f"{date_fmt} {time_fmt} %Z")

    def lop_rel(dt) -> str:
        """Return a relative time string such as '19 days ago'."""
        local = _to_local(dt)
        if local is None:
            return ""
        diff = _dt.now(_utc.utc) - local.astimezone(_utc.utc)
        days = diff.days
        if days <= 0:
            return "today"
        if days == 1:
            return "1 day ago"
        if days < 30:
            return f"{days} days ago"
        if days < 60:
            return "1 month ago"
        if days < 365:
            return f"{days // 30} months ago"
        yrs = days // 365
        return f"{yrs} year{'s' if yrs > 1 else ''} ago"

    def lop_time(dt) -> str:
        """
        Return just the time portion (with TZ abbreviation) in the configured
        time format, e.g. '08:55 AM CDT'  or  '20:55 CDT'.
        """
        local = _to_local(dt)
        if local is None:
            return "—"
        _, _, time_key = _get_regional_cfg()
        time_fmt = TIME_FORMAT_STRFTIME.get(time_key, "%I:%M %p")
        return local.strftime(f"{time_fmt} %Z")

    app.jinja_env.filters["lop_ts"]   = lop_ts
    app.jinja_env.filters["lop_dt"]   = lop_ts   # alias used in ops templates
    app.jinja_env.filters["lop_time"] = lop_time
    app.jinja_env.filters["lop_rel"]  = lop_rel

    @app.context_processor
    def _inject_lop_tz():
        """Inject lop_tz (IANA name) into every template context."""
        try:
            tz_name, _, _ = _get_regional_cfg()
            return {"lop_tz": tz_name}
        except Exception:
            return {"lop_tz": "UTC"}


def _configure_logging(app: Flask) -> None:
    """
    Set up structured logging.

    - Console handler: always active.
    - Rotating file handler: active in non-testing environments.
    """
    log_level = getattr(logging, app.config.get("LOG_LEVEL", "INFO"), logging.INFO)
    fmt = logging.Formatter(
        app.config["LOG_FORMAT"],
        datefmt=app.config["LOG_DATE_FORMAT"],
    )

    # Console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.setLevel(log_level)

    # File (skip during tests to avoid creating log files)
    handlers: list[logging.Handler] = [console_handler]
    if not app.config.get("TESTING"):
        log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "lop.log"),
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=5,
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(log_level)
        handlers.append(file_handler)

    logging.basicConfig(level=log_level, handlers=handlers)
    app.logger.setLevel(log_level)


def _register_error_handlers(app: Flask) -> None:
    """Register custom HTTP error pages."""
    from flask import render_template

    @app.errorhandler(401)
    def unauthorized(exc):  # noqa: ANN001
        return render_template("errors/401.html"), 401

    @app.errorhandler(403)
    def forbidden(exc):  # noqa: ANN001
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(exc):  # noqa: ANN001
        app.logger.warning("404  path=%s", exc)
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(exc):  # noqa: ANN001
        app.logger.error("500  error=%s", exc, exc_info=True)
        return render_template("errors/500.html"), 500

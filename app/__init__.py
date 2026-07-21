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
    from .blueprints.patching import patching_bp  # noqa: E402
    from .blueprints.reports import reports_bp  # noqa: E402
    from .blueprints.search import search_bp    # noqa: E402
    from .blueprints.settings import settings_bp  # noqa: E402
    from .blueprints.users import users_bp      # noqa: E402

    app.register_blueprint(api_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(patching_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(users_bp)

    # ------------------------------------------------------------------ #
    # Error handlers
    # ------------------------------------------------------------------ #
    _register_error_handlers(app)

    app.logger.info(
        "LOP started  env=%s  debug=%s", config_name, app.debug
    )

    return app


# --------------------------------------------------------------------------- #
# Private helpers
# --------------------------------------------------------------------------- #

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

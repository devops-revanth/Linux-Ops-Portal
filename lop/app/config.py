"""
Configuration management for Linux Operations Portal.

Three environments are supported:
  development  – debug mode, verbose logging
  production   – gunicorn-ready, strict settings
  testing      – in-memory SQLite, no side-effects
"""
import os
from dotenv import load_dotenv

# Load .env from the project root (lop/) when running locally
load_dotenv()


class Config:
    """Base configuration shared by all environments."""

    # ------------------------------------------------------------------ #
    # Security
    # ------------------------------------------------------------------ #
    # Read SECRET_KEY first; fall back to SESSION_SECRET (Replit managed
    # secret) so the value is never stored as a plaintext env var.
    SECRET_KEY: str = (
        os.environ.get("SECRET_KEY")
        or os.environ.get("SESSION_SECRET")
        or "change-me-in-production"
    )

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    # Replit provides DATABASE_URL as "postgresql://..." — normalize any
    # legacy "postgres://" prefix that psycopg2 does not accept.
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL",
        "postgresql://lop_user:lop_pass@db:5432/lop_db",
    ).replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        "pool_pre_ping": True,   # Reconnect on stale connections
        "pool_recycle": 300,     # Recycle connections every 5 minutes
    }

    # ------------------------------------------------------------------ #
    # Application
    # ------------------------------------------------------------------ #
    APP_NAME: str = "Linux Operations Portal"
    APP_VERSION: str = "1.0.0"
    ITEMS_PER_PAGE: int = 25

    # ------------------------------------------------------------------ #
    # Logging
    # ------------------------------------------------------------------ #
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


class DevelopmentConfig(Config):
    """Local development – verbose output, no SSL."""

    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"

    # Override to allow local Postgres (outside Docker)
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL",
        "postgresql://lop_user:lop_pass@localhost:5432/lop_db",
    ).replace("postgres://", "postgresql://", 1)


class ProductionConfig(Config):
    """Production – strict, no debug."""

    DEBUG: bool = False
    TESTING: bool = False

    # Enforce that SECRET_KEY is explicitly set in production
    @classmethod
    def validate(cls) -> None:
        if cls.SECRET_KEY == "change-me-in-production":
            raise RuntimeError(
                "SECRET_KEY must be set to a strong random value in production."
            )


class TestingConfig(Config):
    """Unit / integration testing – no real DB required."""

    TESTING: bool = True
    WTF_CSRF_ENABLED: bool = False
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"


# Registry used by create_app()
config: dict = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}

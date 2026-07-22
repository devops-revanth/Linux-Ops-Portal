"""
Configuration management for Linux Operations Portal.

Three environments are supported:
  development  – debug mode, verbose logging
  production   – gunicorn-ready, strict settings
  testing      – in-memory SQLite, no side-effects
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root when running locally
load_dotenv()

# ── Version resolution ────────────────────────────────────────────────────────
# Read APP_VERSION from the VERSION file at the repo root.
# This is the single source of truth; never hardcode it here.
_BASE_DIR = Path(__file__).parent.parent   # app/ → repo root

def _read_version_file_key(key: str, fallback: str = "unknown") -> str:
    """Read a key=value entry from the repo-root VERSION file."""
    ver_file = _BASE_DIR / "VERSION"
    if ver_file.exists():
        for line in ver_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return fallback


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
    APP_VERSION: str = _read_version_file_key("APP_VERSION", "1.0.0")
    ITEMS_PER_PAGE: int = 25

    # Base URL shown in API documentation (e.g. the Ansible example call).
    # Override with the APP_BASE_URL environment variable in production.
    APP_BASE_URL: str = os.environ.get(
        "APP_BASE_URL", "https://your-domain.example.com"
    )

    # ------------------------------------------------------------------ #
    # FreeIPA / LDAP Authentication
    # ------------------------------------------------------------------ #
    # Set FREEIPA_ENABLED=true to activate LDAP-first login.
    # All other FREEIPA_* vars are required when enabled.
    FREEIPA_ENABLED: str = os.environ.get("FREEIPA_ENABLED", "false")
    FREEIPA_URI: str = os.environ.get("FREEIPA_URI", "")
    FREEIPA_BASE_DN: str = os.environ.get("FREEIPA_BASE_DN", "")
    FREEIPA_BIND_DN: str = os.environ.get("FREEIPA_BIND_DN", "")
    FREEIPA_BIND_PASSWORD: str = os.environ.get("FREEIPA_BIND_PASSWORD", "")
    # Absolute path to the PEM CA bundle (leave blank to use system trust store)
    FREEIPA_CA_CERT: str = os.environ.get("FREEIPA_CA_CERT", "")
    # Set to "false" only in isolated dev environments — disables TLS cert check
    FREEIPA_VERIFY_CERT: str = os.environ.get("FREEIPA_VERIFY_CERT", "true")

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
        import logging as _logging
        if cls.APP_BASE_URL == "https://your-domain.example.com":
            _logging.getLogger(__name__).warning(
                "APP_BASE_URL is still set to the placeholder value. "
                "Set the APP_BASE_URL environment variable before going live."
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

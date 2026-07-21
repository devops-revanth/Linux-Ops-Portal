"""
User model.

Stores portal operator accounts.  Passwords are hashed via Werkzeug's
PBKDF2-SHA256 implementation (already a Flask dependency — no extra package).

FreeIPA / LDAP users have auth_source="ldap" and their password_hash is set to
the sentinel "!NOLOGIN" so local password checks always fail.

Flask-Login integration is via UserMixin which provides the four required
properties/methods: is_authenticated, is_active, is_anonymous, get_id().

Roles:
  administrator – full access
  operator      – read/write inventory & patching (default)
  readonly      – view-only
"""
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db

# Sentinel stored in password_hash for FreeIPA/LDAP accounts.
# The leading "!" is intentionally invalid for Werkzeug hashes so that
# check_password() will always return False even if called accidentally.
_UNUSABLE_PASSWORD = "!NOLOGIN"

VALID_ROLES = ("administrator", "operator", "readonly")


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: int = db.Column(db.Integer, primary_key=True)
    username: str = db.Column(db.String(64), nullable=False, unique=True, index=True)
    email: str = db.Column(db.String(255), nullable=True, unique=True, index=True)
    password_hash: str = db.Column(db.String(256), nullable=False, default=_UNUSABLE_PASSWORD)

    # Role-based access
    role: str = db.Column(
        db.String(32), nullable=False, default="operator", server_default="operator"
    )
    # Auth source: "local" or "ldap"
    auth_source: str = db.Column(
        db.String(32), nullable=False, default="local", server_default="local"
    )
    # Human-friendly name sourced from LDAP cn attribute
    display_name: str = db.Column(db.String(128), nullable=True)
    # Timestamp of most recent successful login
    last_login: datetime = db.Column(db.DateTime(timezone=True), nullable=True)

    is_active: bool = db.Column(db.Boolean, nullable=False, default=True)
    created_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Password helpers ─────────────────────────────────────────────────── #

    def set_password(self, password: str) -> None:
        """Hash and store a plain-text password."""
        self.password_hash = generate_password_hash(password)

    def set_unusable_password(self) -> None:
        """Mark this account as having no local password (LDAP-only)."""
        self.password_hash = _UNUSABLE_PASSWORD

    def check_password(self, password: str) -> bool:
        """Return True if the plain-text password matches the stored hash.

        Always returns False for LDAP accounts (sentinel hash).
        """
        if self.password_hash == _UNUSABLE_PASSWORD:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def is_ldap_user(self) -> bool:
        """True when this account is managed by FreeIPA/LDAP."""
        return self.auth_source == "ldap"

    @property
    def display(self) -> str:
        """Best available human-friendly name."""
        return self.display_name or self.username

    def __repr__(self) -> str:
        return f"<User {self.username} role={self.role} source={self.auth_source}>"

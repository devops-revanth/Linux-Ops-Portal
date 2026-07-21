"""
User model.

Stores portal operator accounts.  Passwords are hashed via Werkzeug's
PBKDF2-SHA256 implementation (already a Flask dependency — no extra package).

Flask-Login integration is via UserMixin which provides the four required
properties/methods: is_authenticated, is_active, is_anonymous, get_id().
"""
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: int = db.Column(db.Integer, primary_key=True)
    username: str = db.Column(db.String(64), nullable=False, unique=True, index=True)
    email: str = db.Column(db.String(255), nullable=True, unique=True, index=True)
    password_hash: str = db.Column(db.String(256), nullable=False)
    is_active: bool = db.Column(db.Boolean, nullable=False, default=True)
    created_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Password helpers ─────────────────────────────────────────────── #

    def set_password(self, password: str) -> None:
        """Hash and store a plain-text password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Return True if the plain-text password matches the stored hash."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.username}>"

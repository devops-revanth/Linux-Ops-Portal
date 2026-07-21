"""
API Token model.

Stores the bearer token used to authenticate Ansible push requests.
Only one active token exists at a time; regenerating creates a new
record and deactivates the old one.
"""
import secrets
from datetime import datetime, timezone

from ..extensions import db


class ApiToken(db.Model):
    __tablename__ = "api_tokens"

    id: int = db.Column(db.Integer, primary_key=True)
    token: str = db.Column(db.String(64), nullable=False, unique=True, index=True)
    is_active: bool = db.Column(db.Boolean, nullable=False, default=True)
    created_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Class helpers ─────────────────────────────────────────────────── #

    @classmethod
    def generate_token(cls) -> str:
        """Return a new cryptographically secure 32-byte hex token string."""
        return secrets.token_hex(32)

    @classmethod
    def get_active(cls) -> "ApiToken | None":
        """Return the single active token, or None if none exists."""
        return cls.query.filter_by(is_active=True).first()

    @classmethod
    def validate(cls, raw_token: str) -> bool:
        """Return True if *raw_token* matches the active token."""
        active = cls.get_active()
        if not active:
            return False
        return secrets.compare_digest(active.token, raw_token)

    def __repr__(self) -> str:
        return f"<ApiToken id={self.id} active={self.is_active}>"

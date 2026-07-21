"""Audit log model — records every write operation performed by a portal user."""
from datetime import datetime

from ..extensions import db


class AuditLog(db.Model):
    """One row per write action taken by a user through the portal UI.

    Columns
    -------
    actor      : username of the logged-in user (or "system" for seeders)
    action     : dot-namespaced verb, e.g. "inventory.server.delete"
    target     : human-readable subject, e.g. "web01.example.com"
    details    : optional free-text context (hostnames list, count, etc.)
    created_at : UTC timestamp, indexed for chronological queries
    """

    __tablename__ = "audit_logs"

    id         = db.Column(db.Integer, primary_key=True)
    actor      = db.Column(db.String(64),  nullable=False, index=True)
    action     = db.Column(db.String(100), nullable=False, index=True)
    target     = db.Column(db.String(255), nullable=True)
    details    = db.Column(db.Text,        nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} actor={self.actor!r} action={self.action!r}>"

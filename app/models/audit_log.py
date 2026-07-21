"""Audit log model — records every write operation performed by a portal user."""
from datetime import datetime

from ..extensions import db


class AuditLog(db.Model):
    """One row per write action taken by a user through the portal UI.

    Columns
    -------
    actor        : username of the logged-in user (or "system" for seeders)
    module       : first segment of action, e.g. "inventory" (indexed)
    action       : dot-namespaced verb, e.g. "inventory.server.delete"
    target       : human-readable subject, e.g. "web01.example.com"
    details      : optional free-text context
    ip_address   : client IP address at time of action
    auth_source  : "local" or "ldap" (mirrors User.auth_source)
    result       : "success" or "failed"
    user_agent   : HTTP User-Agent header
    session_id   : Flask session identifier (if available)
    before_values: JSON snapshot of the object before modification
    after_values : JSON snapshot of the object after modification
    created_at   : UTC timestamp, indexed for chronological queries
    """

    __tablename__ = "audit_logs"

    id            = db.Column(db.Integer, primary_key=True)
    actor         = db.Column(db.String(64),  nullable=False, index=True)
    module        = db.Column(db.String(50),  nullable=True,  index=True)
    action        = db.Column(db.String(100), nullable=False, index=True)
    target        = db.Column(db.String(255), nullable=True)
    details       = db.Column(db.Text,        nullable=True)
    ip_address    = db.Column(db.String(45),  nullable=True)
    auth_source   = db.Column(db.String(32),  nullable=True)
    result        = db.Column(db.String(20),  nullable=False, default="success", index=True)
    user_agent    = db.Column(db.String(500), nullable=True)
    session_id    = db.Column(db.String(128), nullable=True)
    before_values = db.Column(db.Text,        nullable=True)
    after_values  = db.Column(db.Text,        nullable=True)
    created_at    = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} actor={self.actor!r} action={self.action!r} result={self.result!r}>"

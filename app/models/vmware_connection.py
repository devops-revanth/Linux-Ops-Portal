"""
VmwareConnection — one row per configured vCenter.

Replaces the singleton VmwareConfig pattern.  Each connection has its own
credentials, schedule, sync stats, and location assignment.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..extensions import db

# Re-export schedule choices so callers can import from one place
SYNC_SCHEDULE_CHOICES: list[tuple[str, str]] = [
    ("disabled", "Disabled"),
    ("hourly",   "Hourly"),
    ("6h",       "Every 6 Hours"),
    ("12h",      "Every 12 Hours"),
    ("daily",    "Daily"),
]

CONNECTION_STATUS_OPTIONS = [
    "Not Tested",
    "Connected",
    "Disconnected",
    "Authentication Failed",
    "SSL Error",
    "Connection Timeout",
]


class VmwareConnection(db.Model):
    __tablename__ = "vmware_connections"
    __table_args__ = (
        db.UniqueConstraint("location_id", "vcenter_host", name="uq_vmware_conn_loc_host"),
    )

    id: int = db.Column(db.Integer, primary_key=True)

    # ── Identity ─────────────────────────────────────────────────────────── #
    name: str = db.Column(db.String(255), nullable=False)

    # ── Connection ───────────────────────────────────────────────────────── #
    vcenter_host: str = db.Column(db.String(255), nullable=False)
    port: int         = db.Column(db.Integer,     nullable=False, default=443)
    username: str     = db.Column(db.String(255), nullable=True)
    password_enc: str = db.Column(db.Text,        nullable=True)
    ignore_ssl: bool  = db.Column(db.Boolean,     nullable=False, default=False)

    # ── Location (mandatory at app level) ────────────────────────────────── #
    location_id: int = db.Column(
        db.Integer, db.ForeignKey("locations.id"), nullable=True
    )
    default_environment_id: int = db.Column(
        db.Integer, db.ForeignKey("environments.id"), nullable=True
    )

    # ── Enable / disable ─────────────────────────────────────────────────── #
    enabled: bool = db.Column(db.Boolean, nullable=False, default=True)

    # ── Connection status ────────────────────────────────────────────────── #
    connection_status: str = db.Column(
        db.String(50), nullable=False, default="Not Tested"
    )
    last_test_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)

    # ── Sync stats ───────────────────────────────────────────────────────── #
    last_sync_at:       datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    last_sync_ok_at:    datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    last_sync_fail_at:  datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    last_sync_vms:      int      = db.Column(db.Integer, nullable=True)
    last_sync_duration_s: float  = db.Column(db.Float,   nullable=True)
    sync_schedule: str           = db.Column(db.String(20), nullable=False, default="disabled")

    updated_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ─────────────────────────────────────────────────────── #
    location            = db.relationship("Location",    foreign_keys=[location_id])
    default_environment = db.relationship("Environment", foreign_keys=[default_environment_id])
    sync_logs           = db.relationship(
        "VmwareSyncLog", back_populates="connection",
        cascade="all, delete-orphan", lazy="dynamic",
    )

    # ── Helpers ───────────────────────────────────────────────────────────── #
    def set_password(self, plaintext: str) -> None:
        """Encrypt and store a new password.  No-op if plaintext is blank."""
        if not plaintext:
            return
        from ..encryption import encrypt_value
        self.password_enc = encrypt_value(plaintext)

    def get_password(self) -> str | None:
        if not self.password_enc:
            return None
        from ..encryption import decrypt_value
        return decrypt_value(self.password_enc)

    @property
    def status_badge_class(self) -> str:
        """Bootstrap badge colour class for connection_status."""
        return {
            "Connected":          "bg-success-subtle text-success border-success-subtle",
            "Authentication Failed": "bg-danger-subtle text-danger border-danger-subtle",
            "SSL Error":          "bg-warning-subtle text-warning border-warning-subtle",
            "Connection Timeout": "bg-warning-subtle text-warning border-warning-subtle",
        }.get(self.connection_status, "bg-secondary-subtle text-secondary border-secondary-subtle")

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "name":             self.name,
            "vcenter_host":     self.vcenter_host,
            "port":             self.port,
            "username":         self.username or "",
            "ignore_ssl":       self.ignore_ssl,
            "location_id":      self.location_id,
            "location_name":    self.location.name if self.location else "",
            "default_environment_id": self.default_environment_id,
            "enabled":          self.enabled,
            "connection_status": self.connection_status,
            "sync_schedule":    self.sync_schedule,
            "last_sync_ok_at":  self.last_sync_ok_at.isoformat() if self.last_sync_ok_at else None,
            "last_sync_vms":    self.last_sync_vms,
            "last_sync_duration_s": self.last_sync_duration_s,
        }

    def __repr__(self) -> str:
        return f"<VmwareConnection {self.name!r} host={self.vcenter_host!r}>"

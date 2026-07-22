"""
VMware vCenter configuration and sync log models.

VmwareConfig  — singleton table storing connection settings and sync stats.
VmwareSyncLog — one row per sync run (running / completed / failed).
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..extensions import db


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


class VmwareConfig(db.Model):
    __tablename__ = "vmware_config"

    id: int = db.Column(db.Integer, primary_key=True)

    # ── Enable / disable ────────────────────────────────────────────────── #
    enabled: bool = db.Column(db.Boolean, nullable=False, default=False)

    # ── Connection ──────────────────────────────────────────────────────── #
    vcenter_host: str = db.Column(db.String(255), nullable=True)
    port: int = db.Column(db.Integer, nullable=False, default=443)
    username: str = db.Column(db.String(255), nullable=True)
    password_enc: str = db.Column(db.Text, nullable=True)
    ignore_ssl: bool = db.Column(db.Boolean, nullable=False, default=False)

    # ── Default mappings ────────────────────────────────────────────────── #
    default_location_id: int = db.Column(
        db.Integer, db.ForeignKey("locations.id"), nullable=True
    )
    default_environment_id: int = db.Column(
        db.Integer, db.ForeignKey("environments.id"), nullable=True
    )

    # ── Connection status ───────────────────────────────────────────────── #
    connection_status: str = db.Column(
        db.String(50), nullable=False, default="Not Tested"
    )
    last_test_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)

    # ── Sync stats ──────────────────────────────────────────────────────── #
    last_sync_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    last_sync_ok_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    last_sync_fail_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    last_sync_vms: int = db.Column(db.Integer, nullable=True)
    last_sync_duration_s: float = db.Column(db.Float, nullable=True)
    sync_schedule: str = db.Column(db.String(20), nullable=False, default="disabled")

    updated_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ───────────────────────────────────────────────────── #
    default_location = db.relationship("Location", foreign_keys=[default_location_id])
    default_environment = db.relationship("Environment", foreign_keys=[default_environment_id])

    # ── Helpers ─────────────────────────────────────────────────────────── #
    @classmethod
    def get(cls) -> "VmwareConfig":
        """Return (or create with defaults) the singleton config record."""
        cfg = cls.query.first()
        if cfg is None:
            cfg = cls()
            db.session.add(cfg)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                cfg = cls.query.first() or cls()
        return cfg

    def set_password(self, plaintext: str) -> None:
        if not plaintext:
            return  # keep existing encrypted password if blank submitted
        from ..encryption import encrypt_value
        self.password_enc = encrypt_value(plaintext)

    def get_password(self) -> str | None:
        if not self.password_enc:
            return None
        from ..encryption import decrypt_value
        return decrypt_value(self.password_enc)

    def __repr__(self) -> str:
        return f"<VmwareConfig host={self.vcenter_host!r} enabled={self.enabled}>"


class VmwareSyncLog(db.Model):
    __tablename__ = "vmware_sync_logs"

    id: int = db.Column(db.Integer, primary_key=True)
    status: str = db.Column(
        db.String(20), nullable=False, default="running"
    )  # running | completed | failed
    started_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    finished_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    vms_imported: int = db.Column(db.Integer, nullable=False, default=0)
    vms_updated: int = db.Column(db.Integer, nullable=False, default=0)
    vms_skipped: int = db.Column(db.Integer, nullable=False, default=0)
    error_message: str = db.Column(db.Text, nullable=True)
    triggered_by: str = db.Column(db.String(20), nullable=False, default="manual")
    # manual | scheduled

    def __repr__(self) -> str:
        return f"<VmwareSyncLog id={self.id} status={self.status!r}>"

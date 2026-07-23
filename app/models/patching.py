"""
Patching model.

One-to-one with Server.  All fields are populated by Ansible except
patch_status which may also be updated manually via the API endpoint.
"""
from datetime import datetime, timezone

from ..extensions import db


class Patching(db.Model):
    __tablename__ = "patching"

    id: int = db.Column(db.Integer, primary_key=True)
    server_id: int = db.Column(
        db.Integer,
        db.ForeignKey("linux_servers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    patch_status: str = db.Column(
        db.String(50),
        nullable=False,
        default="unknown",
    )  # up-to-date | pending | failed | unknown

    current_kernel: str = db.Column(db.String(150), nullable=True)
    previous_kernel: str = db.Column(db.String(150), nullable=True)
    last_patch_date: datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    last_reboot_date: datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    pending_updates: int = db.Column(db.Integer, nullable=True, default=0)
    reboot_required: bool | None = db.Column(db.Boolean, nullable=True, default=None)

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

    # Relationship
    server = db.relationship("Server", back_populates="patching")

    # ── Computed compliance status ─────────────────────────────────────────── #

    @property
    def compliance_status(self) -> str:
        """
        Derive compliance from last_patch_date and the configured thresholds.

        Compliance is determined solely by when the server was last patched
        relative to the organisation's policy windows.  It is intentionally
        independent of pending_updates, patch_status, and reboot_required —
        those fields belong to the separate Patch Status concept.

        Thresholds are read from ComplianceConfig (DB singleton, cached per
        request via flask.g).  Falls back to 90-day / 15-day defaults when
        called outside a request context or before the table exists.

        Policy (example: window=90 days, due_soon=15 days):

            days since last patch  │ status
            ───────────────────────┼──────────
            NULL                   │ unknown
            0 – 90                 │ compliant
            91 – 105               │ due_soon
            > 105                  │ overdue

        Returns:
            'unknown'   — last_patch_date is NULL (never patched / no data)
            'compliant' — patched within the compliance window
            'due_soon'  — patched beyond the window but within the due-soon buffer
            'overdue'   — patched beyond the window + due-soon buffer
        """
        if self.last_patch_date is None:
            return "unknown"

        window_days, due_soon_days = _get_compliance_thresholds()
        now = datetime.now(timezone.utc)
        days_since = (now - self.last_patch_date).days

        if days_since <= window_days:
            return "compliant"
        if days_since <= window_days + due_soon_days:
            return "due_soon"
        return "overdue"

    def __repr__(self) -> str:
        return f"<Patching server_id={self.server_id} status={self.patch_status}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "server_id": self.server_id,
            "patch_status": self.patch_status,
            "current_kernel": self.current_kernel,
            "previous_kernel": self.previous_kernel,
            "last_patch_date": (
                self.last_patch_date.isoformat() if self.last_patch_date else None
            ),
            "last_reboot_date": (
                self.last_reboot_date.isoformat() if self.last_reboot_date else None
            ),
            "pending_updates": self.pending_updates,
            "reboot_required": self.reboot_required,
        }


def _get_compliance_thresholds() -> tuple[int, int]:
    """
    Return (compliance_window_days, due_soon_days) from ComplianceConfig,
    caching the result in flask.g for the lifetime of the current request.
    Falls back to (90, 15) when called outside a request context.
    """
    try:
        from flask import g
        if not hasattr(g, "_compliance_thresholds"):
            from .compliance_config import ComplianceConfig
            cfg = ComplianceConfig.get()
            g._compliance_thresholds = (cfg.compliance_window_days, cfg.due_soon_days)
        return g._compliance_thresholds
    except Exception:
        return (90, 15)

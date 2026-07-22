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
        Derive compliance from pending_updates and last_patch_date.

        Compliance window: 30 days (industry default for enterprise Linux).

        Returns:
            'compliant'  — no pending updates
            'due_soon'   — updates pending but last patch within 30 days
            'overdue'    — updates pending and last patch > 30 days ago (or never)
            'unknown'    — pending_updates is None (data not yet collected)
        """
        from datetime import datetime, timezone

        COMPLIANCE_WINDOW_DAYS = 30

        if self.pending_updates is None:
            return "unknown"

        if self.pending_updates == 0:
            return "compliant"

        # Has pending updates — check whether we are still within the window
        if self.last_patch_date:
            now = datetime.now(timezone.utc)
            days_since = (now - self.last_patch_date).days
            if days_since <= COMPLIANCE_WINDOW_DAYS:
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

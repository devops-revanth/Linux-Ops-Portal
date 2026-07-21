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
        }

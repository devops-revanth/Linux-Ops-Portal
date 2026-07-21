"""
Owner model.

Represents a team or individual responsible for a group of servers.
Examples: "Platform Engineering", "DevOps", "Security"
"""
from datetime import datetime, timezone

from ..extensions import db


class Owner(db.Model):
    __tablename__ = "owners"

    id: int = db.Column(db.Integer, primary_key=True)
    name: str = db.Column(db.String(150), nullable=False, unique=True)
    email: str = db.Column(db.String(255), nullable=True)
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

    # Relationships
    servers = db.relationship("Server", back_populates="owner", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Owner {self.name}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "is_active": self.is_active,
        }

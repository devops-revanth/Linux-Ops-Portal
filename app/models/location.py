"""
Location model.

Represents a physical or logical data-centre / site location.
Examples: "DC1-NYC", "AWS-US-EAST", "On-Prem-LAB"
"""
from datetime import datetime, timezone

from ..extensions import db


class Location(db.Model):
    __tablename__ = "locations"

    id: int = db.Column(db.Integer, primary_key=True)
    name: str = db.Column(db.String(100), nullable=False, unique=True)
    description: str = db.Column(db.String(255), nullable=True)
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
    servers = db.relationship("Server", back_populates="location", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Location {self.name}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_active": self.is_active,
        }

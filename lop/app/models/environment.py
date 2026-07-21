"""
Environment model.

Represents a deployment tier / lifecycle stage.
Examples: "Production", "Development", "Staging", "Demo"
"""
from datetime import datetime, timezone

from ..extensions import db


class Environment(db.Model):
    __tablename__ = "environments"

    id: int = db.Column(db.Integer, primary_key=True)
    name: str = db.Column(db.String(100), nullable=False, unique=True)
    label: str = db.Column(db.String(50), nullable=False)   # Short display label
    color: str = db.Column(db.String(20), nullable=False, default="secondary")  # Bootstrap colour
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
    servers = db.relationship("Server", back_populates="environment", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Environment {self.name}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "label": self.label,
            "color": self.color,
            "is_active": self.is_active,
        }

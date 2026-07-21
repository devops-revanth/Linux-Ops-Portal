"""
Package models.

Package  — master catalogue of trackable software (Docker, Python, Java …)
ServerPackage — installed version per server (junction table with extras).
"""
from datetime import datetime, timezone

from ..extensions import db


class Package(db.Model):
    """Master list of software packages the portal tracks."""

    __tablename__ = "packages"

    id: int = db.Column(db.Integer, primary_key=True)
    name: str = db.Column(db.String(100), nullable=False, unique=True)
    display_name: str = db.Column(db.String(150), nullable=True)
    description: str = db.Column(db.String(255), nullable=True)
    is_active: bool = db.Column(db.Boolean, nullable=False, default=True)
    created_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    server_packages = db.relationship("ServerPackage", back_populates="package")

    def __repr__(self) -> str:
        return f"<Package {self.name}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name or self.name,
            "description": self.description,
        }


class ServerPackage(db.Model):
    """Installed version of a Package on a specific Server."""

    __tablename__ = "server_packages"

    id: int = db.Column(db.Integer, primary_key=True)
    server_id: int = db.Column(
        db.Integer,
        db.ForeignKey("linux_servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    package_id: int = db.Column(
        db.Integer,
        db.ForeignKey("packages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: str = db.Column(db.String(100), nullable=True)
    collected_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        db.UniqueConstraint("server_id", "package_id", name="uq_server_package"),
    )

    # Relationships
    server = db.relationship("Server", back_populates="packages")
    package = db.relationship("Package", back_populates="server_packages")

    def __repr__(self) -> str:
        return f"<ServerPackage server={self.server_id} pkg={self.package_id} v={self.version}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "package_name": self.package.name if self.package else None,
            "display_name": self.package.display_name if self.package else None,
            "version": self.version,
            "collected_at": self.collected_at.isoformat() if self.collected_at else None,
        }

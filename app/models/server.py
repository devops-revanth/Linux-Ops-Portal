"""
Server (linux_servers) model.

Central inventory record.  All fields except hostname and ip_address
are nullable because Ansible may not collect every attribute on the
first run.  Manual-only fields: owner_id, status.
"""
from datetime import datetime, timezone

from ..extensions import db


class Server(db.Model):
    __tablename__ = "linux_servers"

    # ------------------------------------------------------------------ #
    # Identity
    # ------------------------------------------------------------------ #
    id: int = db.Column(db.Integer, primary_key=True)
    hostname: str = db.Column(db.String(255), nullable=False, unique=True, index=True)
    fqdn: str = db.Column(db.String(255), nullable=True)
    ip_address: str = db.Column(db.String(45), nullable=False, index=True)  # IPv4 or IPv6

    # ------------------------------------------------------------------ #
    # Classification (FK)
    # ------------------------------------------------------------------ #
    environment_id: int = db.Column(
        db.Integer, db.ForeignKey("environments.id"), nullable=True, index=True
    )
    location_id: int = db.Column(
        db.Integer, db.ForeignKey("locations.id"), nullable=True, index=True
    )
    owner_id: int = db.Column(
        db.Integer, db.ForeignKey("owners.id"), nullable=True, index=True
    )

    # ------------------------------------------------------------------ #
    # OS & Hardware (populated by Ansible)
    # ------------------------------------------------------------------ #
    operating_system: str = db.Column(db.String(100), nullable=True)
    os_version: str = db.Column(db.String(100), nullable=True)
    kernel_version: str = db.Column(db.String(150), nullable=True)
    cpu_count: int = db.Column(db.Integer, nullable=True)
    cpu_model: str = db.Column(db.String(255), nullable=True)
    ram_gb: float = db.Column(db.Float, nullable=True)

    # ── Extended Ansible-owned fields (Phase 2 fact collection) ──────── #
    architecture: str = db.Column(db.String(20), nullable=True)
    swap_gb: float = db.Column(db.Float, nullable=True)
    timezone: str = db.Column(db.String(50), nullable=True)
    selinux_status: str = db.Column(db.String(30), nullable=True)
    uptime_seconds: int = db.Column(db.BigInteger, nullable=True)
    boot_time: datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    default_gateway: str = db.Column(db.String(45), nullable=True)
    dns_servers: str = db.Column(db.Text, nullable=True)       # comma-separated
    primary_interface: str = db.Column(db.String(50), nullable=True)
    mac_address: str = db.Column(db.String(20), nullable=True)
    virtualization_type: str = db.Column(db.String(30), nullable=True)

    # ── Per-server fact collection status (Phase 2.1) ─────────────────────── #
    ansible_fact_status: str   = db.Column(db.String(20), nullable=True)
    # success | failed | running | None (never collected)
    ansible_fact_duration_secs: int = db.Column(db.Integer, nullable=True)
    ansible_fact_error: str    = db.Column(db.Text, nullable=True)

    # ------------------------------------------------------------------ #
    # Source tracking
    # ------------------------------------------------------------------ #
    source: str = db.Column(
        db.String(20),
        nullable=False,
        default="manual",
        server_default="manual",
    )  # manual | vmware | ansible
    vmware_vm_uuid: str = db.Column(
        db.String(36), nullable=True, index=True,
        comment="VMware VM UUID for deduplication"
    )

    # ------------------------------------------------------------------ #
    # Status (manually set)
    # ------------------------------------------------------------------ #
    status: str = db.Column(
        db.String(50),
        nullable=False,
        default="active",
    )  # active | inactive | decommissioned | maintenance

    # ------------------------------------------------------------------ #
    # Sync metadata
    # ------------------------------------------------------------------ #
    last_ansible_sync: datetime = db.Column(db.DateTime(timezone=True), nullable=True)
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

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    environment = db.relationship("Environment", back_populates="servers")
    location = db.relationship("Location", back_populates="servers")
    owner = db.relationship("Owner", back_populates="servers")
    patching = db.relationship(
        "Patching", back_populates="server", uselist=False, cascade="all, delete-orphan"
    )
    packages = db.relationship(
        "ServerPackage", back_populates="server", cascade="all, delete-orphan"
    )
    notes = db.relationship(
        "Note", back_populates="server", cascade="all, delete-orphan", order_by="Note.created_at.desc()"
    )
    vmware_meta = db.relationship(
        "VmwareServerMeta", back_populates="server", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Server {self.hostname}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "hostname": self.hostname,
            "fqdn": self.fqdn,
            "ip_address": self.ip_address,
            "environment": self.environment.name if self.environment else None,
            "location": self.location.name if self.location else None,
            "owner": self.owner.name if self.owner else None,
            "operating_system": self.operating_system,
            "os_version": self.os_version,
            "kernel_version": self.kernel_version,
            "cpu_count": self.cpu_count,
            "cpu_model": self.cpu_model,
            "ram_gb": self.ram_gb,
            "status": self.status,
            "last_ansible_sync": (
                self.last_ansible_sync.isoformat() if self.last_ansible_sync else None
            ),
        }

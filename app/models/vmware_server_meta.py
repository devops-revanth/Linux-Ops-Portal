"""
VMware-specific metadata for an inventory server.

One row per server that was imported from vCenter.  Linked 1:1 to
linux_servers via server_id.  The parent Server record stores the
standard inventory fields; this table holds vSphere-specific data.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..extensions import db


class VmwareServerMeta(db.Model):
    __tablename__ = "vmware_server_meta"

    id: int = db.Column(db.Integer, primary_key=True)
    server_id: int = db.Column(
        db.Integer,
        db.ForeignKey("linux_servers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # ── vCenter topology ────────────────────────────────────────────────── #
    vcenter_host: str = db.Column(db.String(255), nullable=True)
    datacenter: str = db.Column(db.String(255), nullable=True)
    cluster: str = db.Column(db.String(255), nullable=True)
    esxi_host: str = db.Column(db.String(255), nullable=True)
    datastore: str = db.Column(db.String(255), nullable=True)
    folder: str = db.Column(db.String(500), nullable=True)

    # ── VM identity ─────────────────────────────────────────────────────── #
    vm_name: str = db.Column(db.String(255), nullable=True)
    vm_uuid: str = db.Column(db.String(36), nullable=True, index=True)
    bios_uuid: str = db.Column(db.String(36), nullable=True)

    # ── Runtime state ───────────────────────────────────────────────────── #
    power_state: str = db.Column(db.String(50), nullable=True)

    # ── VMware Tools ────────────────────────────────────────────────────── #
    tools_status: str = db.Column(db.String(100), nullable=True)
    tools_version: str = db.Column(db.String(50), nullable=True)

    # ── Network ─────────────────────────────────────────────────────────── #
    mac_address: str = db.Column(db.String(255), nullable=True)
    network_name: str = db.Column(db.String(255), nullable=True)

    # ── Sync timestamp ──────────────────────────────────────────────────── #
    last_synced_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)

    # ── Relationship ────────────────────────────────────────────────────── #
    server = db.relationship("Server", back_populates="vmware_meta")

    def __repr__(self) -> str:
        return f"<VmwareServerMeta server_id={self.server_id} vm={self.vm_name!r}>"

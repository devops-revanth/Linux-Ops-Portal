"""
Dashboard query helpers.

All database reads for the dashboard live here — keeps routes thin
and makes queries independently testable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from sqlalchemy import func, or_

from ...extensions import db
from ...models.environment import Environment
from ...utils import sort_envs
from ...models.location import Location
from ...models.patching import Patching
from ...models.server import Server

logger = logging.getLogger(__name__)


@dataclass
class EnvironmentCount:
    name: str
    label: str
    color: str
    count: int


@dataclass
class LocationCount:
    name: str
    count: int
    percent: float


@dataclass
class DashboardStats:
    total_servers:        int = 0
    active_servers:       int = 0
    servers_with_updates: int = 0   # pending_updates > 0
    compliant_servers:    int = 0   # pending_updates == 0
    due_soon_servers:     int = 0   # updates pending, patched within window
    overdue_servers:      int = 0   # updates pending, patched beyond window
    last_ansible_sync:    datetime | None = None
    environments:         list[EnvironmentCount] = field(default_factory=list)
    locations:            list[LocationCount]     = field(default_factory=list)
    # VMware stats
    vmware_imported:      int = 0
    vmware_connected:     int = 0   # vCenters with status "Connected"
    vmware_last_sync:     datetime | None = None
    vmware_sync_status:   str = "Not Configured"
    # Ansible stats
    ansible_connected:    bool = False
    ansible_inv_hosts:    int = 0
    ansible_playbooks:    int = 0
    ansible_last_valid:   datetime | None = None


def get_dashboard_stats() -> DashboardStats:
    """
    Return aggregated statistics for the dashboard.

    Runs a small number of targeted SQL queries; avoids full table scans
    where possible by leveraging indexed columns.
    """
    stats = DashboardStats()

    try:
        # ── Total & active server counts ─────────────────────────────
        stats.total_servers = db.session.query(func.count(Server.id)).scalar() or 0
        stats.active_servers = (
            db.session.query(func.count(Server.id))
            .filter(Server.status == "active")
            .scalar()
            or 0
        )

        # ── Compliance-based patch counts ─────────────────────────────
        try:
            from ...models.compliance_config import ComplianceConfig
            cfg = ComplianceConfig.get()
            window_days = cfg.compliance_window_days
        except Exception:
            window_days = 90

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=window_days)

        stats.servers_with_updates = (
            db.session.query(func.count(Patching.id))
            .filter(Patching.pending_updates > 0)
            .scalar() or 0
        )
        stats.compliant_servers = (
            db.session.query(func.count(Patching.id))
            .filter(Patching.pending_updates == 0)
            .scalar() or 0
        )
        stats.due_soon_servers = (
            db.session.query(func.count(Patching.id))
            .filter(
                Patching.pending_updates > 0,
                Patching.last_patch_date >= cutoff,
            )
            .scalar() or 0
        )
        stats.overdue_servers = (
            db.session.query(func.count(Patching.id))
            .filter(
                Patching.pending_updates > 0,
                or_(
                    Patching.last_patch_date < cutoff,
                    Patching.last_patch_date == None,  # noqa: E711
                ),
            )
            .scalar() or 0
        )

        # ── Last Ansible sync across all servers ─────────────────────
        stats.last_ansible_sync = (
            db.session.query(func.max(Server.last_ansible_sync)).scalar()
        )

        # ── Server count per environment ─────────────────────────────
        env_rows = (
            db.session.query(
                Environment.name,
                Environment.label,
                Environment.color,
                func.count(Server.id),
            )
            .outerjoin(Server, Server.environment_id == Environment.id)
            .filter(Environment.is_active == True)  # noqa: E712
            .group_by(Environment.id, Environment.name, Environment.label, Environment.color)
            .all()
        )
        stats.environments = [
            EnvironmentCount(name=r[0], label=r[1], color=r[2], count=r[3])
            for r in sort_envs(env_rows, key=lambda r: r[0])
        ]

        # ── Server count per location ─────────────────────────────────
        loc_rows = (
            db.session.query(
                Location.name,
                func.count(Server.id).label("cnt"),
            )
            .outerjoin(Server, Server.location_id == Location.id)
            .filter(Location.is_active == True)  # noqa: E712
            .group_by(Location.id, Location.name)
            .order_by(func.count(Server.id).desc())
            .all()
        )
        total = stats.total_servers or 1  # avoid division by zero
        stats.locations = [
            LocationCount(
                name=r[0],
                count=r[1],
                percent=round(r[1] / total * 100, 1),
            )
            for r in loc_rows
        ]

        # ── VMware stats ──────────────────────────────────────────────
        try:
            from ...models.vmware_config import VmwareConfig
            cfg = VmwareConfig.query.first()
            if cfg and cfg.enabled:
                stats.vmware_imported = (
                    db.session.query(func.count(Server.id))
                    .filter(Server.source == "vmware")
                    .scalar() or 0
                )
                stats.vmware_connected = 1 if cfg.connection_status == "Connected" else 0
                stats.vmware_last_sync = cfg.last_sync_ok_at
                if cfg.last_sync_ok_at:
                    stats.vmware_sync_status = "Completed"
                elif cfg.last_sync_fail_at:
                    stats.vmware_sync_status = "Failed"
                else:
                    stats.vmware_sync_status = "Never Synced"
            elif cfg and not cfg.enabled:
                stats.vmware_sync_status = "Disabled"
        except Exception:
            pass

        # ── Ansible stats ──────────────────────────────────────────────
        try:
            from ...models.ansible_config import AnsibleConfig
            acfg = AnsibleConfig.query.first()
            if acfg and acfg.enabled:
                stats.ansible_connected  = acfg.connection_status == "Connected"
                stats.ansible_inv_hosts  = acfg.last_inventory_hosts or 0
                stats.ansible_playbooks  = acfg.last_playbooks_found or 0
                stats.ansible_last_valid = acfg.last_validation_at
        except Exception:
            pass

    except Exception:
        logger.exception("Failed to query dashboard stats")

    return stats

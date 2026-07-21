"""
Dashboard query helpers.

All database reads for the dashboard live here — keeps routes thin
and makes queries independently testable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func

from ...extensions import db
from ...models.environment import Environment
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
    total_servers: int = 0
    active_servers: int = 0
    pending_patches: int = 0
    patched_servers: int = 0
    failed_patches: int = 0
    last_ansible_sync: datetime | None = None
    environments: list[EnvironmentCount] = field(default_factory=list)
    locations: list[LocationCount] = field(default_factory=list)


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

        # ── Patching summary ─────────────────────────────────────────
        patch_rows = (
            db.session.query(Patching.patch_status, func.count(Patching.id))
            .group_by(Patching.patch_status)
            .all()
        )
        for status, count in patch_rows:
            if status == "pending":
                stats.pending_patches = count
            elif status == "up-to-date":
                stats.patched_servers = count
            elif status == "failed":
                stats.failed_patches = count

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
            .order_by(Environment.name)
            .all()
        )
        stats.environments = [
            EnvironmentCount(name=r[0], label=r[1], color=r[2], count=r[3])
            for r in env_rows
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

    except Exception:
        logger.exception("Failed to query dashboard stats")

    return stats

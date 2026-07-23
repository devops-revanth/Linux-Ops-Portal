"""
Packages blueprint query helpers.

The Packages page is the single Fleet Package & Patch Management dashboard.
It shows per-server compliance, update status, and links through to each
server's detailed package tabs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from sqlalchemy import asc, desc, func, or_
from sqlalchemy.orm import contains_eager

from ...extensions import db
from ...models.environment import Environment
from ...models.location import Location
from ...models.patching import Patching
from ...models.server import Server
from ...utils import sort_envs

logger = logging.getLogger(__name__)

VALID_SORTS = {
    "hostname", "environment", "location", "operating_system",
    "kernel_version", "pending_updates", "last_patch_date",
}
DEFAULT_SORT  = "hostname"
DEFAULT_ORDER = "asc"

SORTABLE_COLS: dict[str, object] = {
    "hostname":         Server.hostname,
    "environment":      Environment.name,
    "location":         Location.name,
    "operating_system": Server.operating_system,
    "kernel_version":   Server.kernel_version,
    "pending_updates":  Patching.pending_updates,
    "last_patch_date":  Patching.last_patch_date,
}


# ── Data-transfer objects ────────────────────────────────────────────────── #

@dataclass
class PackageFleetSummary:
    servers_managed:      int = 0
    servers_with_updates: int = 0
    compliant_servers:    int = 0
    overdue_servers:      int = 0


@dataclass
class FleetFilters:
    search:      str       = ""
    env_id:      int | None = None
    location_id: int | None = None
    sort:        str       = DEFAULT_SORT
    order:       str       = DEFAULT_ORDER


@dataclass
class FleetPage:
    rows:         list         = field(default_factory=list)
    total:        int          = 0
    page:         int          = 1
    per_page:     int          = 25
    total_pages:  int          = 1
    filters:      FleetFilters = field(default_factory=FleetFilters)
    environments: list         = field(default_factory=list)
    locations:    list         = field(default_factory=list)


# ── Fleet summary stat cards ─────────────────────────────────────────────── #

def get_fleet_summary() -> PackageFleetSummary:
    """Four top stat-card values for the Packages page header."""
    try:
        servers_managed = db.session.query(func.count(Server.id)).scalar() or 0

        servers_with_updates = (
            db.session.query(func.count(Patching.id))
            .filter(Patching.pending_updates > 0)
            .scalar() or 0
        )

        # Compliance counts — same thresholds as Patching.compliance_status
        try:
            from ...models.compliance_config import ComplianceConfig
            cfg = ComplianceConfig.get()
            window_days  = cfg.compliance_window_days
            due_soon_days = cfg.due_soon_days
        except Exception:
            window_days, due_soon_days = 90, 15

        now = datetime.now(timezone.utc)
        cutoff_compliant = now - timedelta(days=window_days)
        cutoff_overdue   = now - timedelta(days=window_days + due_soon_days)

        compliant_servers = (
            db.session.query(func.count(Patching.id))
            .filter(Patching.pending_updates == 0)
            .scalar() or 0
        )

        overdue_servers = (
            db.session.query(func.count(Patching.id))
            .filter(
                Patching.pending_updates > 0,
                or_(
                    Patching.last_patch_date < cutoff_overdue,
                    Patching.last_patch_date == None,  # noqa: E711
                ),
            )
            .scalar() or 0
        )

        return PackageFleetSummary(
            servers_managed      = servers_managed,
            servers_with_updates = servers_with_updates,
            compliant_servers    = compliant_servers,
            overdue_servers      = overdue_servers,
        )
    except Exception:
        logger.exception("Failed to compute fleet summary")
        return PackageFleetSummary()


# ── Per-server fleet table ───────────────────────────────────────────────── #

def get_fleet_page(
    filters: FleetFilters, page: int, per_page: int
) -> FleetPage:
    """
    Paginated, filtered, sorted fleet table.

    Each row is a (Server, Patching|None) tuple.
    Outer-joins Patching/Environment/Location so servers with missing
    data still appear.
    """
    result = FleetPage(filters=filters, page=page, per_page=per_page)
    try:
        q = (
            db.session.query(Server, Patching)
            .outerjoin(Patching,    Patching.server_id    == Server.id)
            .outerjoin(Environment, Server.environment_id == Environment.id)
            .outerjoin(Location,    Server.location_id    == Location.id)
            .options(
                contains_eager(Server.environment),
                contains_eager(Server.location),
            )
        )

        # Search: hostname, FQDN, or IP
        if filters.search:
            term = f"%{filters.search.strip()}%"
            q = q.filter(or_(
                Server.hostname.ilike(term),
                Server.fqdn.ilike(term),
                Server.ip_address.ilike(term),
            ))

        if filters.env_id:
            q = q.filter(Server.environment_id == filters.env_id)

        if filters.location_id:
            q = q.filter(Server.location_id == filters.location_id)

        result.total = q.count()

        sort_col = SORTABLE_COLS.get(filters.sort, Server.hostname)
        order_fn = asc if filters.order == "asc" else desc
        q = q.order_by(order_fn(sort_col).nulls_last())

        offset           = (page - 1) * per_page
        result.rows      = q.offset(offset).limit(per_page).all()
        result.total_pages = max(1, -(-result.total // per_page))

        result.environments = sort_envs(
            Environment.query.filter_by(is_active=True).all()
        )
        result.locations = (
            Location.query.filter_by(is_active=True).order_by(Location.name).all()
        )

    except Exception:
        logger.exception("Failed to query fleet page")
    return result

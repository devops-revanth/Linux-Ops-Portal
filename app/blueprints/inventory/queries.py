"""
Inventory query helpers.

All database reads for the Inventory module live here — keeps routes
thin and makes queries independently testable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import asc, desc, or_
from sqlalchemy.orm import contains_eager

from ...extensions import db
from ...models.environment import Environment
from ...models.location import Location
from ...models.owner import Owner
from ...models.server import Server
from ...utils import sort_envs

logger = logging.getLogger(__name__)

# Columns that can be sorted, mapped to their SQLAlchemy expression.
# Related-model columns require the join already present in the query.
SORTABLE_COLUMNS: dict[str, object] = {
    "hostname":          Server.hostname,
    "fqdn":              Server.fqdn,
    "ip_address":        Server.ip_address,
    "environment":       Environment.name,
    "operating_system":  Server.operating_system,
    "kernel_version":    Server.kernel_version,
    "cpu_count":         Server.cpu_count,
    "ram_gb":            Server.ram_gb,
    "location":          Location.name,
    "owner":             Owner.name,
    "status":            Server.status,
}

DEFAULT_SORT  = "hostname"
DEFAULT_ORDER = "asc"


@dataclass
class InventoryFilters:
    search:      str = ""
    location_id: int | None = None
    env_id:      int | None = None
    status:      str = ""
    source:      str = ""   # "" = all | "manual" | "vmware" | "ansible"
    sort:        str = DEFAULT_SORT
    order:       str = DEFAULT_ORDER


@dataclass
class InventoryPage:
    servers:      list  = field(default_factory=list)
    total:        int   = 0
    page:         int   = 1
    per_page:     int   = 25
    total_pages:  int   = 1
    filters:      InventoryFilters = field(default_factory=InventoryFilters)
    locations:    list  = field(default_factory=list)
    environments: list  = field(default_factory=list)
    owners:       list  = field(default_factory=list)
    statuses:     list  = field(default_factory=list)


def get_inventory_page(filters: InventoryFilters, page: int, per_page: int) -> InventoryPage:
    """
    Return a paginated, filtered, sorted slice of the server inventory.
    Always outer-joins Environment, Location, and Owner so nullable FKs
    still appear in results.
    """
    result = InventoryPage(filters=filters, page=page, per_page=per_page)

    try:
        # ── Base query (always outer-join related tables) ─────────────
        q = (
            db.session.query(Server)
            .outerjoin(Environment, Server.environment_id == Environment.id)
            .outerjoin(Location,    Server.location_id    == Location.id)
            .outerjoin(Owner,       Server.owner_id       == Owner.id)
        )

        # ── Search: hostname, IP address, or owner name ───────────────
        if filters.search:
            term = f"%{filters.search.strip()}%"
            q = q.filter(
                or_(
                    Server.hostname.ilike(term),
                    Server.fqdn.ilike(term),
                    Server.ip_address.ilike(term),
                    Owner.name.ilike(term),
                )
            )

        # ── Filters ───────────────────────────────────────────────────
        if filters.location_id:
            q = q.filter(Server.location_id == filters.location_id)

        if filters.env_id:
            q = q.filter(Server.environment_id == filters.env_id)

        if filters.status:
            q = q.filter(Server.status == filters.status)

        if filters.source:
            q = q.filter(Server.source == filters.source)

        # ── Total (before pagination) ─────────────────────────────────
        result.total = q.count()

        # ── Sort — NULLs always last regardless of direction ──────────
        sort_col = SORTABLE_COLUMNS.get(filters.sort, Server.hostname)
        order_fn = asc if filters.order == "asc" else desc
        q = q.order_by(order_fn(sort_col).nulls_last())

        # ── Pagination ────────────────────────────────────────────────
        offset = (page - 1) * per_page
        result.servers     = q.offset(offset).limit(per_page).all()
        result.total_pages = max(1, -(-result.total // per_page))   # ceiling division

        # ── Dropdown options (for filter bar and Add Server form) ─────
        result.locations    = Location.query.filter_by(is_active=True).order_by(Location.name).all()
        result.environments = sort_envs(Environment.query.filter_by(is_active=True).all())
        result.owners       = Owner.query.filter_by(is_active=True).order_by(Owner.name).all()
        result.statuses     = ["active", "inactive", "maintenance", "decommissioned"]

    except Exception:
        logger.exception("Failed to query inventory")

    return result

"""
Patching query helpers.

All database reads for the Patching module live here — keeps routes
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
from ...models.patching import Patching
from ...models.server import Server

logger = logging.getLogger(__name__)

# Columns that can be sorted, mapped to their SQLAlchemy expression.
# Related-model columns require the join already present in the query.
SORTABLE_COLUMNS: dict[str, object] = {
    "hostname":           Server.hostname,
    "environment":        Environment.name,
    "location":           Location.name,
    "operating_system":   Server.operating_system,
    "current_kernel":     Patching.current_kernel,
    "patch_status":       Patching.patch_status,
    "last_patch_date":    Patching.last_patch_date,
    "last_reboot_date":   Patching.last_reboot_date,
    "last_ansible_sync":  Server.last_ansible_sync,
    "owner":              Owner.name,
}

DEFAULT_SORT  = "hostname"
DEFAULT_ORDER = "asc"

VALID_PATCH_STATUSES = ["up-to-date", "pending", "failed", "unknown"]


@dataclass
class PatchingFilters:
    search:       str = ""
    location_id:  int | None = None
    env_id:       int | None = None
    patch_status: str = ""
    sort:         str = DEFAULT_SORT
    order:        str = DEFAULT_ORDER


@dataclass
class PatchingPage:
    servers:       list  = field(default_factory=list)
    total:         int   = 0
    page:          int   = 1
    per_page:      int   = 25
    total_pages:   int   = 1
    filters:       PatchingFilters = field(default_factory=PatchingFilters)
    locations:     list  = field(default_factory=list)
    environments:  list  = field(default_factory=list)
    patch_statuses: list = field(default_factory=list)


def get_patching_page(
    filters: PatchingFilters, page: int, per_page: int
) -> PatchingPage:
    """
    Return a paginated, filtered, sorted slice of the server patching view.

    Outer-joins Patching so servers with no patching record still appear
    (they show as 'unknown').  Always outer-joins Environment, Location,
    and Owner so nullable FKs don't drop rows.
    """
    result = PatchingPage(filters=filters, page=page, per_page=per_page)

    try:
        # ── Base query (all servers, patching data optional) ──────────
        q = (
            db.session.query(Server)
            .outerjoin(Patching,     Patching.server_id    == Server.id)
            .outerjoin(Environment,  Server.environment_id == Environment.id)
            .outerjoin(Location,     Server.location_id    == Location.id)
            .outerjoin(Owner,        Server.owner_id       == Owner.id)
        )

        # ── Search: hostname, IP address, or owner name ───────────────
        if filters.search:
            term = f"%{filters.search.strip()}%"
            q = q.filter(
                or_(
                    Server.hostname.ilike(term),
                    Server.ip_address.ilike(term),
                    Owner.name.ilike(term),
                )
            )

        # ── Filters ───────────────────────────────────────────────────
        if filters.location_id:
            q = q.filter(Server.location_id == filters.location_id)

        if filters.env_id:
            q = q.filter(Server.environment_id == filters.env_id)

        if filters.patch_status:
            if filters.patch_status == "unknown":
                # Servers with no patching record OR explicit 'unknown' status
                q = q.filter(
                    (Patching.id == None) |  # noqa: E711
                    (Patching.patch_status == "unknown")
                )
            else:
                q = q.filter(Patching.patch_status == filters.patch_status)

        # ── Total (before pagination) ─────────────────────────────────
        result.total = q.count()

        # ── Sort — NULLs always last regardless of direction ──────────
        sort_col = SORTABLE_COLUMNS.get(filters.sort, Server.hostname)
        order_fn = asc if filters.order == "asc" else desc
        q = q.order_by(order_fn(sort_col).nulls_last())

        # ── Pagination ────────────────────────────────────────────────
        offset = (page - 1) * per_page
        result.servers      = q.offset(offset).limit(per_page).all()
        result.total_pages  = max(1, -(-result.total // per_page))  # ceiling division

        # ── Dropdown options (for filter bar) ─────────────────────────
        result.locations    = Location.query.filter_by(is_active=True).order_by(Location.name).all()
        result.environments = Environment.query.filter_by(is_active=True).order_by(Environment.name).all()
        result.patch_statuses = VALID_PATCH_STATUSES

    except Exception:
        logger.exception("Failed to query patching page")

    return result

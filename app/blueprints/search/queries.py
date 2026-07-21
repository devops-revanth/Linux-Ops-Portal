"""
Search query helpers.

All database reads for the global Search module live here — keeps routes
thin and makes queries independently testable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import asc, desc, or_
from sqlalchemy.orm import contains_eager  # noqa: F401 (kept for parity)

from ...extensions import db
from ...models.environment import Environment
from ...models.location import Location
from ...models.owner import Owner
from ...models.patching import Patching
from ...models.server import Server

logger = logging.getLogger(__name__)

# Columns the user can sort on, mapped to their SQLAlchemy expression.
# All joined tables are always present (outer joins), so every column is safe.
SORTABLE_COLUMNS: dict[str, object] = {
    "hostname":         Server.hostname,
    "ip_address":       Server.ip_address,
    "environment":      Environment.name,
    "location":         Location.name,
    "operating_system": Server.operating_system,
    "kernel_version":   Server.kernel_version,
    "owner":            Owner.name,
    "patch_status":     Patching.patch_status,
}

DEFAULT_SORT  = "hostname"
DEFAULT_ORDER = "asc"


@dataclass
class SearchFilters:
    search: str = ""
    sort:   str = DEFAULT_SORT
    order:  str = DEFAULT_ORDER


@dataclass
class SearchPage:
    servers:     list  = field(default_factory=list)
    total:       int   = 0
    page:        int   = 1
    per_page:    int   = 25
    total_pages: int   = 1
    filters:     SearchFilters = field(default_factory=SearchFilters)


def get_search_page(
    filters: SearchFilters, page: int, per_page: int
) -> SearchPage:
    """
    Return a paginated, sorted slice of the global server search.

    Searches across: hostname, FQDN, IP address, owner name, operating
    system, kernel version, location name, and environment name.

    Outer-joins Patching so servers with no patching record still appear
    (shown as 'unknown').  Always outer-joins Environment, Location, and
    Owner so nullable FKs never drop rows.

    When no search term is provided the result set is empty — the template
    shows a prompt rather than dumping every server.
    """
    result = SearchPage(filters=filters, page=page, per_page=per_page)

    # No query → return the empty page immediately (don't flood the table).
    if not filters.search.strip():
        return result

    try:
        # ── Base query (all servers, patching/meta optional) ──────────
        q = (
            db.session.query(Server)
            .outerjoin(Patching,    Patching.server_id    == Server.id)
            .outerjoin(Environment, Server.environment_id == Environment.id)
            .outerjoin(Location,    Server.location_id    == Location.id)
            .outerjoin(Owner,       Server.owner_id       == Owner.id)
        )

        # ── Full-text partial, case-insensitive search ────────────────
        term = f"%{filters.search.strip()}%"
        q = q.filter(
            or_(
                Server.hostname.ilike(term),
                Server.fqdn.ilike(term),
                Server.ip_address.ilike(term),
                Owner.name.ilike(term),
                Server.operating_system.ilike(term),
                Server.kernel_version.ilike(term),
                Location.name.ilike(term),
                Environment.name.ilike(term),
            )
        )

        # ── Total (before pagination) ─────────────────────────────────
        result.total = q.count()

        # ── Sort — NULLs always last regardless of direction ──────────
        sort_col = SORTABLE_COLUMNS.get(filters.sort, Server.hostname)
        order_fn = asc if filters.order == "asc" else desc
        q = q.order_by(order_fn(sort_col).nulls_last())

        # ── Pagination ────────────────────────────────────────────────
        offset = (page - 1) * per_page
        result.servers     = q.offset(offset).limit(per_page).all()
        result.total_pages = max(1, -(-result.total // per_page))  # ceiling div

    except Exception:
        logger.exception("Failed to execute global search query")

    return result

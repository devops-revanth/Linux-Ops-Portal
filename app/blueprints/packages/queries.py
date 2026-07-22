"""
Packages query helpers.

Packages page is a fleet-level dashboard:
  1. Fleet stat cards  (servers managed, total packages, total available updates)
  2. Per-server table  (hostname, pkg count, updates, compliance, last inventory)

The server-detail packages tab handles per-server package listing separately
(see inventory/routes.py  server_detail()).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import asc, desc, func, select

from ...extensions import db
from ...models.package import Package, ServerPackage
from ...models.patching import Patching
from ...models.server import Server

logger = logging.getLogger(__name__)

VALID_SORTS = {"hostname", "packages", "updates", "last_inventory"}
DEFAULT_SORT  = "hostname"
DEFAULT_ORDER = "asc"


# ── Data transfer objects ────────────────────────────────────────────────── #

@dataclass
class PackageFleetSummary:
    servers_managed:    int      = 0
    installed_packages: int      = 0
    available_updates:  int      = 0
    security_updates:   int|None = None   # not yet in model
    kernel_updates:     int|None = None   # not yet in model


@dataclass
class PackagesFilters:
    search: str = ""
    sort:   str = DEFAULT_SORT
    order:  str = DEFAULT_ORDER


@dataclass
class PackagesPage:
    rows:        list            = field(default_factory=list)
    total:       int             = 0
    page:        int             = 1
    per_page:    int             = 25
    total_pages: int             = 1
    filters:     PackagesFilters = field(default_factory=PackagesFilters)


# ── Fleet summary ────────────────────────────────────────────────────────── #

def get_fleet_summary() -> PackageFleetSummary:
    """Aggregate stats shown in the top stat-card row."""
    try:
        servers_managed    = db.session.query(func.count(Server.id)).scalar() or 0
        installed_packages = db.session.query(func.count(ServerPackage.id)).scalar() or 0
        available_updates  = (
            db.session.query(func.coalesce(func.sum(Patching.pending_updates), 0))
            .filter(Patching.pending_updates > 0)
            .scalar() or 0
        )
        return PackageFleetSummary(
            servers_managed=servers_managed,
            installed_packages=installed_packages,
            available_updates=int(available_updates),
        )
    except Exception:
        logger.exception("Failed to compute fleet summary")
        return PackageFleetSummary()


# ── Per-server summary ───────────────────────────────────────────────────── #

def get_servers_package_summary(
    filters: PackagesFilters, page: int, per_page: int
) -> PackagesPage:
    """
    One row per server showing:  server, patching record, package count.

    Rows are tuples: (Server, Patching|None, pkg_count|None).
    """
    result = PackagesPage(filters=filters, page=page, per_page=per_page)
    try:
        # Subquery: package count per server
        pkg_sq = (
            select(
                ServerPackage.server_id,
                func.count(ServerPackage.id).label("pkg_count"),
            )
            .group_by(ServerPackage.server_id)
            .subquery()
        )

        q = (
            db.session.query(Server, Patching, pkg_sq.c.pkg_count)
            .outerjoin(Patching, Patching.server_id == Server.id)
            .outerjoin(pkg_sq,   pkg_sq.c.server_id == Server.id)
        )

        if filters.search:
            q = q.filter(Server.hostname.ilike(f"%{filters.search}%"))

        result.total = q.count()

        sort_col = {
            "hostname":       Server.hostname,
            "packages":       pkg_sq.c.pkg_count,
            "updates":        Patching.pending_updates,
            "last_inventory": Server.last_ansible_sync,
        }.get(filters.sort, Server.hostname)

        order_fn = asc if filters.order == "asc" else desc
        q = q.order_by(order_fn(sort_col).nulls_last())

        offset         = (page - 1) * per_page
        result.rows        = q.offset(offset).limit(per_page).all()
        result.total_pages = max(1, -(-result.total // per_page))
    except Exception:
        logger.exception("Failed to query servers package summary")
    return result

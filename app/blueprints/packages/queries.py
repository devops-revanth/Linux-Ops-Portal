"""
Packages query helpers.

Three data-sets served by the Packages page:
  • Installed Packages  — all ServerPackage rows joined with Package + Server
  • Available Updates   — servers whose Patching record shows pending_updates > 0
  • Recently Installed  — ServerPackage rows ordered by collected_at DESC
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import asc, desc, or_

from ...extensions import db
from ...models.package import Package, ServerPackage
from ...models.patching import Patching
from ...models.server import Server

logger = logging.getLogger(__name__)

# ── Sortable column maps ────────────────────────────────────────────────────

INSTALLED_SORT: dict[str, object] = {
    "name":         Package.name,
    "version":      ServerPackage.version,
    "install_date": ServerPackage.collected_at,
    "server":       Server.hostname,
}

UPDATES_SORT: dict[str, object] = {
    "server":       Server.hostname,
    "updates":      Patching.pending_updates,
    "last_patched": Patching.last_patch_date,
}

DEFAULT_SORT  = "name"
DEFAULT_ORDER = "asc"


# ── Shared filter / page dataclasses ────────────────────────────────────────

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


# ── Query helpers ────────────────────────────────────────────────────────────

def get_installed_page(
    filters: PackagesFilters, page: int, per_page: int
) -> PackagesPage:
    """All ServerPackage rows with their Package and Server details."""
    result = PackagesPage(filters=filters, page=page, per_page=per_page)
    try:
        q = (
            db.session.query(ServerPackage, Package, Server)
            .join(Package, ServerPackage.package_id == Package.id)
            .join(Server,  ServerPackage.server_id  == Server.id)
        )
        if filters.search:
            term = f"%{filters.search}%"
            q = q.filter(
                or_(Package.name.ilike(term), Server.hostname.ilike(term))
            )
        result.total = q.count()

        sort_col = INSTALLED_SORT.get(filters.sort, Package.name)
        order_fn = asc if filters.order == "asc" else desc
        q = q.order_by(order_fn(sort_col).nulls_last())

        offset = (page - 1) * per_page
        result.rows        = q.offset(offset).limit(per_page).all()
        result.total_pages = max(1, -(-result.total // per_page))
    except Exception:
        logger.exception("Failed to query installed packages")
    return result


def get_updates_page(
    filters: PackagesFilters, page: int, per_page: int
) -> PackagesPage:
    """Servers with pending_updates > 0 from their Patching record."""
    result = PackagesPage(filters=filters, page=page, per_page=per_page)
    try:
        q = (
            db.session.query(Server, Patching)
            .join(Patching, Patching.server_id == Server.id)
            .filter(Patching.pending_updates > 0)
        )
        if filters.search:
            term = f"%{filters.search}%"
            q = q.filter(Server.hostname.ilike(term))

        result.total = q.count()

        sort_col = UPDATES_SORT.get(filters.sort, Server.hostname)
        order_fn = asc if filters.order == "asc" else desc
        q = q.order_by(order_fn(sort_col).nulls_last())

        offset = (page - 1) * per_page
        result.rows        = q.offset(offset).limit(per_page).all()
        result.total_pages = max(1, -(-result.total // per_page))
    except Exception:
        logger.exception("Failed to query available updates")
    return result


def get_recently_installed_page(
    filters: PackagesFilters, page: int, per_page: int
) -> PackagesPage:
    """ServerPackage rows ordered by collected_at descending."""
    result = PackagesPage(filters=filters, page=page, per_page=per_page)
    try:
        q = (
            db.session.query(ServerPackage, Package, Server)
            .join(Package, ServerPackage.package_id == Package.id)
            .join(Server,  ServerPackage.server_id  == Server.id)
            .order_by(ServerPackage.collected_at.desc())
        )
        if filters.search:
            term = f"%{filters.search}%"
            q = q.filter(
                or_(Package.name.ilike(term), Server.hostname.ilike(term))
            )
        result.total = q.count()

        offset = (page - 1) * per_page
        result.rows        = q.offset(offset).limit(per_page).all()
        result.total_pages = max(1, -(-result.total // per_page))
    except Exception:
        logger.exception("Failed to query recently installed packages")
    return result

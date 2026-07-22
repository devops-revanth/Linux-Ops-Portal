"""
Search query helpers.

All database reads for the global Search module live here — keeps routes
thin and makes queries independently testable.

Supported search prefixes (smart search):
  package:<name>  — servers with that package installed
  service:<name>  — servers where that service is tracked
  repo:<name>     — servers that have that repository enabled
  (no prefix)     — full-text search across hostname/FQDN/IP/OS/etc.
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

# Smart-search prefix markers
_PREFIXES = ("package:", "service:", "repo:")


@dataclass
class SearchFilters:
    search:      str = ""
    sort:        str = DEFAULT_SORT
    order:       str = DEFAULT_ORDER
    search_type: str = "fulltext"   # fulltext | package | service | repo


@dataclass
class SearchPage:
    servers:     list  = field(default_factory=list)
    total:       int   = 0
    page:        int   = 1
    per_page:    int   = 25
    total_pages: int   = 1
    filters:     SearchFilters = field(default_factory=SearchFilters)


def _detect_prefix(raw: str) -> tuple[str, str]:
    """
    Detect a smart-search prefix.

    Returns (search_type, stripped_term).
    E.g. "package:openssl" → ("package", "openssl")
    """
    lower = raw.lower()
    for prefix in _PREFIXES:
        if lower.startswith(prefix):
            kind = prefix.rstrip(":")
            term = raw[len(prefix):].strip()
            return kind, term
    return "fulltext", raw.strip()


def get_search_page(
    filters: SearchFilters, page: int, per_page: int
) -> SearchPage:
    """
    Return a paginated, sorted slice of the global server search.

    Full-text mode searches across: hostname, FQDN, IP address, owner name,
    operating system, kernel version, location name, and environment name.

    Smart-search prefixes:
      package:<name>  → servers with that package installed
      service:<name>  → servers where that service name matches
      repo:<name>     → servers with a matching enabled repository

    Outer-joins Patching so servers with no patching record still appear.
    When no search term is provided the result set is empty.
    """
    result = SearchPage(filters=filters, page=page, per_page=per_page)

    if not filters.search.strip():
        return result

    # Detect prefix
    search_type, term = _detect_prefix(filters.search)
    filters.search_type = search_type

    try:
        if search_type == "package":
            q = _package_search(term)
        elif search_type == "service":
            q = _service_search(term)
        elif search_type == "repo":
            q = _repo_search(term)
        else:
            q = _fulltext_search(term)

        # ── Total (before pagination) ─────────────────────────────────
        result.total = q.count()

        # ── Sort — NULLs always last regardless of direction ──────────
        sort_col = SORTABLE_COLUMNS.get(filters.sort, Server.hostname)
        order_fn = asc if filters.order == "asc" else desc
        q = q.order_by(order_fn(sort_col).nulls_last())

        # ── Pagination ────────────────────────────────────────────────
        offset = (page - 1) * per_page
        result.servers     = q.offset(offset).limit(per_page).all()
        result.total_pages = max(1, -(-result.total // per_page))

    except Exception:
        logger.exception("Failed to execute global search query")

    return result


# ── Query builders ────────────────────────────────────────────────────────── #

def _base_q():
    """Base query joining optional metadata tables."""
    return (
        db.session.query(Server)
        .outerjoin(Patching,    Patching.server_id    == Server.id)
        .outerjoin(Environment, Server.environment_id == Environment.id)
        .outerjoin(Location,    Server.location_id    == Location.id)
        .outerjoin(Owner,       Server.owner_id       == Owner.id)
        .distinct()
    )


def _fulltext_search(term: str):
    pat = f"%{term}%"
    return _base_q().filter(
        or_(
            Server.hostname.ilike(pat),
            Server.fqdn.ilike(pat),
            Server.ip_address.ilike(pat),
            Owner.name.ilike(pat),
            Server.operating_system.ilike(pat),
            Server.kernel_version.ilike(pat),
            Location.name.ilike(pat),
            Environment.name.ilike(pat),
        )
    )


def _package_search(term: str):
    """Return servers that have a package matching the search term (installed or with updates)."""
    try:
        from ...models.package import Package, ServerPackage
        pat = f"%{term}%"
        return (
            _base_q()
            .join(ServerPackage, ServerPackage.server_id == Server.id)
            .join(Package,       Package.id == ServerPackage.package_id)
            .filter(Package.name.ilike(pat))
        )
    except Exception:
        logger.warning("package_search: could not join Package tables")
        return _base_q().filter(Server.id == None)  # noqa: E711 — empty result


def _service_search(term: str):
    """Return servers where a tracked service matches the search term."""
    try:
        from ...models.ansible_facts import AnsibleServerService
        pat = f"%{term}%"
        return (
            _base_q()
            .join(AnsibleServerService, AnsibleServerService.server_id == Server.id)
            .filter(AnsibleServerService.name.ilike(pat))
        )
    except Exception:
        logger.warning("service_search: could not join AnsibleServerService")
        return _base_q().filter(Server.id == None)  # noqa: E711


def _repo_search(term: str):
    """Return servers that have an enabled repository matching the search term."""
    try:
        from ...models.ansible_facts import AnsibleRepository
        pat = f"%{term}%"
        return (
            _base_q()
            .join(AnsibleRepository, AnsibleRepository.server_id == Server.id)
            .filter(
                or_(
                    AnsibleRepository.repo_id.ilike(pat),
                    AnsibleRepository.repo_name.ilike(pat),
                )
            )
        )
    except Exception:
        logger.warning("repo_search: could not join AnsibleRepository")
        return _base_q().filter(Server.id == None)  # noqa: E711

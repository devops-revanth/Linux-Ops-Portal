"""
Reports query helpers.

All database reads for the Reports module live here — keeps routes thin
and makes queries independently testable.

Seven reports are implemented:
  1. Server Inventory Report
  2. Servers by Location
  3. Servers by Environment
  4. Patch Compliance Report
  5. Kernel Compliance Report
  6. Owner Summary Report
  7. Recently Synchronized Servers
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import asc, desc, func, or_

from ...extensions import db
from ...models.environment import Environment
from ...models.location import Location
from ...models.owner import Owner
from ...models.patching import Patching
from ...models.server import Server

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────── #
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────── #

def _base_server_query():
    """Return a query joining all related tables to Server."""
    return (
        db.session.query(Server)
        .outerjoin(Environment, Server.environment_id == Environment.id)
        .outerjoin(Location,    Server.location_id    == Location.id)
        .outerjoin(Owner,       Server.owner_id       == Owner.id)
    )


def _paginate(q, page: int, per_page: int):
    total = q.count()
    total_pages = max(1, -(-total // per_page))   # ceiling division
    offset = (page - 1) * per_page
    rows = q.offset(offset).limit(per_page).all()
    return rows, total, total_pages


def _ref_data():
    """Return dropdown lists used across multiple reports."""
    return {
        "locations":    Location.query.filter_by(is_active=True).order_by(Location.name).all(),
        "environments": Environment.query.filter_by(is_active=True).order_by(Environment.name).all(),
        "owners":       Owner.query.filter_by(is_active=True).order_by(Owner.name).all(),
    }


# ═══════════════════════════════════════════════════════════════════════════ #
# 1. Server Inventory Report
# ═══════════════════════════════════════════════════════════════════════════ #

INVENTORY_SORTABLE: dict[str, object] = {
    "hostname":          Server.hostname,
    "ip_address":        Server.ip_address,
    "environment":       Environment.name,
    "location":          Location.name,
    "owner":             Owner.name,
    "operating_system":  Server.operating_system,
    "os_version":        Server.os_version,
    "kernel_version":    Server.kernel_version,
    "cpu_count":         Server.cpu_count,
    "ram_gb":            Server.ram_gb,
    "status":            Server.status,
    "created_at":        Server.created_at,
    "last_ansible_sync": Server.last_ansible_sync,
}

INVENTORY_DEFAULT_SORT  = "hostname"
INVENTORY_DEFAULT_ORDER = "asc"


@dataclass
class InventoryReportFilters:
    search:      str       = ""
    location_id: int | None = None
    env_id:      int | None = None
    owner_id:    int | None = None
    status:      str       = ""
    sort:        str       = INVENTORY_DEFAULT_SORT
    order:       str       = INVENTORY_DEFAULT_ORDER


@dataclass
class InventoryReportPage:
    servers:      list                  = field(default_factory=list)
    total:        int                   = 0
    page:         int                   = 1
    per_page:     int                   = 25
    total_pages:  int                   = 1
    filters:      InventoryReportFilters = field(default_factory=InventoryReportFilters)
    locations:    list                  = field(default_factory=list)
    environments: list                  = field(default_factory=list)
    owners:       list                  = field(default_factory=list)
    statuses:     list                  = field(default_factory=list)


def _inventory_report_query(filters: InventoryReportFilters):
    q = _base_server_query()

    if filters.search:
        term = f"%{filters.search.strip()}%"
        q = q.filter(or_(
            Server.hostname.ilike(term),
            Server.ip_address.ilike(term),
            Owner.name.ilike(term),
            Server.operating_system.ilike(term),
        ))

    if filters.location_id:
        q = q.filter(Server.location_id == filters.location_id)
    if filters.env_id:
        q = q.filter(Server.environment_id == filters.env_id)
    if filters.owner_id:
        q = q.filter(Server.owner_id == filters.owner_id)
    if filters.status:
        q = q.filter(Server.status == filters.status)

    sort_col = INVENTORY_SORTABLE.get(filters.sort, Server.hostname)
    order_fn = asc if filters.order == "asc" else desc
    q = q.order_by(order_fn(sort_col).nulls_last())

    return q


def get_inventory_report(
    filters: InventoryReportFilters, page: int, per_page: int
) -> InventoryReportPage:
    result = InventoryReportPage(filters=filters, page=page, per_page=per_page)
    try:
        q = _inventory_report_query(filters)
        result.servers, result.total, result.total_pages = _paginate(q, page, per_page)
        ref = _ref_data()
        result.locations    = ref["locations"]
        result.environments = ref["environments"]
        result.owners       = ref["owners"]
        result.statuses     = ["active", "inactive", "maintenance", "decommissioned"]
    except Exception:
        logger.exception("Failed to query inventory report")
    return result


def get_inventory_report_export(filters: InventoryReportFilters) -> list:
    """Return all rows (no pagination) for export."""
    try:
        return _inventory_report_query(filters).all()
    except Exception:
        logger.exception("Failed to export inventory report")
        return []


# ═══════════════════════════════════════════════════════════════════════════ #
# 2. Servers by Location
# ═══════════════════════════════════════════════════════════════════════════ #

BY_LOCATION_SORTABLE: dict[str, object] = {
    "hostname":    Server.hostname,
    "ip_address":  Server.ip_address,
    "environment": Environment.name,
    "owner":       Owner.name,
    "status":      Server.status,
    "os":          Server.operating_system,
}

BY_LOCATION_DEFAULT_SORT  = "hostname"
BY_LOCATION_DEFAULT_ORDER = "asc"


@dataclass
class LocationSummaryRow:
    location_name: str
    total:         int
    active:        int
    inactive:      int
    maintenance:   int
    decommissioned: int
    percent:       float


@dataclass
class ByLocationFilters:
    search:      str       = ""
    location_id: int | None = None
    env_id:      int | None = None
    status:      str       = ""
    sort:        str       = BY_LOCATION_DEFAULT_SORT
    order:       str       = BY_LOCATION_DEFAULT_ORDER


@dataclass
class ByLocationPage:
    summary:      list           = field(default_factory=list)
    servers:      list           = field(default_factory=list)
    total:        int            = 0
    page:         int            = 1
    per_page:     int            = 25
    total_pages:  int            = 1
    filters:      ByLocationFilters = field(default_factory=ByLocationFilters)
    locations:    list           = field(default_factory=list)
    environments: list           = field(default_factory=list)


def _by_location_server_query(filters: ByLocationFilters):
    q = _base_server_query()

    if filters.search:
        term = f"%{filters.search.strip()}%"
        q = q.filter(or_(
            Server.hostname.ilike(term),
            Server.ip_address.ilike(term),
            Owner.name.ilike(term),
        ))
    if filters.location_id:
        q = q.filter(Server.location_id == filters.location_id)
    if filters.env_id:
        q = q.filter(Server.environment_id == filters.env_id)
    if filters.status:
        q = q.filter(Server.status == filters.status)

    sort_col = BY_LOCATION_SORTABLE.get(filters.sort, Server.hostname)
    order_fn = asc if filters.order == "asc" else desc
    q = q.order_by(order_fn(sort_col).nulls_last(), Server.hostname.asc())
    return q


def get_by_location_report(
    filters: ByLocationFilters, page: int, per_page: int
) -> ByLocationPage:
    result = ByLocationPage(filters=filters, page=page, per_page=per_page)
    try:
        # Summary: count per location
        total_all = db.session.query(func.count(Server.id)).scalar() or 1
        loc_rows = (
            db.session.query(
                Location.name,
                func.count(Server.id).label("total"),
                func.sum(
                    db.case((Server.status == "active", 1), else_=0)
                ).label("active"),
                func.sum(
                    db.case((Server.status == "inactive", 1), else_=0)
                ).label("inactive"),
                func.sum(
                    db.case((Server.status == "maintenance", 1), else_=0)
                ).label("maintenance"),
                func.sum(
                    db.case((Server.status == "decommissioned", 1), else_=0)
                ).label("decommissioned"),
            )
            .outerjoin(Server, Server.location_id == Location.id)
            .filter(Location.is_active == True)  # noqa: E712
            .group_by(Location.id, Location.name)
            .order_by(func.count(Server.id).desc())
            .all()
        )
        result.summary = [
            LocationSummaryRow(
                location_name  = r.name,
                total          = r.total or 0,
                active         = r.active or 0,
                inactive       = r.inactive or 0,
                maintenance    = r.maintenance or 0,
                decommissioned = r.decommissioned or 0,
                percent        = round((r.total or 0) / total_all * 100, 1),
            )
            for r in loc_rows
        ]

        q = _by_location_server_query(filters)
        result.servers, result.total, result.total_pages = _paginate(q, page, per_page)
        ref = _ref_data()
        result.locations    = ref["locations"]
        result.environments = ref["environments"]
    except Exception:
        logger.exception("Failed to query by-location report")
    return result


def get_by_location_export(filters: ByLocationFilters) -> list:
    try:
        return _by_location_server_query(filters).all()
    except Exception:
        logger.exception("Failed to export by-location report")
        return []


# ═══════════════════════════════════════════════════════════════════════════ #
# 3. Servers by Environment
# ═══════════════════════════════════════════════════════════════════════════ #

BY_ENV_SORTABLE: dict[str, object] = {
    "hostname":   Server.hostname,
    "ip_address": Server.ip_address,
    "location":   Location.name,
    "owner":      Owner.name,
    "status":     Server.status,
    "os":         Server.operating_system,
}

BY_ENV_DEFAULT_SORT  = "hostname"
BY_ENV_DEFAULT_ORDER = "asc"


@dataclass
class EnvSummaryRow:
    env_name:      str
    env_label:     str
    env_color:     str
    total:         int
    active:        int
    inactive:      int
    maintenance:   int
    decommissioned: int
    percent:       float


@dataclass
class ByEnvironmentFilters:
    search:      str       = ""
    env_id:      int | None = None
    location_id: int | None = None
    status:      str       = ""
    sort:        str       = BY_ENV_DEFAULT_SORT
    order:       str       = BY_ENV_DEFAULT_ORDER


@dataclass
class ByEnvironmentPage:
    summary:      list                = field(default_factory=list)
    servers:      list                = field(default_factory=list)
    total:        int                 = 0
    page:         int                 = 1
    per_page:     int                 = 25
    total_pages:  int                 = 1
    filters:      ByEnvironmentFilters = field(default_factory=ByEnvironmentFilters)
    locations:    list                = field(default_factory=list)
    environments: list                = field(default_factory=list)


def _by_env_server_query(filters: ByEnvironmentFilters):
    q = _base_server_query()
    if filters.search:
        term = f"%{filters.search.strip()}%"
        q = q.filter(or_(
            Server.hostname.ilike(term),
            Server.ip_address.ilike(term),
            Owner.name.ilike(term),
        ))
    if filters.env_id:
        q = q.filter(Server.environment_id == filters.env_id)
    if filters.location_id:
        q = q.filter(Server.location_id == filters.location_id)
    if filters.status:
        q = q.filter(Server.status == filters.status)

    sort_col = BY_ENV_SORTABLE.get(filters.sort, Server.hostname)
    order_fn = asc if filters.order == "asc" else desc
    q = q.order_by(order_fn(sort_col).nulls_last(), Server.hostname.asc())
    return q


def get_by_environment_report(
    filters: ByEnvironmentFilters, page: int, per_page: int
) -> ByEnvironmentPage:
    result = ByEnvironmentPage(filters=filters, page=page, per_page=per_page)
    try:
        total_all = db.session.query(func.count(Server.id)).scalar() or 1
        env_rows = (
            db.session.query(
                Environment.name,
                Environment.label,
                Environment.color,
                func.count(Server.id).label("total"),
                func.sum(
                    db.case((Server.status == "active", 1), else_=0)
                ).label("active"),
                func.sum(
                    db.case((Server.status == "inactive", 1), else_=0)
                ).label("inactive"),
                func.sum(
                    db.case((Server.status == "maintenance", 1), else_=0)
                ).label("maintenance"),
                func.sum(
                    db.case((Server.status == "decommissioned", 1), else_=0)
                ).label("decommissioned"),
            )
            .outerjoin(Server, Server.environment_id == Environment.id)
            .filter(Environment.is_active == True)  # noqa: E712
            .group_by(Environment.id, Environment.name, Environment.label, Environment.color)
            .order_by(func.count(Server.id).desc())
            .all()
        )
        result.summary = [
            EnvSummaryRow(
                env_name       = r.name,
                env_label      = r.label,
                env_color      = r.color,
                total          = r.total or 0,
                active         = r.active or 0,
                inactive       = r.inactive or 0,
                maintenance    = r.maintenance or 0,
                decommissioned = r.decommissioned or 0,
                percent        = round((r.total or 0) / total_all * 100, 1),
            )
            for r in env_rows
        ]

        q = _by_env_server_query(filters)
        result.servers, result.total, result.total_pages = _paginate(q, page, per_page)
        ref = _ref_data()
        result.locations    = ref["locations"]
        result.environments = ref["environments"]
    except Exception:
        logger.exception("Failed to query by-environment report")
    return result


def get_by_environment_export(filters: ByEnvironmentFilters) -> list:
    try:
        return _by_env_server_query(filters).all()
    except Exception:
        logger.exception("Failed to export by-environment report")
        return []


# ═══════════════════════════════════════════════════════════════════════════ #
# 4. Patch Compliance Report
# ═══════════════════════════════════════════════════════════════════════════ #

PATCH_SORTABLE: dict[str, object] = {
    "hostname":          Server.hostname,
    "environment":       Environment.name,
    "location":          Location.name,
    "operating_system":  Server.operating_system,
    "current_kernel":    Patching.current_kernel,
    "patch_status":      Patching.patch_status,
    "pending_updates":   Patching.pending_updates,
    "last_patch_date":   Patching.last_patch_date,
    "last_reboot_date":  Patching.last_reboot_date,
    "last_ansible_sync": Server.last_ansible_sync,
    "owner":             Owner.name,
}

PATCH_DEFAULT_SORT  = "patch_status"
PATCH_DEFAULT_ORDER = "asc"
VALID_PATCH_STATUSES = ["up-to-date", "pending", "failed", "unknown"]


@dataclass
class PatchComplianceFilters:
    search:       str       = ""
    location_id:  int | None = None
    env_id:       int | None = None
    patch_status: str       = ""
    sort:         str       = PATCH_DEFAULT_SORT
    order:        str       = PATCH_DEFAULT_ORDER


@dataclass
class PatchCompliancePage:
    servers:        list                   = field(default_factory=list)
    total:          int                    = 0
    page:           int                    = 1
    per_page:       int                    = 25
    total_pages:    int                    = 1
    filters:        PatchComplianceFilters = field(default_factory=PatchComplianceFilters)
    locations:      list                   = field(default_factory=list)
    environments:   list                   = field(default_factory=list)
    patch_statuses: list                   = field(default_factory=list)
    # summary counts
    count_up_to_date: int = 0
    count_pending:    int = 0
    count_failed:     int = 0
    count_unknown:    int = 0


def _patch_compliance_query(filters: PatchComplianceFilters):
    q = (
        db.session.query(Server)
        .outerjoin(Patching,    Patching.server_id    == Server.id)
        .outerjoin(Environment, Server.environment_id == Environment.id)
        .outerjoin(Location,    Server.location_id    == Location.id)
        .outerjoin(Owner,       Server.owner_id       == Owner.id)
    )

    if filters.search:
        term = f"%{filters.search.strip()}%"
        q = q.filter(or_(
            Server.hostname.ilike(term),
            Server.ip_address.ilike(term),
            Owner.name.ilike(term),
        ))
    if filters.location_id:
        q = q.filter(Server.location_id == filters.location_id)
    if filters.env_id:
        q = q.filter(Server.environment_id == filters.env_id)
    if filters.patch_status:
        if filters.patch_status == "unknown":
            q = q.filter(
                (Patching.id == None) |  # noqa: E711
                (Patching.patch_status == "unknown")
            )
        else:
            q = q.filter(Patching.patch_status == filters.patch_status)

    sort_col = PATCH_SORTABLE.get(filters.sort, Server.hostname)
    order_fn = asc if filters.order == "asc" else desc
    q = q.order_by(order_fn(sort_col).nulls_last(), Server.hostname.asc())
    return q


def get_patch_compliance_report(
    filters: PatchComplianceFilters, page: int, per_page: int
) -> PatchCompliancePage:
    result = PatchCompliancePage(filters=filters, page=page, per_page=per_page)
    try:
        q = _patch_compliance_query(filters)
        result.servers, result.total, result.total_pages = _paginate(q, page, per_page)
        ref = _ref_data()
        result.locations      = ref["locations"]
        result.environments   = ref["environments"]
        result.patch_statuses = VALID_PATCH_STATUSES

        # Summary counts (always over the full un-filtered dataset)
        status_rows = (
            db.session.query(
                Patching.patch_status,
                func.count(Patching.id).label("cnt"),
            )
            .group_by(Patching.patch_status)
            .all()
        )
        status_map = {r.patch_status: r.cnt for r in status_rows}
        total_servers  = db.session.query(func.count(Server.id)).scalar() or 0
        patched_count  = sum(status_map.values())
        result.count_up_to_date = status_map.get("up-to-date", 0)
        result.count_pending    = status_map.get("pending",    0)
        result.count_failed     = status_map.get("failed",     0)
        result.count_unknown    = (total_servers - patched_count) + status_map.get("unknown", 0)
    except Exception:
        logger.exception("Failed to query patch compliance report")
    return result


def get_patch_compliance_export(filters: PatchComplianceFilters) -> list:
    try:
        return _patch_compliance_query(filters).all()
    except Exception:
        logger.exception("Failed to export patch compliance report")
        return []


# ═══════════════════════════════════════════════════════════════════════════ #
# 5. Kernel Compliance Report
# ═══════════════════════════════════════════════════════════════════════════ #

KERNEL_SORTABLE: dict[str, object] = {
    "hostname":          Server.hostname,
    "environment":       Environment.name,
    "location":          Location.name,
    "operating_system":  Server.operating_system,
    "current_kernel":    Patching.current_kernel,
    "previous_kernel":   Patching.previous_kernel,
    "last_reboot_date":  Patching.last_reboot_date,
    "last_ansible_sync": Server.last_ansible_sync,
    "owner":             Owner.name,
}

KERNEL_DEFAULT_SORT  = "current_kernel"
KERNEL_DEFAULT_ORDER = "asc"


@dataclass
class KernelComplianceFilters:
    search:      str       = ""
    location_id: int | None = None
    env_id:      int | None = None
    kernel:      str       = ""
    sort:        str       = KERNEL_DEFAULT_SORT
    order:       str       = KERNEL_DEFAULT_ORDER


@dataclass
class KernelSummaryRow:
    kernel_version: str
    count:          int
    percent:        float


@dataclass
class KernelCompliancePage:
    servers:        list                   = field(default_factory=list)
    kernel_summary: list                   = field(default_factory=list)
    total:          int                    = 0
    page:           int                    = 1
    per_page:       int                    = 25
    total_pages:    int                    = 1
    filters:        KernelComplianceFilters = field(default_factory=KernelComplianceFilters)
    locations:      list                   = field(default_factory=list)
    environments:   list                   = field(default_factory=list)
    distinct_kernels: list                 = field(default_factory=list)


def _kernel_compliance_query(filters: KernelComplianceFilters):
    q = (
        db.session.query(Server)
        .outerjoin(Patching,    Patching.server_id    == Server.id)
        .outerjoin(Environment, Server.environment_id == Environment.id)
        .outerjoin(Location,    Server.location_id    == Location.id)
        .outerjoin(Owner,       Server.owner_id       == Owner.id)
    )

    if filters.search:
        term = f"%{filters.search.strip()}%"
        q = q.filter(or_(
            Server.hostname.ilike(term),
            Server.ip_address.ilike(term),
            Patching.current_kernel.ilike(term),
        ))
    if filters.location_id:
        q = q.filter(Server.location_id == filters.location_id)
    if filters.env_id:
        q = q.filter(Server.environment_id == filters.env_id)
    if filters.kernel:
        q = q.filter(
            (Patching.current_kernel == filters.kernel) |
            (Server.kernel_version   == filters.kernel)
        )

    sort_col = KERNEL_SORTABLE.get(filters.sort, Patching.current_kernel)
    order_fn = asc if filters.order == "asc" else desc
    q = q.order_by(order_fn(sort_col).nulls_last(), Server.hostname.asc())
    return q


def get_kernel_compliance_report(
    filters: KernelComplianceFilters, page: int, per_page: int
) -> KernelCompliancePage:
    result = KernelCompliancePage(filters=filters, page=page, per_page=per_page)
    try:
        q = _kernel_compliance_query(filters)
        result.servers, result.total, result.total_pages = _paginate(q, page, per_page)
        ref = _ref_data()
        result.locations    = ref["locations"]
        result.environments = ref["environments"]

        # Kernel version distribution (always unfiltered for summary bar)
        total_with_kernel = (
            db.session.query(func.count(Patching.id))
            .filter(Patching.current_kernel != None)  # noqa: E711
            .scalar()
        ) or 1
        kernel_rows = (
            db.session.query(
                Patching.current_kernel,
                func.count(Patching.id).label("cnt"),
            )
            .filter(Patching.current_kernel != None)  # noqa: E711
            .group_by(Patching.current_kernel)
            .order_by(func.count(Patching.id).desc())
            .limit(20)
            .all()
        )
        result.kernel_summary = [
            KernelSummaryRow(
                kernel_version = r.current_kernel,
                count          = r.cnt,
                percent        = round(r.cnt / total_with_kernel * 100, 1),
            )
            for r in kernel_rows
        ]

        # Distinct kernels for filter dropdown
        distinct = (
            db.session.query(Patching.current_kernel)
            .filter(Patching.current_kernel != None)  # noqa: E711
            .distinct()
            .order_by(Patching.current_kernel)
            .all()
        )
        result.distinct_kernels = [r.current_kernel for r in distinct]
    except Exception:
        logger.exception("Failed to query kernel compliance report")
    return result


def get_kernel_compliance_export(filters: KernelComplianceFilters) -> list:
    try:
        return _kernel_compliance_query(filters).all()
    except Exception:
        logger.exception("Failed to export kernel compliance report")
        return []


# ═══════════════════════════════════════════════════════════════════════════ #
# 6. Owner Summary Report
# ═══════════════════════════════════════════════════════════════════════════ #

OWNER_SORTABLE: dict[str, object] = {
    "name":          Owner.name,
    "total":         func.count(Server.id),
}

OWNER_DEFAULT_SORT  = "total"
OWNER_DEFAULT_ORDER = "desc"


@dataclass
class OwnerSummaryRow:
    owner_id:       int
    owner_name:     str
    owner_email:    str | None
    total:          int
    active:         int
    inactive:       int
    maintenance:    int
    decommissioned: int


@dataclass
class OwnerSummaryFilters:
    search: str = ""
    sort:   str = OWNER_DEFAULT_SORT
    order:  str = OWNER_DEFAULT_ORDER


@dataclass
class OwnerSummaryPage:
    rows:        list               = field(default_factory=list)
    total:       int                = 0
    page:        int                = 1
    per_page:    int                = 25
    total_pages: int                = 1
    filters:     OwnerSummaryFilters = field(default_factory=OwnerSummaryFilters)


def get_owner_summary_report(
    filters: OwnerSummaryFilters, page: int, per_page: int
) -> OwnerSummaryPage:
    result = OwnerSummaryPage(filters=filters, page=page, per_page=per_page)
    try:
        q = (
            db.session.query(
                Owner.id,
                Owner.name,
                Owner.email,
                func.count(Server.id).label("total"),
                func.sum(
                    db.case((Server.status == "active", 1), else_=0)
                ).label("active"),
                func.sum(
                    db.case((Server.status == "inactive", 1), else_=0)
                ).label("inactive"),
                func.sum(
                    db.case((Server.status == "maintenance", 1), else_=0)
                ).label("maintenance"),
                func.sum(
                    db.case((Server.status == "decommissioned", 1), else_=0)
                ).label("decommissioned"),
            )
            .outerjoin(Server, Server.owner_id == Owner.id)
            .filter(Owner.is_active == True)  # noqa: E712
            .group_by(Owner.id, Owner.name, Owner.email)
        )

        if filters.search:
            term = f"%{filters.search.strip()}%"
            q = q.filter(Owner.name.ilike(term))

        # Sorting for aggregated query
        if filters.sort == "name":
            order_col = Owner.name
        else:
            order_col = func.count(Server.id)

        order_fn = asc if filters.order == "asc" else desc
        q = q.order_by(order_fn(order_col))

        result.total      = q.count()
        result.total_pages = max(1, -(-result.total // per_page))
        offset = (page - 1) * per_page
        rows   = q.offset(offset).limit(per_page).all()

        result.rows = [
            OwnerSummaryRow(
                owner_id       = r.id,
                owner_name     = r.name,
                owner_email    = r.email,
                total          = r.total or 0,
                active         = r.active or 0,
                inactive       = r.inactive or 0,
                maintenance    = r.maintenance or 0,
                decommissioned = r.decommissioned or 0,
            )
            for r in rows
        ]
    except Exception:
        logger.exception("Failed to query owner summary report")
    return result


def get_owner_summary_export(filters: OwnerSummaryFilters) -> list:
    """Return all owner summary rows for export."""
    try:
        result = get_owner_summary_report(filters, page=1, per_page=10_000)
        return result.rows
    except Exception:
        logger.exception("Failed to export owner summary report")
        return []


# ═══════════════════════════════════════════════════════════════════════════ #
# 7. Recently Synchronized Servers
# ═══════════════════════════════════════════════════════════════════════════ #

RECENT_SORTABLE: dict[str, object] = {
    "hostname":          Server.hostname,
    "environment":       Environment.name,
    "location":          Location.name,
    "operating_system":  Server.operating_system,
    "patch_status":      Patching.patch_status,
    "last_ansible_sync": Server.last_ansible_sync,
    "owner":             Owner.name,
}

RECENT_DEFAULT_SORT  = "last_ansible_sync"
RECENT_DEFAULT_ORDER = "desc"


@dataclass
class RecentlySyncedFilters:
    search:      str       = ""
    location_id: int | None = None
    env_id:      int | None = None
    sort:        str       = RECENT_DEFAULT_SORT
    order:       str       = RECENT_DEFAULT_ORDER


@dataclass
class RecentlySyncedPage:
    servers:      list                = field(default_factory=list)
    total:        int                 = 0
    page:         int                 = 1
    per_page:     int                 = 25
    total_pages:  int                 = 1
    filters:      RecentlySyncedFilters = field(default_factory=RecentlySyncedFilters)
    locations:    list                = field(default_factory=list)
    environments: list                = field(default_factory=list)
    # Servers never synced
    never_synced: int                 = 0


def _recently_synced_query(filters: RecentlySyncedFilters):
    q = (
        db.session.query(Server)
        .outerjoin(Patching,    Patching.server_id    == Server.id)
        .outerjoin(Environment, Server.environment_id == Environment.id)
        .outerjoin(Location,    Server.location_id    == Location.id)
        .outerjoin(Owner,       Server.owner_id       == Owner.id)
    )

    if filters.search:
        term = f"%{filters.search.strip()}%"
        q = q.filter(or_(
            Server.hostname.ilike(term),
            Server.ip_address.ilike(term),
            Owner.name.ilike(term),
        ))
    if filters.location_id:
        q = q.filter(Server.location_id == filters.location_id)
    if filters.env_id:
        q = q.filter(Server.environment_id == filters.env_id)

    sort_col = RECENT_SORTABLE.get(filters.sort, Server.last_ansible_sync)
    order_fn = asc if filters.order == "asc" else desc
    q = q.order_by(order_fn(sort_col).nulls_last(), Server.hostname.asc())
    return q


def get_recently_synced_report(
    filters: RecentlySyncedFilters, page: int, per_page: int
) -> RecentlySyncedPage:
    result = RecentlySyncedPage(filters=filters, page=page, per_page=per_page)
    try:
        q = _recently_synced_query(filters)
        result.servers, result.total, result.total_pages = _paginate(q, page, per_page)
        ref = _ref_data()
        result.locations    = ref["locations"]
        result.environments = ref["environments"]
        result.never_synced = (
            db.session.query(func.count(Server.id))
            .filter(Server.last_ansible_sync == None)  # noqa: E711
            .scalar()
        ) or 0
    except Exception:
        logger.exception("Failed to query recently synced report")
    return result


def get_recently_synced_export(filters: RecentlySyncedFilters) -> list:
    try:
        return _recently_synced_query(filters).all()
    except Exception:
        logger.exception("Failed to export recently synced report")
        return []

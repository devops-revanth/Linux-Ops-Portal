"""
Reports query helpers.

Four reports:
  1. Server Inventory Report
  2. Infrastructure Summary (servers by location and environment)
  3. Patch Compliance Report
  4. Synchronization Report
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
    search:      str        = ""
    location_id: int | None = None
    env_id:      int | None = None
    owner_id:    int | None = None
    status:      str        = ""
    sort:        str        = INVENTORY_DEFAULT_SORT
    order:       str        = INVENTORY_DEFAULT_ORDER


@dataclass
class InventoryReportPage:
    servers:      list                   = field(default_factory=list)
    total:        int                    = 0
    page:         int                    = 1
    per_page:     int                    = 25
    total_pages:  int                    = 1
    filters:      InventoryReportFilters = field(default_factory=InventoryReportFilters)
    locations:    list                   = field(default_factory=list)
    environments: list                   = field(default_factory=list)
    owners:       list                   = field(default_factory=list)
    statuses:     list                   = field(default_factory=list)


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
# 2. Infrastructure Summary
# ═══════════════════════════════════════════════════════════════════════════ #

INFRA_SORTABLE: dict[str, object] = {
    "hostname":    Server.hostname,
    "ip_address":  Server.ip_address,
    "environment": Environment.name,
    "location":    Location.name,
    "owner":       Owner.name,
    "status":      Server.status,
    "os":          Server.operating_system,
}

INFRA_DEFAULT_SORT  = "hostname"
INFRA_DEFAULT_ORDER = "asc"


@dataclass
class LocationSummaryRow:
    location_id:    int
    location_name:  str
    total:          int
    active:         int
    inactive:       int
    maintenance:    int
    decommissioned: int
    percent:        float


@dataclass
class EnvSummaryRow:
    env_id:         int
    env_name:       str
    env_label:      str
    env_color:      str
    total:          int
    active:         int
    inactive:       int
    maintenance:    int
    decommissioned: int
    percent:        float


@dataclass
class InfrastructureFilters:
    search:      str        = ""
    location_id: int | None = None
    env_id:      int | None = None
    status:      str        = ""
    sort:        str        = INFRA_DEFAULT_SORT
    order:       str        = INFRA_DEFAULT_ORDER


@dataclass
class InfrastructurePage:
    loc_summary:  list                = field(default_factory=list)
    env_summary:  list                = field(default_factory=list)
    servers:      list                = field(default_factory=list)
    total:        int                 = 0
    page:         int                 = 1
    per_page:     int                 = 25
    total_pages:  int                 = 1
    filters:      InfrastructureFilters = field(default_factory=InfrastructureFilters)
    locations:    list                = field(default_factory=list)
    environments: list                = field(default_factory=list)


def _infra_server_query(filters: InfrastructureFilters):
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

    sort_col = INFRA_SORTABLE.get(filters.sort, Server.hostname)
    order_fn = asc if filters.order == "asc" else desc
    q = q.order_by(order_fn(sort_col).nulls_last(), Server.hostname.asc())
    return q


def get_infrastructure_summary(
    filters: InfrastructureFilters, page: int, per_page: int
) -> InfrastructurePage:
    result = InfrastructurePage(filters=filters, page=page, per_page=per_page)
    try:
        total_all = db.session.query(func.count(Server.id)).scalar() or 1

        # Location distribution
        loc_rows = (
            db.session.query(
                Location.id,
                Location.name,
                func.count(Server.id).label("total"),
                func.sum(db.case((Server.status == "active",         1), else_=0)).label("active"),
                func.sum(db.case((Server.status == "inactive",       1), else_=0)).label("inactive"),
                func.sum(db.case((Server.status == "maintenance",    1), else_=0)).label("maintenance"),
                func.sum(db.case((Server.status == "decommissioned", 1), else_=0)).label("decommissioned"),
            )
            .outerjoin(Server, Server.location_id == Location.id)
            .filter(Location.is_active == True)  # noqa: E712
            .group_by(Location.id, Location.name)
            .order_by(func.count(Server.id).desc())
            .all()
        )
        result.loc_summary = [
            LocationSummaryRow(
                location_id    = r.id,
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

        # Environment distribution
        env_rows = (
            db.session.query(
                Environment.id,
                Environment.name,
                Environment.label,
                Environment.color,
                func.count(Server.id).label("total"),
                func.sum(db.case((Server.status == "active",         1), else_=0)).label("active"),
                func.sum(db.case((Server.status == "inactive",       1), else_=0)).label("inactive"),
                func.sum(db.case((Server.status == "maintenance",    1), else_=0)).label("maintenance"),
                func.sum(db.case((Server.status == "decommissioned", 1), else_=0)).label("decommissioned"),
            )
            .outerjoin(Server, Server.environment_id == Environment.id)
            .filter(Environment.is_active == True)  # noqa: E712
            .group_by(Environment.id, Environment.name, Environment.label, Environment.color)
            .order_by(func.count(Server.id).desc())
            .all()
        )
        result.env_summary = [
            EnvSummaryRow(
                env_id         = r.id,
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

        # Server detail (paginated, filtered)
        q = _infra_server_query(filters)
        result.servers, result.total, result.total_pages = _paginate(q, page, per_page)
        ref = _ref_data()
        result.locations    = ref["locations"]
        result.environments = ref["environments"]
    except Exception:
        logger.exception("Failed to query infrastructure summary")
    return result


def get_infrastructure_summary_export(filters: InfrastructureFilters) -> list:
    try:
        return _infra_server_query(filters).all()
    except Exception:
        logger.exception("Failed to export infrastructure summary")
        return []


# ═══════════════════════════════════════════════════════════════════════════ #
# 3. Patch Compliance Report
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
    search:       str        = ""
    location_id:  int | None = None
    env_id:       int | None = None
    patch_status: str        = ""
    sort:         str        = PATCH_DEFAULT_SORT
    order:        str        = PATCH_DEFAULT_ORDER


@dataclass
class PatchCompliancePage:
    servers:          list                   = field(default_factory=list)
    total:            int                    = 0
    page:             int                    = 1
    per_page:         int                    = 25
    total_pages:      int                    = 1
    filters:          PatchComplianceFilters = field(default_factory=PatchComplianceFilters)
    locations:        list                   = field(default_factory=list)
    environments:     list                   = field(default_factory=list)
    patch_statuses:   list                   = field(default_factory=list)
    count_up_to_date: int                    = 0
    count_pending:    int                    = 0
    count_failed:     int                    = 0
    count_unknown:    int                    = 0


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
# 4. Synchronization Report
# ═══════════════════════════════════════════════════════════════════════════ #

SYNC_SORTABLE: dict[str, object] = {
    "hostname":          Server.hostname,
    "environment":       Environment.name,
    "location":          Location.name,
    "operating_system":  Server.operating_system,
    "patch_status":      Patching.patch_status,
    "last_ansible_sync": Server.last_ansible_sync,
    "owner":             Owner.name,
}

SYNC_DEFAULT_SORT  = "last_ansible_sync"
SYNC_DEFAULT_ORDER = "desc"


@dataclass
class SyncReportFilters:
    search:      str        = ""
    location_id: int | None = None
    env_id:      int | None = None
    sync_status: str        = ""   # "" | "synced" | "never"
    sort:        str        = SYNC_DEFAULT_SORT
    order:       str        = SYNC_DEFAULT_ORDER


@dataclass
class SyncReportPage:
    servers:        list            = field(default_factory=list)
    total:          int             = 0
    page:           int             = 1
    per_page:       int             = 25
    total_pages:    int             = 1
    filters:        SyncReportFilters = field(default_factory=SyncReportFilters)
    locations:      list            = field(default_factory=list)
    environments:   list            = field(default_factory=list)
    total_synced:   int             = 0
    total_never:    int             = 0
    last_sync_time: object          = None   # datetime | None


def _sync_report_query(filters: SyncReportFilters):
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

    if filters.sync_status == "synced":
        q = q.filter(Server.last_ansible_sync != None)  # noqa: E711
    elif filters.sync_status == "never":
        q = q.filter(Server.last_ansible_sync == None)  # noqa: E711

    sort_col = SYNC_SORTABLE.get(filters.sort, Server.last_ansible_sync)
    order_fn = asc if filters.order == "asc" else desc
    q = q.order_by(order_fn(sort_col).nulls_last(), Server.hostname.asc())
    return q


def get_sync_report(
    filters: SyncReportFilters, page: int, per_page: int
) -> SyncReportPage:
    result = SyncReportPage(filters=filters, page=page, per_page=per_page)
    try:
        q = _sync_report_query(filters)
        result.servers, result.total, result.total_pages = _paginate(q, page, per_page)
        ref = _ref_data()
        result.locations    = ref["locations"]
        result.environments = ref["environments"]
        result.total_synced = (
            db.session.query(func.count(Server.id))
            .filter(Server.last_ansible_sync != None)  # noqa: E711
            .scalar()
        ) or 0
        result.total_never = (
            db.session.query(func.count(Server.id))
            .filter(Server.last_ansible_sync == None)  # noqa: E711
            .scalar()
        ) or 0
        result.last_sync_time = db.session.query(func.max(Server.last_ansible_sync)).scalar()
    except Exception:
        logger.exception("Failed to query sync report")
    return result


def get_sync_report_export(filters: SyncReportFilters) -> list:
    try:
        return _sync_report_query(filters).all()
    except Exception:
        logger.exception("Failed to export sync report")
        return []

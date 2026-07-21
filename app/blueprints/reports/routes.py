"""Reports blueprint routes."""
from __future__ import annotations

import csv
import io
import logging

from flask import Response, current_app, render_template, request

from . import reports_bp
from .queries import (
    ByEnvironmentFilters,
    ByLocationFilters,
    InventoryReportFilters,
    KernelComplianceFilters,
    OwnerSummaryFilters,
    PatchComplianceFilters,
    RecentlySyncedFilters,
    get_by_environment_export,
    get_by_environment_report,
    get_by_location_export,
    get_by_location_report,
    get_inventory_report,
    get_inventory_report_export,
    get_kernel_compliance_export,
    get_kernel_compliance_report,
    get_owner_summary_export,
    get_owner_summary_report,
    get_patch_compliance_export,
    get_patch_compliance_report,
    get_recently_synced_export,
    get_recently_synced_report,
    INVENTORY_DEFAULT_SORT,
    INVENTORY_DEFAULT_ORDER,
    BY_LOCATION_DEFAULT_SORT,
    BY_LOCATION_DEFAULT_ORDER,
    BY_ENV_DEFAULT_SORT,
    BY_ENV_DEFAULT_ORDER,
    PATCH_DEFAULT_SORT,
    PATCH_DEFAULT_ORDER,
    KERNEL_DEFAULT_SORT,
    KERNEL_DEFAULT_ORDER,
    OWNER_DEFAULT_SORT,
    OWNER_DEFAULT_ORDER,
    RECENT_DEFAULT_SORT,
    RECENT_DEFAULT_ORDER,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────── #
# Export helpers
# ─────────────────────────────────────────────────────────────────────────── #

def _csv_response(rows: list[list], headers: list[str], filename: str) -> Response:
    """Return a streaming CSV download."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    buf.seek(0)
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _xlsx_response(rows: list[list], headers: list[str], filename: str) -> Response:
    """Return an Excel (.xlsx) download."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        logger.error("openpyxl not installed — falling back to CSV")
        return _csv_response(rows, headers, filename.replace(".xlsx", ".csv"))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = filename.replace(".xlsx", "")[:31]

    # Header row style
    header_font    = Font(bold=True, color="FFFFFF")
    header_fill    = PatternFill("solid", fgColor="1F4E79")
    header_align   = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font      = header_font
        cell.fill      = header_fill
        cell.alignment = header_align

    # Data rows
    for row_idx, row in enumerate(rows, start=2):
        for col_idx, value in enumerate(row, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    # Auto-fit column widths (approximate)
    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 45)

    # Freeze header row
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        buf.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _fmt(value) -> str:
    """Safe string formatter for export values."""
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


# ─────────────────────────────────────────────────────────────────────────── #
# Reports landing page
# ─────────────────────────────────────────────────────────────────────────── #

@reports_bp.route("/reports")
def index():
    """Reports landing page — overview of all available reports."""
    return render_template(
        "reports/index.html",
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


# ─────────────────────────────────────────────────────────────────────────── #
# 1. Server Inventory Report
# ─────────────────────────────────────────────────────────────────────────── #

@reports_bp.route("/reports/inventory")
def inventory():
    per_page = current_app.config.get("ITEMS_PER_PAGE", 25)

    search      = request.args.get("q",           "").strip()
    location_id = request.args.get("location_id", type=int)
    env_id      = request.args.get("env_id",      type=int)
    owner_id    = request.args.get("owner_id",    type=int)
    status      = request.args.get("status",      "").strip()
    sort        = request.args.get("sort",  INVENTORY_DEFAULT_SORT)
    order       = request.args.get("order", INVENTORY_DEFAULT_ORDER)
    page        = request.args.get("page",  1, type=int)
    export      = request.args.get("export", "").strip().lower()

    if order not in ("asc", "desc"):
        order = INVENTORY_DEFAULT_ORDER
    if page < 1:
        page = 1

    filters = InventoryReportFilters(
        search=search, location_id=location_id, env_id=env_id,
        owner_id=owner_id, status=status, sort=sort, order=order,
    )

    if export in ("csv", "xlsx"):
        servers = get_inventory_report_export(filters)
        headers = [
            "Hostname", "FQDN", "IP Address", "Environment", "Location", "Owner",
            "OS", "OS Version", "Kernel", "CPU Count", "RAM (GB)", "Status",
            "Last Ansible Sync", "Created At",
        ]
        rows = [
            [
                s.hostname, _fmt(s.fqdn), s.ip_address,
                s.environment.name if s.environment else "",
                s.location.name    if s.location    else "",
                s.owner.name       if s.owner       else "",
                _fmt(s.operating_system), _fmt(s.os_version), _fmt(s.kernel_version),
                _fmt(s.cpu_count), _fmt(s.ram_gb), s.status,
                _fmt(s.last_ansible_sync), _fmt(s.created_at),
            ]
            for s in servers
        ]
        fn = "server_inventory_report"
        if export == "csv":
            return _csv_response(rows, headers, f"{fn}.csv")
        return _xlsx_response(rows, headers, f"{fn}.xlsx")

    report = get_inventory_report(filters, page=page, per_page=per_page)
    return render_template(
        "reports/inventory.html",
        report=report,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


# ─────────────────────────────────────────────────────────────────────────── #
# 2. Servers by Location
# ─────────────────────────────────────────────────────────────────────────── #

@reports_bp.route("/reports/by-location")
def by_location():
    per_page = current_app.config.get("ITEMS_PER_PAGE", 25)

    search      = request.args.get("q",           "").strip()
    location_id = request.args.get("location_id", type=int)
    env_id      = request.args.get("env_id",      type=int)
    status      = request.args.get("status",      "").strip()
    sort        = request.args.get("sort",  BY_LOCATION_DEFAULT_SORT)
    order       = request.args.get("order", BY_LOCATION_DEFAULT_ORDER)
    page        = request.args.get("page",  1, type=int)
    export      = request.args.get("export", "").strip().lower()

    if order not in ("asc", "desc"):
        order = BY_LOCATION_DEFAULT_ORDER
    if page < 1:
        page = 1

    filters = ByLocationFilters(
        search=search, location_id=location_id, env_id=env_id,
        status=status, sort=sort, order=order,
    )

    if export in ("csv", "xlsx"):
        servers = get_by_location_export(filters)
        headers = [
            "Hostname", "IP Address", "Location", "Environment", "OS",
            "Kernel", "Owner", "Status", "Last Ansible Sync",
        ]
        rows = [
            [
                s.hostname, s.ip_address,
                s.location.name    if s.location    else "",
                s.environment.name if s.environment else "",
                _fmt(s.operating_system), _fmt(s.kernel_version),
                s.owner.name       if s.owner       else "",
                s.status, _fmt(s.last_ansible_sync),
            ]
            for s in servers
        ]
        fn = "servers_by_location"
        if export == "csv":
            return _csv_response(rows, headers, f"{fn}.csv")
        return _xlsx_response(rows, headers, f"{fn}.xlsx")

    report = get_by_location_report(filters, page=page, per_page=per_page)
    return render_template(
        "reports/by_location.html",
        report=report,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


# ─────────────────────────────────────────────────────────────────────────── #
# 3. Servers by Environment
# ─────────────────────────────────────────────────────────────────────────── #

@reports_bp.route("/reports/by-environment")
def by_environment():
    per_page = current_app.config.get("ITEMS_PER_PAGE", 25)

    search      = request.args.get("q",           "").strip()
    env_id      = request.args.get("env_id",      type=int)
    location_id = request.args.get("location_id", type=int)
    status      = request.args.get("status",      "").strip()
    sort        = request.args.get("sort",  BY_ENV_DEFAULT_SORT)
    order       = request.args.get("order", BY_ENV_DEFAULT_ORDER)
    page        = request.args.get("page",  1, type=int)
    export      = request.args.get("export", "").strip().lower()

    if order not in ("asc", "desc"):
        order = BY_ENV_DEFAULT_ORDER
    if page < 1:
        page = 1

    filters = ByEnvironmentFilters(
        search=search, env_id=env_id, location_id=location_id,
        status=status, sort=sort, order=order,
    )

    if export in ("csv", "xlsx"):
        servers = get_by_environment_export(filters)
        headers = [
            "Hostname", "IP Address", "Environment", "Location", "OS",
            "Kernel", "Owner", "Status", "Last Ansible Sync",
        ]
        rows = [
            [
                s.hostname, s.ip_address,
                s.environment.name if s.environment else "",
                s.location.name    if s.location    else "",
                _fmt(s.operating_system), _fmt(s.kernel_version),
                s.owner.name       if s.owner       else "",
                s.status, _fmt(s.last_ansible_sync),
            ]
            for s in servers
        ]
        fn = "servers_by_environment"
        if export == "csv":
            return _csv_response(rows, headers, f"{fn}.csv")
        return _xlsx_response(rows, headers, f"{fn}.xlsx")

    report = get_by_environment_report(filters, page=page, per_page=per_page)
    return render_template(
        "reports/by_environment.html",
        report=report,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


# ─────────────────────────────────────────────────────────────────────────── #
# 4. Patch Compliance Report
# ─────────────────────────────────────────────────────────────────────────── #

@reports_bp.route("/reports/patch-compliance")
def patch_compliance():
    per_page = current_app.config.get("ITEMS_PER_PAGE", 25)

    search       = request.args.get("q",            "").strip()
    location_id  = request.args.get("location_id",  type=int)
    env_id       = request.args.get("env_id",       type=int)
    patch_status = request.args.get("patch_status", "").strip()
    sort         = request.args.get("sort",  PATCH_DEFAULT_SORT)
    order        = request.args.get("order", PATCH_DEFAULT_ORDER)
    page         = request.args.get("page",  1, type=int)
    export       = request.args.get("export", "").strip().lower()

    if order not in ("asc", "desc"):
        order = PATCH_DEFAULT_ORDER
    if page < 1:
        page = 1

    filters = PatchComplianceFilters(
        search=search, location_id=location_id, env_id=env_id,
        patch_status=patch_status, sort=sort, order=order,
    )

    if export in ("csv", "xlsx"):
        servers = get_patch_compliance_export(filters)
        headers = [
            "Hostname", "Environment", "Location", "OS", "Current Kernel",
            "Previous Kernel", "Patch Status", "Pending Updates",
            "Last Patched", "Last Reboot", "Last Ansible Sync", "Owner",
        ]
        rows = []
        for s in servers:
            p = s.patching
            rows.append([
                s.hostname,
                s.environment.name if s.environment else "",
                s.location.name    if s.location    else "",
                _fmt(s.operating_system),
                _fmt(p.current_kernel  if p else None),
                _fmt(p.previous_kernel if p else None),
                p.patch_status         if p else "unknown",
                _fmt(p.pending_updates if p else None),
                _fmt(p.last_patch_date  if p else None),
                _fmt(p.last_reboot_date if p else None),
                _fmt(s.last_ansible_sync),
                s.owner.name if s.owner else "",
            ])
        fn = "patch_compliance_report"
        if export == "csv":
            return _csv_response(rows, headers, f"{fn}.csv")
        return _xlsx_response(rows, headers, f"{fn}.xlsx")

    report = get_patch_compliance_report(filters, page=page, per_page=per_page)
    return render_template(
        "reports/patch_compliance.html",
        report=report,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


# ─────────────────────────────────────────────────────────────────────────── #
# 5. Kernel Compliance Report
# ─────────────────────────────────────────────────────────────────────────── #

@reports_bp.route("/reports/kernel-compliance")
def kernel_compliance():
    per_page = current_app.config.get("ITEMS_PER_PAGE", 25)

    search      = request.args.get("q",           "").strip()
    location_id = request.args.get("location_id", type=int)
    env_id      = request.args.get("env_id",      type=int)
    kernel      = request.args.get("kernel",      "").strip()
    sort        = request.args.get("sort",  KERNEL_DEFAULT_SORT)
    order       = request.args.get("order", KERNEL_DEFAULT_ORDER)
    page        = request.args.get("page",  1, type=int)
    export      = request.args.get("export", "").strip().lower()

    if order not in ("asc", "desc"):
        order = KERNEL_DEFAULT_ORDER
    if page < 1:
        page = 1

    filters = KernelComplianceFilters(
        search=search, location_id=location_id, env_id=env_id,
        kernel=kernel, sort=sort, order=order,
    )

    if export in ("csv", "xlsx"):
        servers = get_kernel_compliance_export(filters)
        headers = [
            "Hostname", "Environment", "Location", "OS",
            "Current Kernel", "Previous Kernel", "Last Reboot",
            "Last Ansible Sync", "Owner",
        ]
        rows = []
        for s in servers:
            p = s.patching
            rows.append([
                s.hostname,
                s.environment.name if s.environment else "",
                s.location.name    if s.location    else "",
                _fmt(s.operating_system),
                _fmt(p.current_kernel  if p else s.kernel_version),
                _fmt(p.previous_kernel if p else None),
                _fmt(p.last_reboot_date if p else None),
                _fmt(s.last_ansible_sync),
                s.owner.name if s.owner else "",
            ])
        fn = "kernel_compliance_report"
        if export == "csv":
            return _csv_response(rows, headers, f"{fn}.csv")
        return _xlsx_response(rows, headers, f"{fn}.xlsx")

    report = get_kernel_compliance_report(filters, page=page, per_page=per_page)
    return render_template(
        "reports/kernel_compliance.html",
        report=report,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


# ─────────────────────────────────────────────────────────────────────────── #
# 6. Owner Summary Report
# ─────────────────────────────────────────────────────────────────────────── #

@reports_bp.route("/reports/owner-summary")
def owner_summary():
    per_page = current_app.config.get("ITEMS_PER_PAGE", 25)

    search  = request.args.get("q",     "").strip()
    sort    = request.args.get("sort",  OWNER_DEFAULT_SORT)
    order   = request.args.get("order", OWNER_DEFAULT_ORDER)
    page    = request.args.get("page",  1, type=int)
    export  = request.args.get("export", "").strip().lower()

    if order not in ("asc", "desc"):
        order = OWNER_DEFAULT_ORDER
    if page < 1:
        page = 1

    filters = OwnerSummaryFilters(search=search, sort=sort, order=order)

    if export in ("csv", "xlsx"):
        rows_data = get_owner_summary_export(filters)
        headers = [
            "Owner", "Email", "Total Servers",
            "Active", "Inactive", "Maintenance", "Decommissioned",
        ]
        rows = [
            [
                r.owner_name, _fmt(r.owner_email),
                r.total, r.active, r.inactive, r.maintenance, r.decommissioned,
            ]
            for r in rows_data
        ]
        fn = "owner_summary_report"
        if export == "csv":
            return _csv_response(rows, headers, f"{fn}.csv")
        return _xlsx_response(rows, headers, f"{fn}.xlsx")

    report = get_owner_summary_report(filters, page=page, per_page=per_page)
    return render_template(
        "reports/owner_summary.html",
        report=report,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


# ─────────────────────────────────────────────────────────────────────────── #
# 7. Recently Synchronized Servers
# ─────────────────────────────────────────────────────────────────────────── #

@reports_bp.route("/reports/recently-synced")
def recently_synced():
    per_page = current_app.config.get("ITEMS_PER_PAGE", 25)

    search      = request.args.get("q",           "").strip()
    location_id = request.args.get("location_id", type=int)
    env_id      = request.args.get("env_id",      type=int)
    sort        = request.args.get("sort",  RECENT_DEFAULT_SORT)
    order       = request.args.get("order", RECENT_DEFAULT_ORDER)
    page        = request.args.get("page",  1, type=int)
    export      = request.args.get("export", "").strip().lower()

    if order not in ("asc", "desc"):
        order = RECENT_DEFAULT_ORDER
    if page < 1:
        page = 1

    filters = RecentlySyncedFilters(
        search=search, location_id=location_id, env_id=env_id,
        sort=sort, order=order,
    )

    if export in ("csv", "xlsx"):
        servers = get_recently_synced_export(filters)
        headers = [
            "Hostname", "IP Address", "Environment", "Location", "OS",
            "Current Kernel", "Patch Status", "Last Ansible Sync", "Owner",
        ]
        rows = []
        for s in servers:
            p = s.patching
            rows.append([
                s.hostname, s.ip_address,
                s.environment.name if s.environment else "",
                s.location.name    if s.location    else "",
                _fmt(s.operating_system),
                _fmt(p.current_kernel if p else s.kernel_version),
                p.patch_status if p else "unknown",
                _fmt(s.last_ansible_sync),
                s.owner.name if s.owner else "",
            ])
        fn = "recently_synced_servers"
        if export == "csv":
            return _csv_response(rows, headers, f"{fn}.csv")
        return _xlsx_response(rows, headers, f"{fn}.xlsx")

    report = get_recently_synced_report(filters, page=page, per_page=per_page)
    return render_template(
        "reports/recently_synced.html",
        report=report,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )

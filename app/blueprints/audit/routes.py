"""Audit Logs blueprint routes."""
from __future__ import annotations

import logging

from flask import Response, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required

from . import audit_bp
from .queries import (
    RETENTION_OPTIONS,
    AuditFilters,
    build_csv,
    build_excel,
    get_all_for_export,
    get_audit_entry,
    get_audit_page,
    get_distinct_actors,
    get_distinct_modules,
    get_total_count,
    purge_old_entries,
)
from ...audit import commit_audit

logger = logging.getLogger(__name__)


# ── Index ─────────────────────────────────────────────────────────────────── #

@audit_bp.route("/audit")
@login_required
def index():
    """Audit log browser — searchable, filterable, sortable, paginated."""
    filters = AuditFilters.from_request(request.args)
    pagination = get_audit_page(filters)
    actors  = get_distinct_actors()
    modules = get_distinct_modules()
    total   = get_total_count()

    return render_template(
        "audit/index.html",
        filters=filters,
        pagination=pagination,
        entries=pagination.items if pagination else [],
        actors=actors,
        modules=modules,
        total=total,
        retention_options=RETENTION_OPTIONS,
    )


# ── Detail (AJAX JSON for modal) ──────────────────────────────────────────── #

@audit_bp.route("/audit/<int:entry_id>/detail")
@login_required
def detail(entry_id: int):
    """Return a single audit entry as JSON for the detail modal."""
    entry = get_audit_entry(entry_id)
    if not entry:
        return jsonify({"error": "Entry not found"}), 404

    return jsonify({
        "id":            entry.id,
        "timestamp":     entry.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if entry.created_at else "—",
        "actor":         entry.actor,
        "module":        entry.module or "—",
        "action":        entry.action,
        "target":        entry.target or "—",
        "details":       entry.details or "—",
        "ip_address":    entry.ip_address or "—",
        "auth_source":   entry.auth_source or "—",
        "result":        entry.result,
        "user_agent":    entry.user_agent or "—",
        "session_id":    entry.session_id or "—",
        "before_values": entry.before_values or "—",
        "after_values":  entry.after_values or "—",
    })


# ── Exports ───────────────────────────────────────────────────────────────── #

@audit_bp.route("/audit/export/csv")
@login_required
def export_csv():
    """Export the current filtered audit log as CSV."""
    filters = AuditFilters.from_request(request.args)
    rows = get_all_for_export(filters)
    commit_audit("audit.export.csv", target=f"{len(rows)} rows", result="success")
    csv_data = build_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )


@audit_bp.route("/audit/export/excel")
@login_required
def export_excel():
    """Export the current filtered audit log as Excel (.xlsx)."""
    filters = AuditFilters.from_request(request.args)
    rows = get_all_for_export(filters)
    commit_audit("audit.export.excel", target=f"{len(rows)} rows", result="success")
    excel_data = build_excel(rows)
    return Response(
        excel_data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=audit_log.xlsx"},
    )


# ── Retention cleanup ─────────────────────────────────────────────────────── #

@audit_bp.route("/audit/cleanup", methods=["POST"])
@login_required
def cleanup():
    """Delete audit log entries older than the requested retention period."""
    try:
        days = int(request.form.get("days", 90))
    except (ValueError, TypeError):
        days = 90

    valid_days = [d for d, _ in RETENTION_OPTIONS]
    if days not in valid_days:
        flash("Invalid retention period.", "danger")
        return redirect(url_for("audit.index"))

    try:
        count = purge_old_entries(days)
        commit_audit(
            "audit.cleanup",
            target=f"entries older than {days} days",
            details=f"Deleted {count} entries",
            result="success",
        )
        flash(f"Deleted {count} audit log {'entry' if count == 1 else 'entries'} older than {days} days.", "success")
    except Exception as exc:
        flash(f"Cleanup failed: {exc}", "danger")

    return redirect(url_for("audit.index"))

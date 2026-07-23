"""
Main blueprint routes.

The application root redirects to the dashboard once it exists.
The /health endpoint is kept here as it belongs to no specific module.
It returns structured JSON consumed by health.sh, the lop CLI, and
eventually the web UI.
"""
import logging
import os
import platform
import time

from flask import current_app, redirect, send_from_directory, url_for
from sqlalchemy import text

from . import main_bp
from ...extensions import db

logger = logging.getLogger(__name__)

# Track server start time for uptime calculation
_START_TIME = time.time()


@main_bp.route("/download/gap-analysis", methods=["GET"])
def download_gap_analysis():
    """Temporary route to download the GAP analysis Word document."""
    static_dir = os.path.join(os.path.dirname(current_app.root_path), "app", "static")
    return send_from_directory(
        static_dir,
        "LOP_Ansible_GAP_Analysis.docx",
        as_attachment=True,
        download_name="LOP_Ansible_GAP_Analysis.docx",
    )


@main_bp.route("/", methods=["GET"])
def index():
    """Redirect root to the dashboard."""
    return redirect(url_for("dashboard.index"))


@main_bp.route("/health", methods=["GET"])
def health():
    """
    Structured health-check endpoint.

    Returns a JSON object with component-level status suitable for:
      • Docker / load-balancer liveness probes (check HTTP 200 / 503)
      • health.sh CLI checks
      • Future web UI dashboard widget

    No authentication required.
    """
    checks = {}
    overall = "ok"

    # ── Database connectivity ─────────────────────────────────────────────────
    try:
        db.session.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "error", "detail": str(exc)}
        overall = "degraded"

    # ── Schema version ────────────────────────────────────────────────────────
    try:
        result = db.session.execute(
            text("SELECT version_num FROM alembic_version LIMIT 1")
        ).scalar()
        checks["schema_version"] = {"status": "ok", "version": result or "unknown"}
    except Exception:
        checks["schema_version"] = {"status": "unknown"}

    # ── Python runtime ────────────────────────────────────────────────────────
    checks["python"] = {
        "status": "ok",
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
    }

    # ── Memory (best-effort, non-fatal) ───────────────────────────────────────
    try:
        with open("/proc/meminfo") as f:
            mem_lines = {
                line.split(":")[0].strip(): int(line.split(":")[1].strip().split()[0])
                for line in f
                if ":" in line
            }
        mem_total_mb = mem_lines.get("MemTotal", 0) // 1024
        mem_avail_mb = mem_lines.get("MemAvailable", 0) // 1024
        mem_used_mb = mem_total_mb - mem_avail_mb
        checks["memory"] = {
            "status": "ok",
            "total_mb": mem_total_mb,
            "used_mb": mem_used_mb,
            "available_mb": mem_avail_mb,
        }
    except Exception:
        checks["memory"] = {"status": "unavailable"}

    # ── Disk space (best-effort, non-fatal) ───────────────────────────────────
    try:
        stat = os.statvfs("/opt/lop" if os.path.exists("/opt/lop") else "/")
        if stat.f_blocks == 0:
            # statvfs not meaningful (container / virtual FS — skip)
            checks["disk"] = {"status": "unavailable"}
        else:
            disk_total_gb = round((stat.f_blocks * stat.f_frsize) / (1024 ** 3), 1)
            disk_free_gb  = round((stat.f_bavail * stat.f_frsize) / (1024 ** 3), 1)
            disk_used_pct = round((1 - stat.f_bavail / max(stat.f_blocks, 1)) * 100, 1)
            if disk_total_gb < 0.1:
                # Values round to zero — container or virtual FS; skip degrading overall.
                checks["disk"] = {"status": "unavailable"}
            else:
                disk_status = "ok"
                if disk_free_gb < 1:
                    disk_status = "critical"
                    overall = "degraded"
                elif disk_used_pct > 85:
                    disk_status = "warning"
                checks["disk"] = {
                    "status": disk_status,
                    "total_gb": disk_total_gb,
                    "free_gb": disk_free_gb,
                    "used_pct": disk_used_pct,
                }
    except Exception:
        checks["disk"] = {"status": "unavailable"}

    # ── Uptime ────────────────────────────────────────────────────────────────
    uptime_seconds = int(time.time() - _START_TIME)
    checks["uptime"] = {
        "status": "ok",
        "seconds": uptime_seconds,
        "human": _format_uptime(uptime_seconds),
    }

    # ── Response ──────────────────────────────────────────────────────────────
    http_status = 200 if overall == "ok" else 503
    return {
        "status": overall,
        "version": current_app.config.get("APP_VERSION", "unknown"),
        "checks": checks,
    }, http_status


def _format_uptime(seconds: int) -> str:
    """Return a human-readable uptime string."""
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)

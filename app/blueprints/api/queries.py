"""
API v1 query helpers.

All database reads and writes for the REST API live here.
Routes stay thin; all business logic and DB access is here.

Design rules:
  - Use SQLAlchemy ORM only — no raw SQL.
  - Upsert on hostname (unique key).
  - Resolve location / environment / owner by name (case-insensitive).
  - Always update Server.last_ansible_sync on a successful push.
  - validate_inventory_payload() enforces types for every expected field
    so the route returns deterministic 400s instead of 500s on bad input.
  - _safe_str() is used everywhere a string field is read from the payload
    so upsert_server() never calls .strip() on a non-string value.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ...extensions import db
from ...models.environment import Environment
from ...models.location import Location
from ...models.owner import Owner
from ...models.patching import Patching
from ...models.server import Server

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────── #

VALID_PATCH_STATUSES = ("up-to-date", "pending", "failed", "unknown")
VALID_STATUSES = ("active", "inactive", "maintenance", "decommissioned")

# All optional string fields accepted from the payload.
# Maps field name → max allowed length.
OPTIONAL_STRING_FIELDS: dict[str, int] = {
    "fqdn":              255,
    "operating_system":  100,
    "os_version":        100,
    "kernel_version":    150,
    "cpu_model":         255,
    "location":          100,
    "environment":       100,
    "owner":             150,
    "status":             50,
    "current_kernel":    150,
    # Extended system info
    "architecture":       50,
    "package_manager":    50,
    "python_version":     50,
    "ansible_version":    50,
    "selinux_status":     50,
    "timezone_name":     100,
    # Hostname parsing results
    "parsed_site":        20,
    "parsed_app_code":    20,
    "parsed_os_name":    100,
    "parsed_env_name":    50,
    # Extended patching
    "installed_kernel":  150,
}


# ── Result container ──────────────────────────────────────────────────── #

@dataclass
class UpsertResult:
    action: str = "updated"   # "created" | "updated"
    hostname: str = ""
    error: str = ""
    success: bool = True


# ── Type-safe helpers ──────────────────────────────────────────────────── #

def _safe_str(value: Any, *, max_len: int | None = None) -> str | None:
    """
    Return value.strip() if value is a non-empty string, else None.
    Never raises — non-string/None inputs silently become None.
    Truncation is not performed; callers that need length limits should
    validate before calling this (or pass max_len for a silent truncation
    safety net in upsert, after validation has already rejected overlong values).
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if max_len is not None and len(s) > max_len:
        return s[:max_len]
    return s


def _parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 string or return None for missing/invalid values."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ── Lookup helpers ────────────────────────────────────────────────────── #

def _lookup_environment(name: str | None) -> Environment | None:
    """Look up an active Environment by name (case-insensitive). Non-strings → None."""
    safe = _safe_str(name)
    if not safe:
        return None
    return Environment.query.filter(
        db.func.lower(Environment.name) == safe.lower(),
        Environment.is_active == True,  # noqa: E712
    ).first()


def _lookup_location(name: str | None) -> Location | None:
    """Look up an active Location by name (case-insensitive). Non-strings → None."""
    safe = _safe_str(name)
    if not safe:
        return None
    return Location.query.filter(
        db.func.lower(Location.name) == safe.lower(),
        Location.is_active == True,  # noqa: E712
    ).first()


def _lookup_owner(name: str | None) -> Owner | None:
    """Look up an active Owner by name (case-insensitive). Non-strings → None."""
    safe = _safe_str(name)
    if not safe:
        return None
    return Owner.query.filter(
        db.func.lower(Owner.name) == safe.lower(),
        Owner.is_active == True,  # noqa: E712
    ).first()


# ── Validate payload ──────────────────────────────────────────────────── #

def validate_inventory_payload(data: dict) -> str | None:
    """
    Return an error string if the payload is invalid, otherwise None.

    Validates:
      - Required fields (hostname, ip_address): present, string type, non-empty,
        within max length.
      - All optional string fields: if present, must be a string type and within
        max length.
      - Numeric fields (cpu_count, ram_gb, pending_updates): if present, must be
        numeric (int/float).
      - patch_status: if present, must be a string and one of VALID_PATCH_STATUSES.
      - status: if present, must be a string and one of VALID_STATUSES.

    All checks run before any DB access, guaranteeing clean 400 responses
    rather than 500s when Ansible sends unexpected types.
    """
    # ── Required string fields ─────────────────────────────────────────
    hostname_raw = data.get("hostname")
    ip_raw = data.get("ip_address")

    if not isinstance(hostname_raw, str):
        return "Missing required field: hostname" if hostname_raw is None else "hostname must be a string"
    if not isinstance(ip_raw, str):
        return "Missing required field: ip_address" if ip_raw is None else "ip_address must be a string"

    hostname = hostname_raw.strip()
    ip_address = ip_raw.strip()

    if not hostname:
        return "Missing required field: hostname"
    if len(hostname) > 255:
        return "hostname exceeds maximum length of 255 characters"
    if not ip_address:
        return "Missing required field: ip_address"
    if len(ip_address) > 45:
        return "ip_address exceeds maximum length of 45 characters"

    # ── Optional string fields ─────────────────────────────────────────
    for field, max_len in OPTIONAL_STRING_FIELDS.items():
        value = data.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            return f"{field} must be a string"
        if len(value.strip()) > max_len:
            return f"{field} exceeds maximum length of {max_len} characters"

    # ── patch_status enumeration ───────────────────────────────────────
    patch_status = data.get("patch_status")
    if patch_status is not None:
        if not isinstance(patch_status, str):
            return "patch_status must be a string"
        if patch_status not in VALID_PATCH_STATUSES:
            return (
                f"Invalid patch_status '{patch_status}'. "
                f"Allowed values: {', '.join(VALID_PATCH_STATUSES)}"
            )

    # ── status enumeration ─────────────────────────────────────────────
    status = data.get("status")
    if status is not None:
        if not isinstance(status, str):
            return "status must be a string"
        if status.strip() not in VALID_STATUSES:
            return (
                f"Invalid status '{status}'. "
                f"Allowed values: {', '.join(VALID_STATUSES)}"
            )

    # ── Numeric fields ─────────────────────────────────────────────────
    for num_field in (
        "cpu_count", "pending_updates", "security_updates",
        "uptime_seconds",
        "disk_total_gb", "disk_used_gb", "disk_used_pct",
        "swap_total_gb", "swap_used_gb",
    ):
        val = data.get(num_field)
        if val is not None and not isinstance(val, (int, float)):
            return f"{num_field} must be a number"

    for float_field in ("ram_gb",):
        val = data.get(float_field)
        if val is not None and not isinstance(val, (int, float)):
            return f"{float_field} must be a number"

    # ── Boolean fields ─────────────────────────────────────────────────
    for bool_field in ("reboot_required", "kernel_update_available"):
        val = data.get(bool_field)
        if val is not None and not isinstance(val, bool):
            return f"{bool_field} must be a boolean"

    return None


# ── Upsert ────────────────────────────────────────────────────────────── #

def upsert_server(data: dict) -> UpsertResult:
    """
    Create or update a server record from an Ansible push payload.

    Assumes validate_inventory_payload() has already been called and
    returned None.  Uses _safe_str() for every optional string field so
    non-string values (which validation already rejected) produce None
    rather than raising AttributeError inside the try/except.

    Uses hostname as the unique key.  Environment, location, and owner
    are resolved by name (case-insensitive).  Any name that does not
    match an active record is silently ignored (FK stays NULL).
    """
    hostname = data["hostname"].strip()
    result = UpsertResult(hostname=hostname)

    try:
        now = datetime.now(timezone.utc)

        # ── Resolve related records ────────────────────────────────────
        environment = _lookup_environment(data.get("environment"))
        location = _lookup_location(data.get("location"))
        owner = _lookup_owner(data.get("owner"))

        # ── Upsert server ──────────────────────────────────────────────
        server = Server.query.filter_by(hostname=hostname).first()

        if server is None:
            result.action = "created"
            server = Server(hostname=hostname)
            db.session.add(server)
        else:
            result.action = "updated"

        # Core fields — _safe_str() guards against residual non-string input
        server.ip_address = data["ip_address"].strip()   # required; already validated
        server.fqdn = _safe_str(data.get("fqdn"), max_len=255)

        # System info
        server.operating_system = _safe_str(data.get("operating_system"), max_len=100)
        server.os_version = _safe_str(data.get("os_version"), max_len=100)
        server.kernel_version = _safe_str(data.get("kernel_version"), max_len=150)
        server.architecture = _safe_str(data.get("architecture"), max_len=50)
        server.cpu_count = _parse_int(data.get("cpu_count"))
        server.cpu_model = _safe_str(data.get("cpu_model"), max_len=255)
        server.ram_gb = _parse_float(data.get("ram_gb"))

        # Disk & swap
        server.disk_total_gb = _parse_float(data.get("disk_total_gb"))
        server.disk_used_gb = _parse_float(data.get("disk_used_gb"))
        server.disk_used_pct = _parse_float(data.get("disk_used_pct"))
        server.swap_total_gb = _parse_float(data.get("swap_total_gb"))
        server.swap_used_gb = _parse_float(data.get("swap_used_gb"))

        # Uptime & boot
        server.uptime_seconds = _parse_int(data.get("uptime_seconds"))
        server.last_boot = _parse_datetime(data.get("last_boot"))

        # System metadata
        server.package_manager = _safe_str(data.get("package_manager"), max_len=50)
        server.python_version = _safe_str(data.get("python_version"), max_len=50)
        server.ansible_version = _safe_str(data.get("ansible_version"), max_len=50)
        server.selinux_status = _safe_str(data.get("selinux_status"), max_len=50)
        server.timezone_name = _safe_str(data.get("timezone_name"), max_len=100)

        # Hostname parsing metadata (stored as-is from Ansible)
        server.parsed_site = _safe_str(data.get("parsed_site"), max_len=20)
        server.parsed_app_code = _safe_str(data.get("parsed_app_code"), max_len=20)
        server.parsed_os_name = _safe_str(data.get("parsed_os_name"), max_len=100)
        server.parsed_env_name = _safe_str(data.get("parsed_env_name"), max_len=50)

        # Relationships
        if environment is not None:
            server.environment_id = environment.id
        if location is not None:
            server.location_id = location.id
        if owner is not None:
            server.owner_id = owner.id

        # Sync timestamp
        server.last_ansible_sync = _parse_datetime(data.get("last_inventory_sync")) or now

        # Status: only update if an explicit, valid value is provided in the payload.
        # On updates this preserves manual lifecycle state (inactive, maintenance,
        # decommissioned) so an Ansible sync never silently resets it to "active".
        explicit_status = _safe_str(data.get("status"))
        if explicit_status and explicit_status in VALID_STATUSES:
            server.status = explicit_status
        elif result.action == "created":
            # New server: default to active when no status was supplied
            server.status = "active"
        # else: existing server, no valid status in payload → preserve current value

        server.updated_at = now

        db.session.flush()  # get server.id before patching upsert

        # ── Upsert patching record ─────────────────────────────────────
        patching = Patching.query.filter_by(server_id=server.id).first()
        if patching is None:
            patching = Patching(server_id=server.id)
            db.session.add(patching)

        patch_status = _safe_str(data.get("patch_status"))
        if patch_status and patch_status in VALID_PATCH_STATUSES:
            patching.patch_status = patch_status
        elif patching.patch_status is None:
            patching.patch_status = "unknown"

        # Use kernel_version as the canonical source; fall back to current_kernel
        patching.current_kernel = (
            _safe_str(data.get("kernel_version"), max_len=150)
            or _safe_str(data.get("current_kernel"), max_len=150)
        )
        patching.last_patch_date = _parse_datetime(data.get("last_patch_date"))
        patching.last_reboot_date = _parse_datetime(data.get("last_reboot"))
        patching.pending_updates = _parse_int(data.get("pending_updates")) or 0
        patching.security_updates = _parse_int(data.get("security_updates")) or 0
        patching.installed_kernel = _safe_str(data.get("installed_kernel"), max_len=150)

        # Boolean fields: only update when explicitly provided in payload
        if "reboot_required" in data:
            rr = data["reboot_required"]
            patching.reboot_required = bool(rr) if rr is not None else None

        if "kernel_update_available" in data:
            ku = data["kernel_update_available"]
            patching.kernel_update_available = bool(ku) if ku is not None else None

        patching.updated_at = now

        db.session.commit()
        logger.info(
            "Inventory upsert — action=%s hostname=%s ip=%s",
            result.action, hostname, server.ip_address,
        )

    except Exception:
        db.session.rollback()
        logger.exception("Inventory upsert failed for hostname=%s", hostname)
        result.success = False
        result.error = "Database error — inventory update failed"

    return result

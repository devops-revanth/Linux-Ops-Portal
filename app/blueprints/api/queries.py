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
from ...models.package import Package, ServerPackage
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
    for num_field in ("cpu_count", "pending_updates"):
        val = data.get(num_field)
        if val is not None and not isinstance(val, (int, float)):
            return f"{num_field} must be a number"

    ram = data.get("ram_gb")
    if ram is not None and not isinstance(ram, (int, float)):
        return "ram_gb must be a number"

    # ── reboot_required: must be bool (or absent/null) ─────────────────────
    rr = data.get("reboot_required")
    if rr is not None and not isinstance(rr, bool):
        return "reboot_required must be a boolean"

    return None


# ── Package helpers ───────────────────────────────────────────────────── #

def _upsert_available_updates(
    server_id: int,
    packages: list,
    collected_at: datetime,
) -> None:
    """
    Sync the available-update package list for a server.

    Steps:
      1. Clear all existing update_available=True flags for this server
         (removes stale entries from the previous inventory scan).
      2. For each structured package dict, upsert a Package master record
         and a ServerPackage row with update_available=True.

    Safe to call with an empty list — clearing flags with no new rows
    correctly reflects a fully up-to-date server.

    Expected package dict keys (all optional except 'name'):
      name              — package name (required; row is skipped if absent)
      arch              — CPU architecture string
      available_version — version string of the available update
      repository        — source repository name
      update_type       — security | bugfix | enhancement
    """
    # Step 1: clear stale update flags
    (
        db.session.query(ServerPackage)
        .filter_by(server_id=server_id, update_available=True)
        .update(
            {"update_available": False, "available_version": None},
            synchronize_session="fetch",
        )
    )

    if not packages:
        return

    # Step 2: upsert each available-update package
    for pkg_data in packages:
        if not isinstance(pkg_data, dict):
            continue

        name = _safe_str(pkg_data.get("name"))
        if not name:
            continue

        available_version = _safe_str(pkg_data.get("available_version"), max_len=100)
        repository = _safe_str(pkg_data.get("repository"), max_len=150)
        update_type = _safe_str(pkg_data.get("update_type"), max_len=50)

        # Upsert Package master record
        pkg = Package.query.filter_by(name=name).first()
        if pkg is None:
            pkg = Package(name=name, display_name=name)
            db.session.add(pkg)
            db.session.flush()  # get pkg.id

        # Upsert ServerPackage
        sp = ServerPackage.query.filter_by(
            server_id=server_id, package_id=pkg.id
        ).first()
        if sp is None:
            sp = ServerPackage(server_id=server_id, package_id=pkg.id)
            db.session.add(sp)

        sp.update_available = True
        sp.available_version = available_version
        sp.update_type = update_type
        sp.repository = repository
        sp.collected_at = collected_at


def _record_installed_packages(
    server_id: int,
    packages: list,
    installed_at: datetime,
) -> None:
    """
    Record packages installed or upgraded by a patch run.

    Sets update_available=False (the update has been applied) and stamps
    collected_at with the patch timestamp so they sort to the top of the
    "Recently Installed" tab.

    Expected package dict keys (all optional except 'name'):
      name        — package name (required; row is skipped if absent)
      arch        — CPU architecture string
      version     — installed version after patching
      action      — Install | Upgrade | Upgraded | etc.
      repository  — source repository name
    """
    for pkg_data in packages:
        if not isinstance(pkg_data, dict):
            continue

        name = _safe_str(pkg_data.get("name"))
        if not name:
            continue

        version = _safe_str(pkg_data.get("version"), max_len=100)
        action = _safe_str(pkg_data.get("action"), max_len=50)
        repository = _safe_str(pkg_data.get("repository"), max_len=150)

        # Upsert Package master record
        pkg = Package.query.filter_by(name=name).first()
        if pkg is None:
            pkg = Package(name=name, display_name=name)
            db.session.add(pkg)
            db.session.flush()

        # Upsert ServerPackage — update_available=False (installed)
        sp = ServerPackage.query.filter_by(
            server_id=server_id, package_id=pkg.id
        ).first()
        if sp is None:
            sp = ServerPackage(server_id=server_id, package_id=pkg.id)
            db.session.add(sp)

        sp.version = version
        sp.update_available = False
        sp.available_version = None
        sp.update_type = action      # "Upgraded" / "Installed" etc.
        sp.repository = repository
        sp.collected_at = installed_at   # fresh timestamp → top of recently-installed


# ── Validate patching payload ─────────────────────────────────────────── #

def validate_patching_payload(data: dict) -> str | None:
    """
    Return an error string if the patch-completion payload is invalid.

    Required fields:
      hostname       — string, non-empty
      last_patch_date — ISO-8601 string

    Optional fields:
      installed_packages — list of dicts
      pending_updates    — integer
      reboot_required    — boolean
    """
    hostname = data.get("hostname")
    if not isinstance(hostname, str) or not hostname.strip():
        return "Missing required field: hostname"
    if len(hostname.strip()) > 255:
        return "hostname exceeds maximum length of 255 characters"

    lpd = data.get("last_patch_date")
    if not lpd:
        return "Missing required field: last_patch_date"
    if not isinstance(lpd, str):
        return "last_patch_date must be an ISO-8601 string"

    pkgs = data.get("installed_packages")
    if pkgs is not None and not isinstance(pkgs, list):
        return "installed_packages must be a list"

    pu = data.get("pending_updates")
    if pu is not None and not isinstance(pu, (int, float)):
        return "pending_updates must be a number"

    rr = data.get("reboot_required")
    if rr is not None and not isinstance(rr, bool):
        return "reboot_required must be a boolean"

    return None


# ── Record patch completion ────────────────────────────────────────────── #

def record_patch_completion(data: dict) -> UpsertResult:
    """
    Update a server's patching record after a patch run completes.

    - Sets last_patch_date (required).
    - Updates pending_updates and reboot_required when provided.
    - Clears all update_available flags (updates have been applied).
    - Writes installed_packages as ServerPackage rows with update_available=False.

    Assumes validate_patching_payload() has already been called.
    """
    hostname = data["hostname"].strip()
    result = UpsertResult(hostname=hostname, action="patched")

    try:
        now = datetime.now(timezone.utc)

        server = Server.query.filter_by(hostname=hostname).first()
        if server is None:
            result.success = False
            result.error = f"Server '{hostname}' not found — run inventory sync first"
            return result

        # ── Upsert patching record ─────────────────────────────────────
        patching = Patching.query.filter_by(server_id=server.id).first()
        if patching is None:
            patching = Patching(server_id=server.id)
            db.session.add(patching)

        patch_dt = _parse_datetime(data.get("last_patch_date")) or now
        patching.last_patch_date = patch_dt

        pu = _parse_int(data.get("pending_updates"))
        if pu is not None:
            patching.pending_updates = pu

        if "reboot_required" in data:
            rr = data["reboot_required"]
            patching.reboot_required = bool(rr) if rr is not None else None

        # Reflect updated patch status
        if patching.pending_updates == 0:
            patching.patch_status = "up-to-date"
        else:
            patching.patch_status = "pending"

        patching.updated_at = now

        db.session.flush()

        # ── Clear stale available-update flags ─────────────────────────
        # All flagged updates have been applied; next inventory sync will
        # re-populate any that remain.
        (
            db.session.query(ServerPackage)
            .filter_by(server_id=server.id, update_available=True)
            .update(
                {"update_available": False, "available_version": None},
                synchronize_session="fetch",
            )
        )

        # ── Record installed packages ──────────────────────────────────
        installed = data.get("installed_packages")
        if isinstance(installed, list) and installed:
            _record_installed_packages(server.id, installed, patch_dt)

        db.session.commit()
        logger.info(
            "Patch completion recorded — hostname=%s last_patch_date=%s installed=%d",
            hostname,
            patch_dt.isoformat(),
            len(installed) if isinstance(installed, list) else 0,
        )

    except Exception:
        db.session.rollback()
        logger.exception("record_patch_completion failed for hostname=%s", hostname)
        result.success = False
        result.error = "Database error — patch completion update failed"

    return result


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
        server.cpu_count = _parse_int(data.get("cpu_count"))
        server.cpu_model = _safe_str(data.get("cpu_model"), max_len=255)
        server.ram_gb = _parse_float(data.get("ram_gb"))

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
        # last_patch_date: only write when the payload carries a real date.
        # payload.yml sends last_patch_date="" (blank) during inventory sync so
        # we must NOT overwrite a date that was set by POST /api/v1/patching.
        _lpd = _parse_datetime(data.get("last_patch_date"))
        if _lpd is not None:
            patching.last_patch_date = _lpd

        # last_reboot_date: same guard — blank string means "not provided"
        _lrd = _parse_datetime(data.get("last_reboot"))
        if _lrd is not None:
            patching.last_reboot_date = _lrd

        patching.pending_updates = _parse_int(data.get("pending_updates")) or 0

        # reboot_required: only update when explicitly provided in payload
        if "reboot_required" in data:
            rr = data["reboot_required"]
            patching.reboot_required = bool(rr) if rr is not None else None

        patching.updated_at = now

        db.session.flush()

        # ── Sync available-update package list ─────────────────────────
        # The payload's updates.available_packages is a list of structured
        # dicts produced by the lop_inventory_sync role's updates.yml task.
        # If present, we replace the server's available-update rows with the
        # fresh list.  If absent (old-style payload), we skip to preserve any
        # existing package data.
        updates_block = data.get("updates")
        if isinstance(updates_block, dict):
            available_packages = updates_block.get("available_packages")
            if isinstance(available_packages, list):
                _upsert_available_updates(server.id, available_packages, now)

        db.session.commit()
        logger.info(
            "Inventory upsert — action=%s hostname=%s ip=%s pending_updates=%s",
            result.action, hostname, server.ip_address,
            patching.pending_updates,
        )

    except Exception:
        db.session.rollback()
        logger.exception("Inventory upsert failed for hostname=%s", hostname)
        result.success = False
        result.error = "Database error — inventory update failed"

    return result

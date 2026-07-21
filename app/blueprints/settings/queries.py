"""
Settings query helpers.

All database reads and writes for the Settings module live here.
Routes stay thin; all business logic and DB access is here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ...extensions import db
from ...models.api_token import ApiToken
from ...models.directory_config import DirectoryConfig, DIRECTORY_TYPES
from ...models.environment import Environment
from ...models.ldap_group_mapping import LdapGroupMapping, VALID_ROLES as MAPPING_VALID_ROLES
from ...models.location import Location
from ...models.owner import Owner
from ...utils import sort_envs

logger = logging.getLogger(__name__)


# ── Data containers ───────────────────────────────────────────────────────── #

@dataclass
class SettingsData:
    locations:      list = field(default_factory=list)
    environments:   list = field(default_factory=list)
    owners:         list = field(default_factory=list)
    api_token:      "ApiToken | None" = None
    dir_config:     "DirectoryConfig | None" = None
    group_mappings: list = field(default_factory=list)


@dataclass
class QueryResult:
    success: bool = True
    error:   str  = ""
    name:    str  = ""


# ── Read helpers ──────────────────────────────────────────────────────────── #

VALID_COLORS = ("primary", "secondary", "success", "danger", "warning", "info")


def get_settings_data() -> SettingsData:
    """Return all locations, environments, owners, API token, and directory config."""
    data = SettingsData()
    try:
        data.locations      = Location.query.order_by(Location.name).all()
        data.environments   = sort_envs(Environment.query.all())
        data.owners         = Owner.query.order_by(Owner.name).all()
        data.api_token      = ApiToken.get_active()
        data.dir_config     = DirectoryConfig.get()
        data.group_mappings = LdapGroupMapping.query.order_by(LdapGroupMapping.role).all()
    except Exception:
        logger.exception("Failed to load settings data")
    return data


# ── Location CRUD ─────────────────────────────────────────────────────────── #

def add_location(name: str, description: str) -> QueryResult:
    name = name.strip()
    if not name:
        return QueryResult(success=False, error="Location name is required.")
    if Location.query.filter(db.func.lower(Location.name) == name.lower()).first():
        return QueryResult(success=False, error=f'A location named "{name}" already exists.')
    try:
        db.session.add(Location(name=name, description=description.strip() or None))
        db.session.commit()
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to create location: %s", name)
        return QueryResult(success=False, error="Database error — could not save location.")


def edit_location(location_id: int, name: str, description: str, is_active: bool) -> QueryResult:
    loc = Location.query.get(location_id)
    if not loc:
        return QueryResult(success=False, error="Location not found.")
    name = name.strip()
    if not name:
        return QueryResult(success=False, error="Location name is required.")
    if Location.query.filter(db.func.lower(Location.name) == name.lower(), Location.id != location_id).first():
        return QueryResult(success=False, error=f'Another location named "{name}" already exists.')
    try:
        loc.name = name; loc.description = description.strip() or None; loc.is_active = is_active
        db.session.commit()
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to update location id=%d", location_id)
        return QueryResult(success=False, error="Database error — could not update location.")


def delete_location(location_id: int) -> QueryResult:
    loc = Location.query.get(location_id)
    if not loc:
        return QueryResult(success=False, error="Location not found.")
    server_count = loc.servers.count()
    if server_count:
        return QueryResult(success=False, error=f'Cannot delete "{loc.name}" — {server_count} server{"s" if server_count != 1 else ""} assigned to it.')
    name = loc.name
    try:
        db.session.delete(loc); db.session.commit()
        return QueryResult(name=name)
    except Exception:
        db.session.rollback()
        return QueryResult(success=False, error="Database error — could not delete location.")


# ── Environment CRUD ──────────────────────────────────────────────────────── #

def add_environment(name: str, label: str, color: str) -> QueryResult:
    name  = name.strip(); label = label.strip()
    color = color.strip() if color.strip() in VALID_COLORS else "secondary"
    if not name:  return QueryResult(success=False, error="Environment name is required.")
    if not label: return QueryResult(success=False, error="Environment label is required.")
    if Environment.query.filter(db.func.lower(Environment.name) == name.lower()).first():
        return QueryResult(success=False, error=f'An environment named "{name}" already exists.')
    try:
        db.session.add(Environment(name=name, label=label, color=color)); db.session.commit()
        return QueryResult()
    except Exception:
        db.session.rollback()
        return QueryResult(success=False, error="Database error — could not save environment.")


def edit_environment(env_id: int, name: str, label: str, color: str, is_active: bool) -> QueryResult:
    env = Environment.query.get(env_id)
    if not env: return QueryResult(success=False, error="Environment not found.")
    name  = name.strip(); label = label.strip()
    color = color.strip() if color.strip() in VALID_COLORS else "secondary"
    if not name:  return QueryResult(success=False, error="Environment name is required.")
    if not label: return QueryResult(success=False, error="Environment label is required.")
    if Environment.query.filter(db.func.lower(Environment.name) == name.lower(), Environment.id != env_id).first():
        return QueryResult(success=False, error=f'Another environment named "{name}" already exists.')
    try:
        env.name = name; env.label = label; env.color = color; env.is_active = is_active
        db.session.commit(); return QueryResult()
    except Exception:
        db.session.rollback()
        return QueryResult(success=False, error="Database error — could not update environment.")


def delete_environment(env_id: int) -> QueryResult:
    env = Environment.query.get(env_id)
    if not env: return QueryResult(success=False, error="Environment not found.")
    server_count = env.servers.count()
    if server_count:
        return QueryResult(success=False, error=f'Cannot delete "{env.name}" — {server_count} server{"s" if server_count != 1 else ""} assigned to it.')
    name = env.name
    try:
        db.session.delete(env); db.session.commit(); return QueryResult(name=name)
    except Exception:
        db.session.rollback()
        return QueryResult(success=False, error="Database error — could not delete environment.")


# ── Owner CRUD ────────────────────────────────────────────────────────────── #

def add_owner(name: str, email: str) -> QueryResult:
    name = name.strip(); email = email.strip() or None
    if not name: return QueryResult(success=False, error="Owner name is required.")
    if Owner.query.filter(db.func.lower(Owner.name) == name.lower()).first():
        return QueryResult(success=False, error=f'An owner named "{name}" already exists.')
    try:
        db.session.add(Owner(name=name, email=email)); db.session.commit(); return QueryResult()
    except Exception:
        db.session.rollback()
        return QueryResult(success=False, error="Database error — could not save owner.")


def edit_owner(owner_id: int, name: str, email: str, is_active: bool) -> QueryResult:
    owner = Owner.query.get(owner_id)
    if not owner: return QueryResult(success=False, error="Owner not found.")
    name = name.strip(); email = email.strip() or None
    if not name: return QueryResult(success=False, error="Owner name is required.")
    if Owner.query.filter(db.func.lower(Owner.name) == name.lower(), Owner.id != owner_id).first():
        return QueryResult(success=False, error=f'Another owner named "{name}" already exists.')
    try:
        owner.name = name; owner.email = email; owner.is_active = is_active
        db.session.commit(); return QueryResult()
    except Exception:
        db.session.rollback()
        return QueryResult(success=False, error="Database error — could not update owner.")


def delete_owner(owner_id: int) -> QueryResult:
    owner = Owner.query.get(owner_id)
    if not owner: return QueryResult(success=False, error="Owner not found.")
    server_count = owner.servers.count()
    if server_count:
        return QueryResult(success=False, error=f'Cannot delete "{owner.name}" — {server_count} server{"s" if server_count != 1 else ""} assigned to it.')
    name = owner.name
    try:
        db.session.delete(owner); db.session.commit(); return QueryResult(name=name)
    except Exception:
        db.session.rollback()
        return QueryResult(success=False, error="Database error — could not delete owner.")


# ── API Token management ───────────────────────────────────────────────── #

def generate_api_token() -> "tuple[QueryResult, str]":
    raw_token = ApiToken.generate_token()
    try:
        ApiToken.query.filter_by(is_active=True).update({"is_active": False})
        db.session.add(ApiToken(token=raw_token, is_active=True))
        db.session.commit()
        return QueryResult(), raw_token
    except Exception:
        db.session.rollback()
        logger.exception("Failed to generate API token")
        return QueryResult(success=False, error="Database error — could not generate token."), ""


def revoke_api_token() -> QueryResult:
    try:
        ApiToken.query.filter_by(is_active=True).update({"is_active": False})
        db.session.commit(); return QueryResult()
    except Exception:
        db.session.rollback()
        return QueryResult(success=False, error="Database error — could not revoke token.")


# ── Directory Services CRUD ────────────────────────────────────────────────── #

def save_directory_config(form: dict) -> QueryResult:
    """Create or update the directory configuration from submitted form data."""
    try:
        cfg = DirectoryConfig.get_or_create()

        cfg.directory_type       = form.get("directory_type", "freeipa")
        cfg.uri                  = form.get("uri", "").strip()
        cfg.port                 = int(form["port"]) if form.get("port", "").strip() else None
        cfg.base_dn              = form.get("base_dn", "").strip()
        cfg.bind_dn              = form.get("bind_dn", "").strip()
        cfg.user_search_base     = form.get("user_search_base", "").strip() or None
        cfg.group_search_base    = form.get("group_search_base", "").strip() or None
        cfg.user_search_filter   = form.get("user_search_filter", "(uid={username})").strip() or "(uid={username})"
        cfg.group_search_filter  = form.get("group_search_filter", "(objectClass=groupOfNames)").strip() or "(objectClass=groupOfNames)"
        cfg.ssl_enabled          = form.get("ssl_enabled") == "1"
        cfg.verify_cert          = form.get("verify_cert") == "1"
        cfg.ca_cert_path         = form.get("ca_cert_path", "").strip() or None
        cfg.timeout              = max(1, int(form.get("timeout", 10) or 10))
        cfg.default_role         = form.get("default_role", "operator")
        if cfg.default_role not in MAPPING_VALID_ROLES:
            cfg.default_role = "operator"

        # Only update password if a new one was submitted
        new_password = form.get("bind_password", "").strip()
        if new_password:
            cfg.set_bind_password(new_password)

        db.session.commit()
        logger.info("Directory config saved: type=%s uri=%s", cfg.directory_type, cfg.uri)
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to save directory config")
        return QueryResult(success=False, error="Database error — could not save directory configuration.")


def toggle_directory_auth(enabled: bool) -> QueryResult:
    """Enable or disable directory authentication."""
    try:
        cfg = DirectoryConfig.get_or_create()
        cfg.is_enabled = enabled
        db.session.commit()
        logger.info("Directory auth %s", "enabled" if enabled else "disabled")
        return QueryResult()
    except Exception:
        db.session.rollback()
        return QueryResult(success=False, error="Database error — could not update directory configuration.")


def add_group_mapping(group_dn: str, role: str) -> QueryResult:
    """Add an LDAP group → role mapping."""
    group_dn = group_dn.strip()
    if not group_dn:
        return QueryResult(success=False, error="Group DN / CN is required.")
    if role not in MAPPING_VALID_ROLES:
        return QueryResult(success=False, error=f"Invalid role '{role}'.")
    if LdapGroupMapping.query.filter_by(group_dn=group_dn).first():
        return QueryResult(success=False, error=f'A mapping for "{group_dn}" already exists.')
    try:
        db.session.add(LdapGroupMapping(group_dn=group_dn, role=role))
        db.session.commit()
        return QueryResult()
    except Exception:
        db.session.rollback()
        return QueryResult(success=False, error="Database error — could not save group mapping.")


def delete_group_mapping(mapping_id: int) -> QueryResult:
    """Delete an LDAP group mapping."""
    mapping = LdapGroupMapping.query.get(mapping_id)
    if not mapping:
        return QueryResult(success=False, error="Group mapping not found.")
    name = mapping.group_dn
    try:
        db.session.delete(mapping); db.session.commit()
        return QueryResult(name=name)
    except Exception:
        db.session.rollback()
        return QueryResult(success=False, error="Database error — could not delete group mapping.")

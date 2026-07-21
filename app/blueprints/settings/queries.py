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
from ...models.environment import Environment
from ...models.location import Location
from ...models.owner import Owner

logger = logging.getLogger(__name__)


# ── Data containers ───────────────────────────────────────────────────────── #

@dataclass
class SettingsData:
    locations:    list = field(default_factory=list)
    environments: list = field(default_factory=list)
    owners:       list = field(default_factory=list)
    api_token:    "ApiToken | None" = None


@dataclass
class QueryResult:
    success: bool = True
    error:   str  = ""


# ── Read helpers ──────────────────────────────────────────────────────────── #

def get_settings_data() -> SettingsData:
    """Return all locations, environments, owners, and the active API token."""
    data = SettingsData()
    try:
        data.locations    = Location.query.order_by(Location.name).all()
        data.environments = Environment.query.order_by(Environment.id).all()
        data.owners       = Owner.query.order_by(Owner.name).all()
        data.api_token    = ApiToken.get_active()
    except Exception:
        logger.exception("Failed to load settings data")
    return data


# ── Location CRUD ─────────────────────────────────────────────────────────── #

def add_location(name: str, description: str) -> QueryResult:
    """Insert a new Location.  Validates for duplicate name."""
    name = name.strip()
    if not name:
        return QueryResult(success=False, error="Location name is required.")

    if Location.query.filter(
        db.func.lower(Location.name) == name.lower()
    ).first():
        return QueryResult(
            success=False,
            error=f'A location named "{name}" already exists.',
        )

    try:
        db.session.add(Location(name=name, description=description.strip() or None))
        db.session.commit()
        logger.info("Location created: %s", name)
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to create location: %s", name)
        return QueryResult(success=False, error="Database error — could not save location.")


def edit_location(location_id: int, name: str, description: str, is_active: bool) -> QueryResult:
    """Update an existing Location."""
    loc = Location.query.get(location_id)
    if not loc:
        return QueryResult(success=False, error="Location not found.")

    name = name.strip()
    if not name:
        return QueryResult(success=False, error="Location name is required.")

    duplicate = Location.query.filter(
        db.func.lower(Location.name) == name.lower(),
        Location.id != location_id,
    ).first()
    if duplicate:
        return QueryResult(
            success=False,
            error=f'Another location named "{name}" already exists.',
        )

    try:
        loc.name        = name
        loc.description = description.strip() or None
        loc.is_active   = is_active
        db.session.commit()
        logger.info("Location updated: id=%d name=%s", location_id, name)
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to update location id=%d", location_id)
        return QueryResult(success=False, error="Database error — could not update location.")


def delete_location(location_id: int) -> QueryResult:
    """Delete a Location.  Blocked if any servers reference it."""
    loc = Location.query.get(location_id)
    if not loc:
        return QueryResult(success=False, error="Location not found.")

    server_count = loc.servers.count()
    if server_count:
        return QueryResult(
            success=False,
            error=(
                f'Cannot delete "{loc.name}" — '
                f'{server_count} server{"s" if server_count != 1 else ""} '
                f'{"are" if server_count != 1 else "is"} assigned to it.'
            ),
        )

    try:
        db.session.delete(loc)
        db.session.commit()
        logger.info("Location deleted: id=%d name=%s", location_id, loc.name)
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to delete location id=%d", location_id)
        return QueryResult(success=False, error="Database error — could not delete location.")


# ── Environment CRUD ──────────────────────────────────────────────────────── #

VALID_COLORS = ("primary", "secondary", "success", "danger", "warning", "info")


def add_environment(name: str, label: str, color: str) -> QueryResult:
    """Insert a new Environment."""
    name  = name.strip()
    label = label.strip()
    color = color.strip() if color.strip() in VALID_COLORS else "secondary"

    if not name:
        return QueryResult(success=False, error="Environment name is required.")
    if not label:
        return QueryResult(success=False, error="Environment label is required.")

    if Environment.query.filter(
        db.func.lower(Environment.name) == name.lower()
    ).first():
        return QueryResult(
            success=False,
            error=f'An environment named "{name}" already exists.',
        )

    try:
        db.session.add(Environment(name=name, label=label, color=color))
        db.session.commit()
        logger.info("Environment created: %s", name)
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to create environment: %s", name)
        return QueryResult(success=False, error="Database error — could not save environment.")


def edit_environment(
    env_id: int, name: str, label: str, color: str, is_active: bool
) -> QueryResult:
    """Update an existing Environment."""
    env = Environment.query.get(env_id)
    if not env:
        return QueryResult(success=False, error="Environment not found.")

    name  = name.strip()
    label = label.strip()
    color = color.strip() if color.strip() in VALID_COLORS else "secondary"

    if not name:
        return QueryResult(success=False, error="Environment name is required.")
    if not label:
        return QueryResult(success=False, error="Environment label is required.")

    duplicate = Environment.query.filter(
        db.func.lower(Environment.name) == name.lower(),
        Environment.id != env_id,
    ).first()
    if duplicate:
        return QueryResult(
            success=False,
            error=f'Another environment named "{name}" already exists.',
        )

    try:
        env.name      = name
        env.label     = label
        env.color     = color
        env.is_active = is_active
        db.session.commit()
        logger.info("Environment updated: id=%d name=%s", env_id, name)
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to update environment id=%d", env_id)
        return QueryResult(success=False, error="Database error — could not update environment.")


def delete_environment(env_id: int) -> QueryResult:
    """Delete an Environment.  Blocked if any servers reference it."""
    env = Environment.query.get(env_id)
    if not env:
        return QueryResult(success=False, error="Environment not found.")

    server_count = env.servers.count()
    if server_count:
        return QueryResult(
            success=False,
            error=(
                f'Cannot delete "{env.name}" — '
                f'{server_count} server{"s" if server_count != 1 else ""} '
                f'{"are" if server_count != 1 else "is"} assigned to it.'
            ),
        )

    try:
        db.session.delete(env)
        db.session.commit()
        logger.info("Environment deleted: id=%d name=%s", env_id, env.name)
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to delete environment id=%d", env_id)
        return QueryResult(success=False, error="Database error — could not delete environment.")


# ── Owner CRUD ────────────────────────────────────────────────────────────── #

def add_owner(name: str, email: str) -> QueryResult:
    """Insert a new Owner."""
    name  = name.strip()
    email = email.strip() or None

    if not name:
        return QueryResult(success=False, error="Owner name is required.")

    if Owner.query.filter(
        db.func.lower(Owner.name) == name.lower()
    ).first():
        return QueryResult(
            success=False,
            error=f'An owner named "{name}" already exists.',
        )

    try:
        db.session.add(Owner(name=name, email=email))
        db.session.commit()
        logger.info("Owner created: %s", name)
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to create owner: %s", name)
        return QueryResult(success=False, error="Database error — could not save owner.")


def edit_owner(owner_id: int, name: str, email: str, is_active: bool) -> QueryResult:
    """Update an existing Owner."""
    owner = Owner.query.get(owner_id)
    if not owner:
        return QueryResult(success=False, error="Owner not found.")

    name  = name.strip()
    email = email.strip() or None

    if not name:
        return QueryResult(success=False, error="Owner name is required.")

    duplicate = Owner.query.filter(
        db.func.lower(Owner.name) == name.lower(),
        Owner.id != owner_id,
    ).first()
    if duplicate:
        return QueryResult(
            success=False,
            error=f'Another owner named "{name}" already exists.',
        )

    try:
        owner.name      = name
        owner.email     = email
        owner.is_active = is_active
        db.session.commit()
        logger.info("Owner updated: id=%d name=%s", owner_id, name)
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to update owner id=%d", owner_id)
        return QueryResult(success=False, error="Database error — could not update owner.")


def delete_owner(owner_id: int) -> QueryResult:
    """Delete an Owner.  Blocked if any servers reference it."""
    owner = Owner.query.get(owner_id)
    if not owner:
        return QueryResult(success=False, error="Owner not found.")

    server_count = owner.servers.count()
    if server_count:
        return QueryResult(
            success=False,
            error=(
                f'Cannot delete "{owner.name}" — '
                f'{server_count} server{"s" if server_count != 1 else ""} '
                f'{"are" if server_count != 1 else "is"} assigned to it.'
            ),
        )

    try:
        db.session.delete(owner)
        db.session.commit()
        logger.info("Owner deleted: id=%d name=%s", owner_id, owner.name)
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to delete owner id=%d", owner_id)
        return QueryResult(success=False, error="Database error — could not delete owner.")


# ── API Token management ───────────────────────────────────────────────── #

def generate_api_token() -> "tuple[QueryResult, str]":
    """
    Deactivate any existing token and create a new active one.

    Returns (QueryResult, raw_token_string).  The raw token is only
    available here; it is stored in plain-text so the admin can copy it.
    """
    raw_token = ApiToken.generate_token()
    try:
        # Deactivate all existing tokens
        ApiToken.query.filter_by(is_active=True).update({"is_active": False})
        # Create the new token
        token_obj = ApiToken(token=raw_token, is_active=True)
        db.session.add(token_obj)
        db.session.commit()
        logger.info("API token generated/regenerated")
        return QueryResult(), raw_token
    except Exception:
        db.session.rollback()
        logger.exception("Failed to generate API token")
        return QueryResult(success=False, error="Database error — could not generate token."), ""


def revoke_api_token() -> QueryResult:
    """Deactivate all active API tokens."""
    try:
        count = ApiToken.query.filter_by(is_active=True).update({"is_active": False})
        db.session.commit()
        logger.info("API token(s) revoked: count=%d", count)
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to revoke API token")
        return QueryResult(success=False, error="Database error — could not revoke token.")

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
from ...models.user import User
from ...utils import sort_envs

logger = logging.getLogger(__name__)


# ── Data containers ───────────────────────────────────────────────────────── #

@dataclass
class SettingsData:
    locations:    list = field(default_factory=list)
    environments: list = field(default_factory=list)
    owners:       list = field(default_factory=list)
    users:        list = field(default_factory=list)
    api_token:    "ApiToken | None" = None


@dataclass
class QueryResult:
    success: bool = True
    error:   str  = ""
    name:    str  = ""   # populated by delete/lookup operations for audit logging


# ── Read helpers ──────────────────────────────────────────────────────────── #

def get_settings_data() -> SettingsData:
    """Return all locations, environments, owners, users, and the active API token."""
    data = SettingsData()
    try:
        data.locations    = Location.query.order_by(Location.name).all()
        data.environments = sort_envs(Environment.query.all())
        data.owners       = Owner.query.order_by(Owner.name).all()
        data.users        = User.query.order_by(User.username).all()
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

    name = loc.name
    try:
        db.session.delete(loc)
        db.session.commit()
        logger.info("Location deleted: id=%d name=%s", location_id, name)
        return QueryResult(name=name)
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

    name = env.name
    try:
        db.session.delete(env)
        db.session.commit()
        logger.info("Environment deleted: id=%d name=%s", env_id, name)
        return QueryResult(name=name)
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

    name = owner.name
    try:
        db.session.delete(owner)
        db.session.commit()
        logger.info("Owner deleted: id=%d name=%s", owner_id, name)
        return QueryResult(name=name)
    except Exception:
        db.session.rollback()
        logger.exception("Failed to delete owner id=%d", owner_id)
        return QueryResult(success=False, error="Database error — could not delete owner.")


# ── User CRUD ─────────────────────────────────────────────────────────────── #

MIN_PASSWORD_LENGTH = 8


def add_user(username: str, password: str) -> QueryResult:
    """Create a new portal user account."""
    username = username.strip()
    if not username:
        return QueryResult(success=False, error="Username is required.")
    if len(username) > 64:
        return QueryResult(success=False, error="Username must be 64 characters or fewer.")
    if len(password) < MIN_PASSWORD_LENGTH:
        return QueryResult(
            success=False,
            error=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )

    if User.query.filter(
        db.func.lower(User.username) == username.lower()
    ).first():
        return QueryResult(
            success=False,
            error=f'A user named "{username}" already exists.',
        )

    try:
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        logger.info("User created: %s", username)
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to create user: %s", username)
        return QueryResult(success=False, error="Database error — could not create user.")


def change_password(user_id: int, new_password: str) -> QueryResult:
    """Change a user's password."""
    user = User.query.get(user_id)
    if not user:
        return QueryResult(success=False, error="User not found.")
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return QueryResult(
            success=False,
            error=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )
    try:
        user.set_password(new_password)
        db.session.commit()
        logger.info("Password changed for user id=%d (%s)", user_id, user.username)
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to change password for user id=%d", user_id)
        return QueryResult(success=False, error="Database error — could not update password.")


def toggle_user_active(user_id: int, is_active: bool, current_user_id: int) -> QueryResult:
    """Activate or deactivate a user account."""
    user = User.query.get(user_id)
    if not user:
        return QueryResult(success=False, error="User not found.")

    if not is_active and user_id == current_user_id:
        return QueryResult(success=False, error="You cannot deactivate your own account.")

    # Prevent deactivating the last active user
    if not is_active:
        active_count = User.query.filter_by(is_active=True).count()
        if active_count <= 1:
            return QueryResult(
                success=False,
                error="Cannot deactivate the last active user.",
            )

    try:
        user.is_active = is_active
        db.session.commit()
        state = "activated" if is_active else "deactivated"
        logger.info("User %s id=%d (%s)", state, user_id, user.username)
        return QueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to toggle active for user id=%d", user_id)
        return QueryResult(success=False, error="Database error — could not update user.")


def delete_user(user_id: int, current_user_id: int) -> QueryResult:
    """Delete a user account.  Blocked for the currently logged-in user."""
    user = User.query.get(user_id)
    if not user:
        return QueryResult(success=False, error="User not found.")

    if user_id == current_user_id:
        return QueryResult(success=False, error="You cannot delete your own account.")

    # Prevent deleting the last user entirely
    total = User.query.count()
    if total <= 1:
        return QueryResult(success=False, error="Cannot delete the last user account.")

    username = user.username
    try:
        db.session.delete(user)
        db.session.commit()
        logger.info("User deleted: id=%d (%s)", user_id, username)
        return QueryResult(name=username)
    except Exception:
        db.session.rollback()
        logger.exception("Failed to delete user id=%d", user_id)
        return QueryResult(success=False, error="Database error — could not delete user.")


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

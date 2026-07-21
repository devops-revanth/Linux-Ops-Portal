"""
User Management query helpers.

All database reads and writes for the Users module live here.
Routes stay thin; all business logic and DB access is here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ...extensions import db
from ...models.user import User

logger = logging.getLogger(__name__)

PER_PAGE = 50
MIN_PASSWORD_LENGTH = 8

VALID_ROLES = ("administrator", "operator", "readonly")
VALID_SORT_COLS = ("username", "role", "auth_source", "is_active", "last_login", "created_at")


# ── Result container ──────────────────────────────────────────────────────── #

@dataclass
class UserQueryResult:
    success: bool = True
    error:   str  = ""
    name:    str  = ""


# ── Filter dataclass ──────────────────────────────────────────────────────── #

@dataclass
class UserFilters:
    search:      str = ""
    role:        str = ""
    auth_source: str = ""
    status:      str = ""   # "active" | "inactive" | ""
    sort:        str = "username"
    order:       str = "asc"
    page:        int = 1

    @classmethod
    def from_request(cls, args: dict) -> "UserFilters":
        try:
            page = max(1, int(args.get("page", 1)))
        except (ValueError, TypeError):
            page = 1
        sort = args.get("sort", "username")
        if sort not in VALID_SORT_COLS:
            sort = "username"
        order = "asc" if args.get("order", "asc") == "asc" else "desc"
        return cls(
            search      = args.get("search",      "").strip(),
            role        = args.get("role",        "").strip(),
            auth_source = args.get("auth_source", "").strip(),
            status      = args.get("status",      "").strip(),
            sort        = sort,
            order       = order,
            page        = page,
        )

    def has_active_filters(self) -> bool:
        return any([self.search, self.role, self.auth_source, self.status])


# ── Sort map ──────────────────────────────────────────────────────────────── #

_SORT_COLS = {
    "username":    User.username,
    "role":        User.role,
    "auth_source": User.auth_source,
    "is_active":   User.is_active,
    "last_login":  User.last_login,
    "created_at":  User.created_at,
}


# ── Read helpers ──────────────────────────────────────────────────────────── #

def get_users_page(filters: UserFilters):
    """Return a paginated result of users matching the given filters."""
    try:
        q = User.query

        if filters.search:
            term = f"%{filters.search}%"
            q = q.filter(
                db.or_(
                    User.username.ilike(term),
                    User.display_name.ilike(term),
                    User.email.ilike(term),
                )
            )
        if filters.role:
            q = q.filter(User.role == filters.role)
        if filters.auth_source:
            q = q.filter(User.auth_source == filters.auth_source)
        if filters.status == "active":
            q = q.filter(User.is_active == True)  # noqa: E712
        elif filters.status == "inactive":
            q = q.filter(User.is_active == False)  # noqa: E712

        col = _SORT_COLS.get(filters.sort, User.username)
        q = q.order_by(col.asc() if filters.order == "asc" else col.desc())

        return q.paginate(page=filters.page, per_page=PER_PAGE, error_out=False)
    except Exception:
        logger.exception("Failed to query users page")
        return None


def get_user(user_id: int) -> "User | None":
    return User.query.get(user_id)


# ── Write helpers ─────────────────────────────────────────────────────────── #

def add_local_user(username: str, password: str, role: str = "operator") -> UserQueryResult:
    """Create a new local user account."""
    username = username.strip()
    if not username:
        return UserQueryResult(success=False, error="Username is required.")
    if len(username) > 64:
        return UserQueryResult(success=False, error="Username must be 64 characters or fewer.")
    if len(password) < MIN_PASSWORD_LENGTH:
        return UserQueryResult(success=False, error=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if role not in VALID_ROLES:
        role = "operator"

    if User.query.filter(db.func.lower(User.username) == username.lower()).first():
        return UserQueryResult(success=False, error=f'A user named "{username}" already exists.')

    try:
        user = User(username=username, role=role, auth_source="local")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        logger.info("Local user created: %s (role=%s)", username, role)
        return UserQueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to create user: %s", username)
        return UserQueryResult(success=False, error="Database error — could not create user.")


def change_password(user_id: int, new_password: str) -> UserQueryResult:
    """Change a local user's password. LDAP users cannot use this."""
    user = User.query.get(user_id)
    if not user:
        return UserQueryResult(success=False, error="User not found.")
    if user.auth_source == "ldap":
        return UserQueryResult(success=False, error="Cannot set a local password for a directory user.")
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return UserQueryResult(success=False, error=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    try:
        user.set_password(new_password)
        db.session.commit()
        logger.info("Password changed for user id=%d (%s)", user_id, user.username)
        return UserQueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to change password for user id=%d", user_id)
        return UserQueryResult(success=False, error="Database error — could not update password.")


def edit_role(user_id: int, new_role: str) -> UserQueryResult:
    """Change a user's portal role."""
    if new_role not in VALID_ROLES:
        return UserQueryResult(success=False, error=f"Invalid role '{new_role}'.")
    user = User.query.get(user_id)
    if not user:
        return UserQueryResult(success=False, error="User not found.")
    try:
        user.role = new_role
        db.session.commit()
        logger.info("Role changed for user id=%d (%s) → %s", user_id, user.username, new_role)
        return UserQueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to change role for user id=%d", user_id)
        return UserQueryResult(success=False, error="Database error — could not update role.")


def toggle_user_active(user_id: int, is_active: bool, current_user_id: int) -> UserQueryResult:
    """Activate or deactivate a user account."""
    user = User.query.get(user_id)
    if not user:
        return UserQueryResult(success=False, error="User not found.")
    if not is_active and user_id == current_user_id:
        return UserQueryResult(success=False, error="You cannot deactivate your own account.")
    if not is_active:
        active_count = User.query.filter_by(is_active=True).count()
        if active_count <= 1:
            return UserQueryResult(success=False, error="Cannot deactivate the last active user.")
    try:
        user.is_active = is_active
        db.session.commit()
        logger.info("User %s id=%d (%s)", "activated" if is_active else "deactivated", user_id, user.username)
        return UserQueryResult()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to toggle active for user id=%d", user_id)
        return UserQueryResult(success=False, error="Database error — could not update user.")


def delete_user(user_id: int, current_user_id: int) -> UserQueryResult:
    """Delete a local user account."""
    user = User.query.get(user_id)
    if not user:
        return UserQueryResult(success=False, error="User not found.")
    if user_id == current_user_id:
        return UserQueryResult(success=False, error="You cannot delete your own account.")
    if User.query.count() <= 1:
        return UserQueryResult(success=False, error="Cannot delete the last user account.")
    username = user.username
    try:
        db.session.delete(user)
        db.session.commit()
        logger.info("User deleted: id=%d (%s)", user_id, username)
        return UserQueryResult(name=username)
    except Exception:
        db.session.rollback()
        logger.exception("Failed to delete user id=%d", user_id)
        return UserQueryResult(success=False, error="Database error — could not delete user.")

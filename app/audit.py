"""
Audit logging helper for the Linux Operations Portal.

Two usage patterns depending on whether the caller owns the transaction:

1. **Caller owns the commit** (inventory/patching routes — write then commit):

       db.session.add(some_object)
       log_action("inventory.server.add", target="web01", details="10.0.0.1")
       db.session.commit()   # audit entry commits together with the main change

2. **Transaction already committed** (settings routes — queries.py already committed):

       result = add_location(name, ...)
       if result.success:
           commit_audit("settings.location.add", target=name)

Errors in both helpers are swallowed so a logging failure never breaks the
main user-facing operation.
"""
import logging

from flask_login import current_user

from .extensions import db
from .models.audit_log import AuditLog

logger = logging.getLogger(__name__)

_MAX_DETAILS = 1000


def _current_actor() -> str:
    try:
        return current_user.username if current_user.is_authenticated else "system"
    except Exception:
        return "system"


def log_action(
    action: str,
    target: str | None = None,
    details: str | None = None,
) -> None:
    """Add an AuditLog row to the **current** session (no commit).

    Call this *before* ``db.session.commit()`` so the entry joins the same
    transaction as the main operation.
    """
    try:
        if details and len(details) > _MAX_DETAILS:
            details = details[: _MAX_DETAILS - 1] + "…"
        entry = AuditLog(actor=_current_actor(), action=action, target=target, details=details)
        db.session.add(entry)
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit.log_action failed (action=%s): %s", action, exc)


def commit_audit(
    action: str,
    target: str | None = None,
    details: str | None = None,
) -> None:
    """Add an AuditLog row and **immediately commit** it.

    Use when the main write has already been committed by a lower layer
    (e.g. settings queries.py functions that commit internally).
    """
    try:
        if details and len(details) > _MAX_DETAILS:
            details = details[: _MAX_DETAILS - 1] + "…"
        entry = AuditLog(actor=_current_actor(), action=action, target=target, details=details)
        db.session.add(entry)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.warning("audit.commit_audit failed (action=%s): %s", action, exc)

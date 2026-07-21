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

Both helpers automatically capture: client IP, User-Agent, auth_source, session ID,
and module (derived from the action string) so callers rarely need to pass these.

Errors in both helpers are swallowed so a logging failure never breaks the
main user-facing operation.
"""
import logging

from flask_login import current_user

from .extensions import db
from .models.audit_log import AuditLog

logger = logging.getLogger(__name__)

_MAX_DETAILS = 1000
_MAX_UA = 500


def _current_actor() -> str:
    try:
        return current_user.username if current_user.is_authenticated else "system"
    except Exception:
        return "system"


def _derive_module(action: str) -> str:
    """Return the first dot-segment of an action string, e.g. 'inventory'."""
    return action.split(".")[0] if action else ""


def _request_context() -> dict:
    """
    Collect request-scoped metadata without failing when called outside a
    request context (e.g. from the seeder or CLI commands).
    """
    ctx: dict = {
        "ip_address": None,
        "user_agent": None,
        "session_id": None,
        "auth_source": None,
    }
    try:
        from flask import has_request_context, request, session
        if has_request_context():
            ctx["ip_address"] = request.remote_addr
            ua = request.headers.get("User-Agent", "")
            ctx["user_agent"] = ua[:_MAX_UA] if ua else None
            ctx["session_id"] = session.get("_id")  # Flask session id if set

        # auth_source from current user
        try:
            if current_user.is_authenticated:
                ctx["auth_source"] = getattr(current_user, "auth_source", None)
        except Exception:
            pass
    except Exception:
        pass
    return ctx


def _build_entry(
    action: str,
    target: str | None = None,
    details: str | None = None,
    result: str = "success",
    module: str | None = None,
    ip_address: str | None = None,
    auth_source: str | None = None,
    user_agent: str | None = None,
    session_id: str | None = None,
    before_values: str | None = None,
    after_values: str | None = None,
) -> AuditLog:
    """Construct an AuditLog row, merging request context with explicit overrides."""
    ctx = _request_context()
    if details and len(details) > _MAX_DETAILS:
        details = details[: _MAX_DETAILS - 1] + "…"
    return AuditLog(
        actor         = _current_actor(),
        module        = module or _derive_module(action),
        action        = action,
        target        = target,
        details       = details,
        result        = result,
        ip_address    = ip_address or ctx["ip_address"],
        auth_source   = auth_source or ctx["auth_source"],
        user_agent    = user_agent or ctx["user_agent"],
        session_id    = session_id or ctx["session_id"],
        before_values = before_values,
        after_values  = after_values,
    )


def log_action(
    action: str,
    target: str | None = None,
    details: str | None = None,
    result: str = "success",
    module: str | None = None,
    ip_address: str | None = None,
    auth_source: str | None = None,
    user_agent: str | None = None,
    session_id: str | None = None,
    before_values: str | None = None,
    after_values: str | None = None,
) -> None:
    """Add an AuditLog row to the **current** session (no commit).

    Call this *before* ``db.session.commit()`` so the entry joins the same
    transaction as the main operation.
    """
    try:
        entry = _build_entry(
            action=action, target=target, details=details, result=result,
            module=module, ip_address=ip_address, auth_source=auth_source,
            user_agent=user_agent, session_id=session_id,
            before_values=before_values, after_values=after_values,
        )
        db.session.add(entry)
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit.log_action failed (action=%s): %s", action, exc)


def commit_audit(
    action: str,
    target: str | None = None,
    details: str | None = None,
    result: str = "success",
    module: str | None = None,
    ip_address: str | None = None,
    auth_source: str | None = None,
    user_agent: str | None = None,
    session_id: str | None = None,
    before_values: str | None = None,
    after_values: str | None = None,
) -> None:
    """Add an AuditLog row and **immediately commit** it.

    Use when the main write has already been committed by a lower layer
    (e.g. settings queries.py functions that commit internally).
    """
    try:
        entry = _build_entry(
            action=action, target=target, details=details, result=result,
            module=module, ip_address=ip_address, auth_source=auth_source,
            user_agent=user_agent, session_id=session_id,
            before_values=before_values, after_values=after_values,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.warning("audit.commit_audit failed (action=%s): %s", action, exc)

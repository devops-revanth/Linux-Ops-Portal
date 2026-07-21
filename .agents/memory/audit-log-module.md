---
name: Audit log module
description: Architecture of the dedicated Audit Logs blueprint and extended AuditLog model.
---

## Rule
Audit log lives at `/audit` (blueprint name "audit"). The settings page no longer has a Change Log card — all audit browsing goes through the dedicated page.

## AuditLog extended columns (migration d8e3f921a047)
module, ip_address, auth_source, result (success/failed), user_agent, session_id, before_values, after_values. Migration head order: …audit_logs → add_freeipa_columns → add_extended_audit_log_columns → add_directory_services_tables.

## audit.py helpers auto-capture
`log_action()` and `commit_audit()` call `_request_context()` which reads `request.remote_addr`, `User-Agent`, `session["_id"]`, and `current_user.auth_source` automatically. Callers only need to pass explicit overrides or `result="failed"` / `before_values` / `after_values` when needed.

## Module derivation
`module` is derived from the first dot-segment of `action` (e.g. "inventory.server.add" → "inventory"). Override with `module=` kwarg if needed.

## Auth audit calls
`auth.login` (result=success, auth_source=user.auth_source), `auth.login` (result=failed, target=username), `auth.logout` — all in auth/routes.py.

**Why:** Separating the audit view from settings keeps each page focused; auto-capturing request context reduces call-site boilerplate across 20+ instrumented routes.

**How to apply:** Any new write route should call `log_action(...)` before `db.session.commit()` or `commit_audit(...)` after. Pass `result="failed"` for error paths. The module is auto-derived; no need to pass it unless the action string is ambiguous.

---
name: FreeIPA auth architecture
description: How FreeIPA/LDAP authentication is structured in LOP; login flow, local fallback, role mapping, and LDAP account sentinel.
---

## Rule
FreeIPA is tried first on every login; local password check is the fallback. Local accounts (auth_source="local") always use local passwords regardless of the FreeIPA toggle — this preserves the emergency admin.

## LDAP account sentinel
LDAP user rows store `"!NOLOGIN"` in `password_hash`. `check_password()` returns False for this sentinel so local auth never succeeds for LDAP accounts accidentally. Use `set_unusable_password()` to set it.

## Role mapping (priority order)
`LinuxAdmins → administrator`, `LinuxOperators → operator`, `LinuxReadOnly → readonly`, no match → `operator`. Evaluated in that priority order so a user in multiple groups gets the highest role.

## Auto-upsert
On successful FreeIPA bind, `_try_freeipa_login()` in auth/routes.py creates or updates the local User row, syncing role/display_name/email/last_login. This means LDAP changes (e.g. group membership) propagate on next login without admin intervention.

## Test Connection endpoint
`POST /settings/freeipa/test` — AJAX, returns JSON `{success, message, server, base_dn}`. Logs to audit trail.

**Why:** Never store LDAP passwords; keep one guaranteed-local admin; sync role on login so LDAP is the source of truth for roles.

**How to apply:** Any new auth-related route should still use `current_user` from Flask-Login. FreeIPAService is instantiated per-request from `current_app.config`.

---
name: User model extensions
description: Columns added to the users table for FreeIPA support; migration chain.
---

## Rule
The users table has four additional columns beyond the original schema: `role`, `auth_source`, `display_name`, `last_login`. Migration chain: initial → add_users → add_api_tokens → add_reboot_required → add_audit_logs → **add_freeipa_columns (c4f7a812b3e9)**.

**Why:** FreeIPA auth requires role (replaces any future ACL system), auth_source (distinguishes local vs LDAP rows), display_name (from LDAP cn), last_login (audit/UX).

**How to apply:** Any query filtering by role or auth_source is safe after this migration. Seeder sets role="administrator", auth_source="local" on the admin seed row. VALID_ROLES = ("administrator", "operator", "readonly").

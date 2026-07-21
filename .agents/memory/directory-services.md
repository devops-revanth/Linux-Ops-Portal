---
name: Directory Services — LDAP authentication config
description: How LDAP/AD/FreeIPA/OpenLDAP config is stored, encrypted, and consumed.
---

## Rule
All directory config lives in the `directory_config` table (singleton row) — NOT env vars.
Bind password is encrypted with Fernet (app/encryption.py) keyed from SECRET_KEY via SHA-256.
Group mappings live in `ldap_group_mappings` table — configurable through Settings UI, not hardcoded.

## Migration chain
d8e3f921a047 → e1f4b8c92a3d (adds directory_config + ldap_group_mappings)

## Key classes
- `DirectoryConfig` (app/models/directory_config.py) — singleton; use `get()` or `get_or_create()`
- `LdapGroupMapping` (app/models/ldap_group_mapping.py) — many rows, one per group-to-role mapping
- `FreeIPAService.from_db()` — preferred constructor; reads from DB; falls back to env vars if no record
- `FreeIPAService(app_config)` — legacy constructor; reads FREEIPA_* env vars only (kept for compat)

## Encryption
`app/encryption.py`: `encrypt_value(plaintext)` / `decrypt_value(ciphertext)`.
Key = SHA-256(SECRET_KEY) base64-url-encoded → Fernet AES-128-CBC+HMAC.
If SECRET_KEY changes, stored bind passwords become unreadable — warn users before key rotation.

## Role mapping
`_map_role()` in freeipa.py matches memberOf DNs and CN components against LdapGroupMapping rows.
Priority: administrator(0) > operator(1) > readonly(2). Default role = DirectoryConfig.default_role.

## Settings page
Settings → Directory Services: full config form + group mapping table + Test Connection + Enable/Disable.
Settings does NOT contain User Accounts — those live in /users (users blueprint).

**Why:** DB-stored config allows runtime changes without restarting; encryption avoids plaintext secrets in env.

**How to apply:** To read directory config in code, call `FreeIPAService.from_db()` — never instantiate with `app_config` for new code.

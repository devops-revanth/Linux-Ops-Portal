---
name: Sprint 2 enterprise redesign (extended)
description: All UI changes made in sprint 2, including packages, patching, server detail tabs, compliance config
---

## Summary
Sprint 2 extended all major pages to the new enterprise design language.

## Key decisions

### Packages tab on server detail — 2 tabs only
- **Available Updates** (default) and **Recently Installed** — "Installed Packages" tab removed.
- Route default `pkg_tab` changed from `installed` to `available-updates`.
- Available updates filtered via `ServerPackage.update_available == True`.

### Patching page column set
Hostname (FQDN below) | Environment | Location | OS | Running Kernel | Updates Available (YES/NO badge) | Compliance | Last Patched
- Reboot column removed.
- Compliance status computed from `Patching.compliance_status` property (reads ComplianceConfig from DB via flask.g cache).

### Packages (fleet) page
- Stat cards: Servers Managed, Available Updates, Security Updates, Kernel Updates (no "Installed Packages" card).
- Per-server table: Hostname (link → inventory/packages tab), Updates Available, Security Updates, Compliance, Last Inventory.

### ComplianceConfig — DB singleton
- Table: `compliance_config` (id, compliance_window_days, due_soon_days, updated_at).
- `ComplianceConfig.get()` creates the row with defaults (90/15) if missing.
- `Patching.compliance_status` property reads thresholds via `_get_compliance_thresholds()` which caches to `flask.g._compliance_thresholds` per request.

### Settings → Patch Compliance section
- id="patch-compliance" anchor in settings/index.html
- Route: POST /settings/compliance/save → `settings.save_compliance_route`
- Clamps: window 1–3650 days, due_soon 1–365 days.

### Demo seeder — 3 RHEL servers
- web-prod-01 (USEG, Prod): Compliant, 0 updates, 5 recently installed
- db-prod-01 (UKDL, Prod): Overdue, 8 pending updates with update metadata
- jump-test-01 (DEFR, Stage): Due Soon, 3 pending updates
- All use realistic RHEL package names: openssl, kernel, sudo, bash, NetworkManager, chrony, dnf, etc.

### Migration
- Revision: b2c3d4e5f6a7 (down_revision: f3a2c1d8e049)
- Adds: compliance_config table + 4 columns to server_packages (update_available, available_version, update_type, repository)
- Index: ix_server_packages_update_available
- NOTE: a1b2c3d4e5f6 is already taken by the API tokens migration — never reuse it.

**Why:** All thresholds stored in DB so admins can change compliance windows at runtime via Settings without app restart.

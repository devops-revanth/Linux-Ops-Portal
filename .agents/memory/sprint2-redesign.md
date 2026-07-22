---
name: Sprint 2 Enterprise Redesign
description: Architecture of the Packages fleet dashboard, Patch Compliance redesign, and server detail packages tab.
---

## Packages Page (/packages)
- Is now a **fleet dashboard**, not a per-package list.
- Top row: 5 stat cards (Servers Managed, Installed Packages, Available Updates, Security Updates, Kernel Updates).
- Security Updates and Kernel Updates are `None` in the model → display "Not Available".
- Table shows one row per server: hostname → `/inventory/{id}?tab=packages` (Inventory > Packages tab).
- Row tuple from `get_servers_package_summary()` is `(Server, Patching|None, pkg_count|None)`.
- Compliance column uses `p.compliance_status if p else 'unknown'`.

## Patch Compliance Page (/patching)
- Added 4 compliance summary cards (Compliant / Due Soon / Overdue / Unknown) at the top.
- Cards computed by `get_compliance_summary()` in `patching/queries.py` using SQL CASE expression.
- Table simplified to 6 columns: Checkbox | Hostname (+ env pill + FQDN) | Updates | Last Patched | **Compliance** | Reboot.
- Removed: Environment, Location, OS, Current Kernel, Latest Avail. Kernel, Last Reboot columns.
- Empty state colspan: 6 (was 12).
- Compliance window: **90 days** (changed from 30 in `Patching.compliance_status` property).

## Server Detail — Packages Tab (/inventory/{id}?tab=packages)
- Redesigned to use **server-side pagination** with `pkg_data` dict passed from route.
- Route: `app/blueprints/inventory/routes.py` — `server_detail()` now reads `pkg_tab`, `pkg_q`, `pkg_page`, `pkg_per_page` from query args.
- `pkg_data` keys: `tab`, `q`, `page`, `per_page`, `total`, `total_pages`, `rows`.
- `rows` is list of `(ServerPackage, Package)` tuples.
- Sub-tabs: Installed Packages (sort by name) | Recently Installed (sort by collected_at DESC) | Available Updates (disabled/N/A — no per-package update data in model).
- Columns: Package | Version | Release (N/A) | Architecture (N/A) | Repository (N/A) | Collected date.
- Per-page options: 10, 25, 50, 100.

## Server Detail — Header Meta-row
- "IP Address" → "Management IP".
- "RAM" → "Memory".
- CPU Model removed; CPU shows count only ("N vCPU").
- Added: Disk (always "Not Available"), Last Inventory (last_ansible_sync), Last Check-In (last_ansible_sync), Last Patch (patching.last_patch_date).
- FQDN always shown (removed `if fqdn != hostname` guard).

## Data Model Gaps (for Sprint 3)
- Security updates, kernel updates: not in model — need Ansible collection extension.
- Release, Architecture, Repository per package: not in ServerPackage model.
- Per-package update detail (available version, update type): not in model.
- Disk capacity: not in Server model.

**Why compliance window is 90 days:** User explicitly specified 90-day window replacing the earlier 30-day Sprint 1 default.

---
name: Sprint 1 UI Polish
description: What was built in Sprint 1 and key decisions to stay consistent with.
---

## What was delivered

### Packages blueprint (`app/blueprints/packages/`)
- Route: `GET /packages?tab=installed|updates|recently-installed&q=&sort=&order=&page=&per_page=`
- Blueprint protected by `blueprint.before_request(login_required(lambda: None))` — same pattern as inventory/patching.
- Three tabs served server-side (one query per request, not all three loaded).
- "Available Updates" tab queries `Patching.pending_updates > 0` — only server-level counts, no per-package update rows (those require Ansible collection).
- Columns with no DB backing (Release, Repository, Architecture, Disk) always display "Not Available".

### Compliance model (`app/models/patching.py`)
- `Patching.compliance_status` property returns `'compliant' | 'due_soon' | 'overdue' | 'unknown'`.
- Window: 30 days from `last_patch_date`. `pending_updates == 0` → compliant. `pending_updates IS NULL` → unknown.
- **Why:** compliance is computed at render time in Python, not in SQL — no new DB column needed; filtering by compliance requires Python-side filtering if ever added.

### Per-page selector
- Both inventory (`inv.per_page`) and patching (`pt.per_page`) routes now accept `?per_page=` param.
- Valid values: `{10, 20, 25, 50, 100}`. Default: `ITEMS_PER_PAGE` config (currently 25).
- `per_page` is threaded through all sort-link and pagination `url_for()` calls in the templates.

### Timezone display
- Global JS snippet in `base.html` (before `{% block extra_scripts %}`): converts all `[data-utc]` elements to browser local time.
- Usage: `<span data-utc="{{ dt.isoformat() }}">{{ dt.strftime('%Y-%m-%d') }}</span>`

### Inventory column changes
- "IP Address" header → "Management IP"
- "RAM" header → "Memory"
- New "Disk" column after Memory — always shows "Not Available" (no `disk_gb` model field; would need a migration to populate).
- FQDN now always shows below hostname (removed `if fqdn != hostname` guard).
- Empty state colspan: 11 (was 10 before Disk column was added).

### Nav / naming
- Sidebar: Packages added between Inventory and Patch Compliance.
- "Patching" renamed to "Patch Compliance" in sidebar span, breadcrumb, and page title.

## Sprint 2 recommendations
- Add `disk_gb` / `disk_total_gb` to the `Server` model (migration) and Ansible collection playbook so the Disk column can show real data.
- Add per-package update rows to the data model (e.g. `ServerPackageUpdate` table) so the Available Updates tab can show package-level detail.
- Add compliance filter to the Patch Compliance page (requires Python-side filtering or a computed column in the query).
- Add FQDN to the server detail page header.
- Consider adding `last_sync_date` to server list with timezone display.

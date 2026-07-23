---
name: Stabilization pass fixes
description: Issues found and fixed during the v1.0 stabilization pass on main branch.
---

## Health endpoint false-503

`os.statvfs()` on Replit containers returns non-zero `f_blocks` but tiny values
that round to 0.0 GB. The old code checked only `f_blocks == 0` for the
"unavailable" guard, so `disk_free_gb < 1` triggered "critical" and the
`overall` became "degraded" → HTTP 503.

**Fix:** added a second guard `if disk_total_gb < 0.1` immediately after
computing values — treat as "unavailable" without touching `overall`.
`/health` now returns 200 with `"status": "ok"` in the dev environment.

## N+1 queries fixed

All outerjoin queries that returned Server objects were missing `contains_eager`
(or `joinedload`), so every row triggered per-object lazy-loads for
environment/location/owner/patching.

Files fixed:
- `app/blueprints/reports/queries.py` — `_base_server_query`, `_patch_compliance_query`, `_sync_report_query`
- `app/blueprints/packages/queries.py` — `get_fleet_page` (patching excluded — it's a tuple query)
- `app/blueprints/search/queries.py` — `_base_q` (import was already present but unused)
- `app/blueprints/ops/routes.py` — `api_hosts` (used `joinedload`, not `contains_eager`, because it's a legacy `Model.query` call)

**Why:** `contains_eager` only works when joined via `db.session.query(...).outerjoin(...)`;
`joinedload` works with the `Model.query` shorthand.

## Mobile sidebar

On screens < 768px the sidebar was `display: none !important` with no way to
show it. Added:
- `#sidebarToggle` button in navbar (`d-md-none`)
- CSS: sidebar as `position: fixed` slide-in overlay (`translateX(-110%)` →
  `translateX(0)`) triggered by class `lop-sidebar-open`
- CSS: `.lop-sidebar-backdrop` overlay to dismiss on tap
- JS in `lop.js`: IIFE that wires toggle button + backdrop close + nav-link close

## Admin password

Reset to `Admin1234!` via Flask shell (`user.set_password(...)`) — committed
to main, pushed to origin.

---
name: Phase 4 Multi-vCenter support
description: Durable decisions and operational lessons for multi-vCenter VMware support replacing the singleton VmwareConfig.
---

## VmwareConfig kept as deprecated shim — never drop it
The old singleton `VmwareConfig` table was intentionally kept to preserve existing migrations and imports.
New code exclusively uses `VmwareConnection` (one row per vCenter).

**Why:** Dropping the table breaks every Alembic migration that references it.
**How to apply:** All new VMware feature code imports from `app/models/vmware_connection.py`. `VmwareSyncLog` lives in `vmware_config.py` but now carries a `connection_id` FK.

## Module imports inside services must use relative parent paths
The `sync_connection()` and `sync_all_connections()` functions in `app/services/vmware_service.py`
import `VmwareConnection` inside the function body with `from ..models.vmware_connection import VmwareConnection`.
Using `from .vmware_connection import ...` (same-package) raises `ModuleNotFoundError` at runtime inside APScheduler.

**Why:** The `services/` package has no `vmware_connection` module; the model lives in `models/`.
**How to apply:** Any service function that defers a model import must use `..models.<module>` not `.<module>`.

## Per-connection APScheduler jobs — naming convention
Each enabled `VmwareConnection` gets a job named `vmware_conn_<id>`.
`reschedule_vmware_connections(app)` removes ALL `vmware_conn_*` jobs then re-adds from DB.
The old `reschedule(app, schedule)` is a backward-compat alias that delegates to `reschedule_vmware_connections`.

**Why:** A single global job cannot drive independent schedules per connection.
**How to apply:** After any create/edit/delete/toggle of a VmwareConnection, call `reschedule_vmware_connections(app)`.

## Stale handling is scoped to the current connection AND other connections
A VM is only marked inactive when: absent from the current sync AND its UUID is absent from ALL other connections' `vmware_server_meta` rows. This prevents false-inactive when the same VM is managed by two vCenters.

## location_id is nullable at DB level, required at form level
The `vmware_connections.location_id` column allows NULL in the database to support backward-compat migration (old `vmware_config` may have had no location set). The application form enforces it as required.

## Dashboard vmware_sync_status string changed
Previously `"Completed"` / `"Failed"` / `"Disabled"`.
Now `"N/M Connected"` (e.g. `"3/4 Connected"`) / `"Disconnected"` / `"Disabled"` / `"Not Configured"`.
Any template checking for the old `== 'Completed'` pattern must use `in status` instead.

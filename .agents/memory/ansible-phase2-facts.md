---
name: Ansible Phase 2 – Live Fact Collection
description: Architecture, key decisions, and gotchas for the Ansible fact collection engine (Phase 2).
---

## What was built
- `app/models/ansible_facts.py` — AnsibleFilesystem, AnsibleServerService, AnsibleRepository, AnsibleSyncJob models
- `app/services/ansible_fact_service.py` — `collect_facts(cfg, app, triggered_by)` main entry point
- `migrations/versions/g7h8i9j0k1l2_add_ansible_facts_tables.py` — adds 11 columns to linux_servers, 6 to ansible_config, 4 new tables
- `app/blueprints/ansible/routes.py` — POST /settings/ansible/collect, GET /settings/ansible/collect-status, POST /settings/ansible/reschedule
- `app/scheduler.py` — added `reschedule_ansible()`, `_add_ansible_job()`, `_run_scheduled_ansible_facts()` alongside existing VMware scheduler
- Dashboard queries: `OsDistributionCount` dataclass, live `ansible_synced_servers`, `ansible_packages_total`, `os_distribution` stats

## Architecture: --tree collection
- One SSH session, run each ansible module with `--tree /tmp/lop_XXXX/<module>/`
- Files read back in batches of 50 hosts via a single SSH exec (printf markers trick)
- Temp dir cleaned up in finally block
- `_q()` helper imported from `ansible_service` — provides shell-safe single-quoting

## Critical gotchas
- `Patching` model does NOT have `last_ansible_sync` — do not add it; only update `pending_updates`
- Dashboard queries.py imports `Server` at module level — do not re-import it inside inner try blocks (causes UnboundLocalError via Python scoping)
- Migration's `op.create_table` with `index=True` on a column already creates the index — calling `op.create_index` again causes DuplicateTable error; never double-create
- `_fact_collection_running` is a `threading.Lock()` used as a run-guard; `acquire(blocking=False)` for non-blocking check
- `log_action` vs `commit_audit`: both exist; `log_action` is a lighter helper that doesn't commit; `commit_audit` commits immediately

## Data ownership (never cross)
- Ansible: architecture, swap_gb, timezone, selinux_status, uptime_seconds, boot_time, default_gateway, dns_servers, primary_interface, mac_address, virtualization_type, operating_system, os_version, kernel_version, cpu_count, cpu_model, ram_gb, ip_address
- VMware: vmware_vm_uuid, datacenter, cluster, esxi_host (in VmwareServerMeta)
- LOP: environment, location, owner, status, compliance, notes

## Why bulk update matters
Server facts can be 500MB+ of JSON for large inventories. Key scale decisions:
- Pre-load server map and package map in single queries
- Delete old child rows, bulk insert new ones
- Never do per-host DB roundtrips

**Why:** Without bulk operations, a 200-server inventory with 300 packages each = 60,000+ individual INSERT statements, causing 30-60 second fact collection runs.

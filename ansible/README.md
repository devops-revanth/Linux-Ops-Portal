# Ansible Integration — Linux Operations Portal

Pushes comprehensive server inventory facts from the Ansible Control Node to the
LOP REST API. **No SSH from the portal to any server** — Ansible initiates all
connections outbound from the control node.

## Workflow

```
Linux Server
      │  (SSH from Ansible Control Node)
      ▼
Gather Facts  +  Run check-update / needs-restarting
      │
      ▼
inventory_sync.yml  (hostname parsing, fact aggregation)
      │  POST /api/v1/inventory  +  Bearer token
      ▼
Linux Operations Portal REST API
      │
      ▼
PostgreSQL  →  Dashboard / Inventory / Patching update automatically
```

## Prerequisites

* Ansible ≥ 2.12
* `dnf-utils` / `yum-utils` on target RHEL/Rocky servers (for `needs-restarting`)
* Network access from the Ansible Control Node to the LOP URL
* An active API token (generated in **Settings → API Settings**)

## Quick Start

```bash
# 1. Copy and edit group vars
cp ansible/group_vars/all.yml.example ansible/group_vars/all.yml
# Fill in lop_api_url and lop_api_token

# 2. Edit inventory
cp ansible/inventory.ini.example ansible/inventory.ini
# Replace example hostnames with real servers

# 3. Run the playbook
ansible-playbook -i ansible/inventory.ini ansible/inventory_sync.yml

# 4. Run against a single host to test
ansible-playbook -i ansible/inventory.ini ansible/inventory_sync.yml --limit usegnbxlp001.example.com

# 5. Dry-run (check mode — skips the URI push)
ansible-playbook -i ansible/inventory.ini ansible/inventory_sync.yml --check
```

## Hostname Convention

The playbook automatically parses server names following this format:

```
u  s  e  g  n  b  x  l  p  0  0  1
│──────┘  │──┘  │           │
Site(4)   App(3) OS(1)      Env(1)   Sequence
```

| Position | Length | Description | Examples |
|----------|--------|-------------|---------|
| 0–3      | 4      | Site code (uppercase) | `useg` → USEG, `defr` → DEFR, `ukdl` → UKDL |
| 4–6      | 3      | Application code (uppercase) | `nbx` → NBX, `sap` → SAP, `ecc` → ECC |
| 7        | 1      | OS identifier | `L` = Rocky Linux, `R` = Red Hat Enterprise Linux |
| 8        | 1      | Environment | `P` = Production, `S` = Stage, `T` = Test, `D` = Development, `E` = Demo |
| 9+       | varies | Sequence number | `001`, `002`, … |

**Hostname example:** `usegnbxlp001`
- Site: `USEG`
- App: `NBX`
- OS: Rocky Linux
- Environment: Production

**Parsing happens entirely in Ansible** — the portal stores the results as received. Hostnames that do not follow the convention fall back to the `lop_location` and `lop_environment` inventory variables.

## Variables

### Required (group_vars/all.yml)

| Variable | Description |
|----------|-------------|
| `lop_api_url` | Base URL of the portal, e.g. `https://lop.example.com` |
| `lop_api_token` | Bearer token generated in LOP Settings → API Settings |

### Optional per-host / per-group

| Variable | Default | Description |
|----------|---------|-------------|
| `lop_location` | `""` | Location fallback for non-standard hostnames |
| `lop_environment` | `""` | Environment fallback for non-standard hostnames |
| `lop_owner` | `""` | Owner name (must match a record in LOP) |

## Collected Data

The playbook collects and pushes all of the following:

| Category | Fields |
|----------|--------|
| **Identity** | Hostname, FQDN, Primary IP Address |
| **OS** | Distribution, OS Version, Running Kernel, Installed Kernel, Architecture |
| **Hardware** | CPU Count, CPU Model, RAM (GB) |
| **Disk** | Total (GB), Used (GB), Used % — root filesystem |
| **Swap** | Total (GB), Used (GB) |
| **Runtime** | Uptime (seconds), Last Boot Time |
| **System** | Package Manager, Python Version, Ansible Version, SELinux Status, Timezone |
| **Parsed hostname** | Site, App Code, OS Name, Environment Name |
| **Patching** | Patch Status, Pending Updates, Security Updates, Kernel Update Available, Reboot Required |
| **Timestamps** | Last Inventory Sync |

## Inventory Format

```ini
# Servers following naming convention (auto-classified by hostname)
[production]
usegnbxlp001.example.com   lop_owner="Platform Engineering"
usegnbxlp002.example.com   lop_owner="Platform Engineering"

# Legacy / non-standard hostnames (manual classification required)
[legacy]
web01.example.com   lop_location="USEG"  lop_environment="Production"  lop_owner="Platform Engineering"

[all:vars]
ansible_user=ansible
ansible_become=false
```

## API Reference

### `POST /api/v1/inventory`

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Full payload example:**
```json
{
  "hostname": "usegnbxlp001",
  "fqdn": "usegnbxlp001.example.com",
  "ip_address": "10.10.1.1",
  "operating_system": "Rocky",
  "os_version": "9.4",
  "kernel_version": "5.14.0-427.13.1.el9_4.x86_64",
  "architecture": "x86_64",
  "cpu_count": 8,
  "cpu_model": "Intel(R) Xeon(R) Gold 6248R",
  "ram_gb": 31.28,
  "disk_total_gb": 99.97,
  "disk_used_gb": 12.34,
  "disk_used_pct": 12.3,
  "swap_total_gb": 4.0,
  "swap_used_gb": 0.12,
  "uptime_seconds": 864123,
  "last_boot": "2026-07-11T08:00:00",
  "package_manager": "dnf",
  "python_version": "3.9.18",
  "ansible_version": "2.16.3",
  "selinux_status": "enforcing",
  "timezone_name": "UTC",
  "location": "USEG",
  "environment": "Production",
  "owner": "Platform Engineering",
  "parsed_site": "USEG",
  "parsed_app_code": "NBX",
  "parsed_os_name": "Rocky Linux",
  "parsed_env_name": "Production",
  "patch_status": "pending",
  "pending_updates": 14,
  "security_updates": 3,
  "kernel_update_available": true,
  "installed_kernel": "5.14.0-427.16.1.el9_4.x86_64",
  "reboot_required": false,
  "last_inventory_sync": "2026-07-22T10:00:00Z"
}
```

**Success response (200):**
```json
{
  "status": "success",
  "action": "created",
  "hostname": "usegnbxlp001",
  "message": "Inventory updated"
}
```

| `action` | Meaning |
|---------|---------|
| `created` | New server record was inserted |
| `updated` | Existing server record was updated |

**Error responses:**

| Code | Meaning |
|------|---------|
| 401 | Missing or invalid Bearer token |
| 400 | Malformed JSON or failed field validation |
| 500 | Database error |

## Idempotency

Running the playbook multiple times is safe:
- **New servers** are created automatically on first run.
- **Existing servers** are updated with the latest facts.
- **Duplicate records are never created** — upsert is keyed on `hostname`.
- **Server status** (`active`, `inactive`, `maintenance`, `decommissioned`) set manually in the portal is **never overwritten** by a sync unless `status` is explicitly included in the payload.
- **Patch status** is derived from actual update counts — not from a hardcoded inventory variable.

## Security

```bash
# Encrypt the token file with Ansible Vault (recommended for production)
ansible-vault encrypt ansible/group_vars/all.yml

# Run playbook with vault password prompt
ansible-playbook -i ansible/inventory.ini ansible/inventory_sync.yml --ask-vault-pass

# Or use a vault password file (for CI/CD pipelines)
ansible-playbook -i ansible/inventory.ini ansible/inventory_sync.yml \
  --vault-password-file ~/.vault_pass
```

- The token is a 64-character cryptographically secure hex string.
- Regenerating the token in Settings immediately invalidates the old one.
- The `group_vars/all.yml` file should **never** be committed with a real token.
- Add `ansible/group_vars/all.yml` to `.gitignore` or use Ansible Vault.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Unauthorized` | Wrong or expired token | Regenerate in Settings → API Settings |
| `400 Bad Request` | Invalid field value | Check playbook output for the field name |
| `needs-restarting: command not found` | Package not installed | `dnf install yum-utils` on target |
| `dnf check-update` slow | Metadata refresh | Normal on first run; subsequent runs use cache |
| Server not appearing in portal | Location/Environment name mismatch | Verify names match records in LOP exactly |
| Hostname not parsed | Hostname < 9 chars or non-standard format | Set `lop_location` and `lop_environment` in inventory |

# Ansible Integration — Linux Operations Portal

Pushes server inventory facts from the Ansible Control Node to the
LOP REST API.  **No SSH from the portal to any server.**

## Workflow

```
Linux Server
      │  (SSH from Ansible Control Node)
      ▼
gather.yml         — Ansible facts, package facts, service facts
parse_hostname.yml — Enterprise hostname convention → site / env / OS codes
updates.yml        — Available updates (RHEL dnf / Debian apt)
payload.yml        — Build JSON payload from lop_facts
api.yml            — POST to LOP REST API with retry
      │
      ▼
Linux Operations Portal REST API  (Bearer token)
      │
      ▼
PostgreSQL  →  Dashboard / Inventory / Patching update automatically
```

## Directory Structure

```
ansible/
├── lop_inventory_sync.yml          # Main playbook
├── inventory.ini                   # Example inventory
├── group_vars/
│   └── all.yml                     # Runtime configuration (URL, token, toggles)
└── roles/
    └── lop_inventory_sync/
        ├── tasks/
        │   ├── main.yml            # Imports all task files in order
        │   ├── gather.yml          # Collect system facts
        │   ├── parse_hostname.yml  # Parse enterprise hostname convention
        │   ├── updates.yml         # Collect available package updates
        │   ├── payload.yml         # Build inventory payload
        │   └── api.yml             # Send payload to LOP API
        ├── vars/
        │   └── main.yml            # Static mappings (OS codes, site codes, etc.)
        ├── defaults/
        │   └── main.yml            # Overridable defaults (timeouts, toggles)
        └── meta/
            └── main.yml            # Role metadata and platform support
```

## Prerequisites

* Ansible ≥ 2.12
* Network access from the Ansible Control Node to the LOP URL
* An active API token (generated in **Settings → API Settings**)

## Quick Start

```bash
# 1. Set your portal URL and token in group_vars/all.yml
vi ansible/group_vars/all.yml

# 2. Edit inventory.ini with your server hostnames
vi ansible/inventory.ini

# 3. Run the playbook
ansible-playbook -i ansible/inventory.ini ansible/lop_inventory_sync.yml
```

## Variables

### Required (set in `group_vars/all.yml`)

| Variable | Description |
|---|---|
| `portal_url` | Full inventory endpoint URL, e.g. `http://lop.example.com/api/v1/inventory` |
| `portal_api_token` | Bearer token from LOP Settings → API Settings |

### Optional (defaults in `roles/lop_inventory_sync/defaults/main.yml`)

| Variable | Default | Description |
|---|---|---|
| `portal_validate_certs` | `true` | Set `false` for self-signed certificates |
| `portal_timeout` | `30` | HTTP request timeout in seconds |
| `portal_retry_count` | `3` | Retry attempts on transient failure |
| `portal_retry_delay` | `5` | Seconds between retry attempts |
| `portal_owner` | `""` | Team or person responsible for the server |
| `portal_debug` | `false` | Enable verbose debug output |
| `portal_sync_enabled` | `true` | Master toggle for the sync |

### Per-host (set in `inventory.ini` or `host_vars/`)

| Variable | Description |
|---|---|
| `portal_owner` | Override owner per host or group |

## Hostname Convention

The role parses enterprise hostnames automatically.

```
usegnbxlt001
════╤════╤═╤╤═══
     │    │ ││
     │    │ │└── Sequence  (001)
     │    │ └─── Environment code  (T = Test)
     │    └───── OS code  (L = Rocky Linux)
     └────────── Application code  (NBX)
Site code  (USEG = US Elk Grove)
```

**OS codes** (`vars/main.yml` → `os_map`):

| Code | OS |
|---|---|
| L | Rocky Linux |
| R | Red Hat Enterprise Linux |
| A | AlmaLinux |
| O | Oracle Linux |
| U | Ubuntu |
| D | Debian |

**Environment codes** (`vars/main.yml` → `environment_map`):

| Code | Environment |
|---|---|
| P | Production |
| I | Pre Production |
| T | Test |
| S | Stage |
| D / K / N / X | Development |
| E | Demo |

Add site codes and new mappings to `roles/lop_inventory_sync/vars/main.yml`.

## API Reference

### `POST /api/v1/inventory`

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Core payload fields:**
```json
{
  "hostname": "usegnbxlt001",
  "fqdn": "usegnbxlt001.example.com",
  "ip_address": "10.1.2.3",
  "operating_system": "Rocky",
  "os_version": "9.3",
  "kernel_version": "5.14.0-362.el9.x86_64",
  "cpu_count": 4,
  "cpu_model": "Intel(R) Xeon(R) Gold 6248R",
  "ram_gb": 32.0,
  "location": "USEG",
  "environment": "Test",
  "pending_updates": 12,
  "reboot_required": false,
  "last_inventory_sync": "2026-07-23T10:00:00Z"
}
```

**Success response (200):**
```json
{
  "status": "success",
  "action": "created",
  "hostname": "usegnbxlt001",
  "server_id": 42,
  "message": "Inventory updated"
}
```

**Error responses:**

| Code | Body |
|---|---|
| 401 | `{"status": "error", "message": "Unauthorized"}` |
| 400 | `{"status": "error", "message": "<reason>"}` |
| 500 | `{"status": "error", "message": "Internal server error"}` |

## Security

* Store the API token in **Ansible Vault** for production use.
* The token is a 64-character hex string generated cryptographically.
* Regenerating the token in Settings immediately invalidates the old one.

```bash
# Encrypt the group_vars file
ansible-vault encrypt ansible/group_vars/all.yml

# Run the playbook with vault password
ansible-playbook -i ansible/inventory.ini ansible/lop_inventory_sync.yml \
  --ask-vault-pass
```

## Limiting Scope

```bash
# Sync only the production group
ansible-playbook -i ansible/inventory.ini ansible/lop_inventory_sync.yml \
  --limit production

# Sync a single host
ansible-playbook -i ansible/inventory.ini ansible/lop_inventory_sync.yml \
  --limit usegnbxlt001

# Dry run (check mode — skips the API call)
ansible-playbook -i ansible/inventory.ini ansible/lop_inventory_sync.yml \
  --check
```

# Ansible Integration — Linux Operations Portal

Pushes server inventory facts from the Ansible Control Node to the
LOP REST API.  **No SSH from the portal to any server.**

## Workflow

```
Linux Server
      │  (SSH from Ansible Control Node)
      ▼
Gather Facts  (ansible_hostname, ansible_kernel, etc.)
      │
      ▼
Ansible Playbook  (inventory_sync.yml)
      │  POST /api/v1/inventory  +  Bearer token
      ▼
Linux Operations Portal REST API
      │
      ▼
PostgreSQL  →  Dashboard / Inventory / Patching update automatically
```

## Prerequisites

* Ansible ≥ 2.12
* Network access from the Ansible Control Node to the LOP URL
* An active API token (generated in **Settings → API Settings**)

## Quick Start

1. Copy `inventory/hosts` and edit hostnames and variables.
2. Copy `group_vars/all.yml` and set `lop_api_url` and `lop_api_token`.
3. Run the playbook:

```bash
ansible-playbook -i inventory/hosts inventory_sync.yml
```

## Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `lop_api_url` | Yes | `http://localhost:5000` | Portal base URL |
| `lop_api_token` | Yes | — | Bearer token from LOP Settings |
| `lop_location` | No | `""` | Location name (must match LOP record) |
| `lop_environment` | No | `""` | Environment name (must match LOP record) |
| `lop_owner` | No | `""` | Owner name (must match LOP record) |
| `lop_patch_status` | No | `unknown` | One of: `up-to-date`, `pending`, `failed`, `unknown` |

## API Reference

### `POST /api/v1/inventory`

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Example payload:**
```json
{
  "hostname": "web01",
  "fqdn": "web01.example.com",
  "ip_address": "192.168.1.10",
  "operating_system": "RedHat",
  "os_version": "9.2",
  "kernel_version": "5.14.0-284.el9.x86_64",
  "cpu_count": 4,
  "cpu_model": "Intel(R) Xeon(R) Gold 6248R",
  "ram_gb": 32.0,
  "location": "USEG",
  "environment": "Production",
  "owner": "Platform Engineering",
  "patch_status": "up-to-date",
  "last_patch_date": "2026-07-15T10:00:00Z",
  "last_reboot": "2026-07-20T08:00:00Z",
  "last_inventory_sync": "2026-07-21T12:00:00Z"
}
```

**Success response (200):**
```json
{
  "status": "success",
  "action": "created",
  "hostname": "web01",
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

## Keeping Secrets Safe

```bash
# Encrypt the token file
ansible-vault encrypt group_vars/all.yml

# Run playbook with vault password
ansible-playbook -i inventory/hosts inventory_sync.yml --ask-vault-pass
```

# Ansible Integration

LOP is designed around an **Ansible push model** — the application never
initiates outbound SSH connections to managed servers. Instead, Ansible
playbooks collect server facts and push them to LOP via its REST API.

## Architecture

```
Managed Servers
      │
      │  (Ansible SSH)
      ▼
Ansible Control Node
      │
      │  HTTP POST — facts, patch status, package versions
      ▼
LOP REST API  (to be implemented — see docs/API.md)
      │
      ▼
PostgreSQL Database
```

## Planned Playbooks

| Playbook | Purpose |
|----------|---------|
| `collect_facts.yml` | Gather hostname, IP, OS, kernel, CPU, RAM |
| `collect_packages.yml` | Collect installed package versions (Docker, Python, Java, OpenSSL) |
| `collect_patching.yml` | Collect patch status, last patch date, last reboot date |
| `sync_inventory.yml` | Full inventory sync — runs all collectors in order |

## Fields Collected by Ansible

**Automated (Ansible pushes):**
- Hostname, IP address, FQDN
- Operating system name and version
- Kernel version
- CPU count and model
- RAM (GB)
- Installed package versions
- Patch status, last patch date, last reboot date

**Manual (set in LOP portal):**
- Owner assignment
- Server notes
- Status (active / inactive / maintenance / decommissioned)

## Prerequisites

- Ansible 2.14+
- LOP REST API implemented (see `docs/API.md` and `docs/ROADMAP.md`)
- API key provisioned in LOP Settings

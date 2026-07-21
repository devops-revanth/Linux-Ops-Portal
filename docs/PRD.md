# Product Requirements Document — Linux Operations Portal (LOP)

**Version:** 1.0  
**Status:** Active Development  
**Last Updated:** 2024

---

## 1. Problem Statement

Linux infrastructure teams at most organisations manage server inventories in Excel spreadsheets or fragmented wikis. These approaches are:

- **Out of date** — manual updates lag behind reality
- **Inaccessible** — locked in a single person's file share
- **Error-prone** — no validation, no audit trail
- **Disconnected** — patch status, package versions, and ownership live in separate places

LOP replaces this with a centralised, automatically-updated portal.

---

## 2. Goals

| Goal | Metric |
|------|--------|
| Single source of truth for Linux server inventory | 100% of managed servers registered in LOP |
| Automated data collection via Ansible (no SSH from LOP) | Zero manual data entry for Ansible-collected fields |
| Patch status visibility for all servers | Dashboard shows up-to-date vs pending vs failed |
| Operations team self-service | Add/edit/delete servers without admin intervention |

---

## 3. Non-Goals

- LOP does not perform configuration management (Ansible does that)
- LOP does not initiate SSH connections to servers
- LOP is not a general CMDB — scope is Linux servers only
- LOP does not manage Windows servers

---

## 4. Users

| Persona | Role | Primary Use |
|---------|------|-------------|
| Linux SRE / SysAdmin | Day-to-day operator | Check server status, update notes, view patch state |
| Operations Manager | Oversight | Dashboard overview, environment breakdowns |
| Ansible Engineer | Automation | Push facts via REST API; design playbooks |
| Platform Architect | Architecture | Settings management, Ansible API integration |

---

## 5. Core Modules

### 5.1 Foundation ✅
Flask application factory, PostgreSQL, Alembic migrations, Bootstrap 5 dark theme, CSRF protection.

### 5.2 Dashboard ✅
Real-time statistics: total servers, active/inactive counts, environment breakdown (cards with server counts per tier), location summary, patch status ring. Auto-refreshes every 60 seconds.

### 5.3 Inventory ✅
Server list with search (hostname, IP, owner), filters (environment, location, status), multi-column sort, pagination. Full CRUD: Add Server form, Edit Server modal, Delete confirmation. Server count badge per filter.

### 5.4 Server Details ✅
Tabbed detail view per server: Overview (identity + status), Hardware (CPU, RAM, OS), Patching (status, kernel, dates), Packages (installed versions), Notes (free-text log with author + timestamp). Edit and Delete from detail page.

### 5.5 Settings ✅
Full CRUD management of master data via Bootstrap 5 modals:
- **Locations** — data-centre codes (e.g. USEG, UKDL)
- **Environments** — deployment tiers (Production, Stage, Dev, Demo) with colour badges
- **Owners** — responsible teams/individuals with email
- Deletion blocked when records are referenced by servers

### 5.6 Patching ⏳ Planned
Dedicated patching dashboard: filter by status (up-to-date / pending / failed / unknown), kernel version history per server, last reboot date, overdue patch alerts.

### 5.7 Reports ⏳ Planned
Exportable reports: patch compliance by environment, server age by owner, stale inventory (no Ansible sync in N days).

### 5.8 Ansible REST API ⏳ Planned
Inbound push API for Ansible playbooks. API key authentication. Endpoints for server upsert, patch status update, package version sync.

---

## 6. Technical Constraints

- Python 3.12+, Flask 3.1, PostgreSQL 16
- No external dependencies beyond `requirements.txt`
- CSRF protection on all state-changing forms
- Ansible push model — LOP never initiates outbound connections to servers
- Bootstrap 5 dark theme throughout
- All DB logic in `queries.py`; routes stay thin

---

## 7. Acceptance Criteria

- All existing modules pass manual smoke tests after each change
- New modules follow the existing blueprint pattern (queries.py + routes.py + templates)
- Deleting a referenced Location/Environment/Owner is blocked with a user-friendly message
- Dashboard statistics update within one page load of any inventory change

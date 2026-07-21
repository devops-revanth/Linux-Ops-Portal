# Roadmap — Linux Operations Portal

---

## Completed ✅

### Foundation
- Flask 3.1 application factory
- PostgreSQL 16 + Flask-SQLAlchemy + Alembic migrations
- Bootstrap 5.3 dark theme + sidebar navigation
- CSRF protection (Flask-WTF)
- Rotating file logging
- Docker + Docker Compose setup
- Health check endpoint

### Dashboard
- Real-time server statistics (total, active, inactive, maintenance, decommissioned)
- Environment breakdown cards (count per tier with colour coding)
- Location summary table
- Patch status overview
- Auto-refresh (60-second interval)

### Inventory
- Server list with search (hostname, IP, owner name)
- Multi-field filters: environment, location, status
- Multi-column sort with nulls-last handling
- Pagination (configurable page size)
- Add Server (Bootstrap modal form)
- Edit Server (full field edit from detail page)
- Delete Server (with confirmation)

### Server Details
- Tabbed detail view: Overview, Hardware, Patching, Packages, Notes
- Edit and Delete from detail page
- Notes: add with author attribution, delete individual notes

### Settings
- Locations CRUD (Add / Edit / Delete, Bootstrap 5 modals)
- Environments CRUD (Add / Edit / Delete, colour badge selection)
- Owners CRUD (Add / Edit / Delete, email field)
- Deletion blocked when records are referenced by servers
- Duplicate name validation
- Active/Inactive status toggle

---

## In Progress / Next 🔜

### Patching Module
- Dedicated `/patching` route
- Filterable table by patch status (up-to-date / pending / failed / unknown)
- Overdue patch alerts (no update in N days)
- Kernel version history per server
- Reboot date tracking
- Manual patch status update from portal
- Dashboard integration (stats auto-update)

---

## Planned ⏳

### Ansible REST API
- `POST /api/v1/servers/sync` — upsert server facts
- `POST /api/v1/servers/<hostname>/patching` — update patch status
- `POST /api/v1/servers/<hostname>/packages` — sync package versions
- API key authentication and management in Settings
- Ansible playbook templates in `ansible/`

### Reports Module
- Patch compliance report by environment (% up-to-date)
- Server inventory export (CSV / JSON)
- Stale inventory report (no Ansible sync in N days)
- Owner summary (server count per owner)

### Search Module
- Global full-text search across all fields
- Search within notes
- Quick-jump by hostname or IP

### Audit Log
- Record who changed what and when
- Visible from server detail page
- Filterable by user, action type, date range

### Authentication
- Optional: integrate with LDAP / Active Directory
- Role-based access (read-only vs operator vs admin)
- API key management for Ansible integration

### Notifications
- Email alerts for patch compliance thresholds
- Webhook support for Slack / Teams
- Configurable alert rules

---

## Backlog 📋

- Bulk import servers via CSV upload
- Server grouping / tagging
- Custom fields per server
- Mobile-responsive improvements
- Dark/light theme toggle
- Keyboard shortcuts for power users
- Ansible inventory file export (dynamic inventory)

# Linux Operations Portal (LOP)

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Status](https://img.shields.io/badge/status-Production%20Ready-brightgreen)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**Release:** v1.0.0 — Production Ready

Enterprise web application for Linux Infrastructure Operations teams.

Linux Operations Portal (LOP) replaces Excel-based server inventories with a centralized platform for Linux server inventory, patch management, automation integration, reporting, and infrastructure operations.

---

## Features

- 📊 **Dashboard** — live stats: servers, patching compliance, VMware, Ansible
- 🖥️ **Inventory Management** — multi-source server inventory with filters, search, and pagination
- 📄 **Server Details** — per-server overview, packages, patching, notes, and VMware/Ansible metadata
- ⚙️ **Settings** — LDAP/FreeIPA auth, VMware vCenter sync, Ansible control node, regional settings
- 🛡️ **Patching & Compliance** — patch status tracking and compliance policy configuration
- 🔍 **Global Search** — cross-module instant search
- 📈 **Reports & Export** — CSV and Excel export
- 🔗 **VMware vCenter Integration** — automated VM discovery and inventory sync via pyVmomi
- 🔗 **Ansible Integration** — SSH connection to an existing Ansible control node; inventory validation and playbook discovery
- 🔐 **Authentication** — local users with bcrypt passwords; optional LDAP/FreeIPA SSO
- 👥 **User Management** — role-based access (admin, operator, viewer)
- 🔒 **Encryption** — Fernet-encrypted secrets at rest (LDAP, VMware, Ansible credentials)
- 📋 **Audit Log** — structured audit trail for all configuration and inventory changes
- ⏱️ **Scheduler** — APScheduler (embedded) for automatic VMware inventory sync

---

## Technology Stack

| Layer | Technology |
|--------|------------|
| Backend | Flask 3.1 |
| Database | PostgreSQL 14+ |
| ORM | SQLAlchemy + Flask-SQLAlchemy |
| Migrations | Alembic (Flask-Migrate) |
| Frontend | Bootstrap 5, Jinja2 |
| Security | Flask-WTF, CSRF protection, Flask-Login |
| Encryption | Python `cryptography` (Fernet) |
| VMware | pyVmomi (vSphere API) |
| Ansible | paramiko (SSH to external control node) |
| Scheduler | APScheduler (embedded, in-process) |
| LDAP/SSO | ldap3 |
| Production | gunicorn |

> **Note:** LOP connects to an **existing** Ansible control node via SSH.  
> LOP does **not** install Ansible, AWX, or any Automation Controller.  
> The control node is managed independently by your operations team.

---

## Installation

### Fresh Install (Rocky Linux 9 / RHEL 9 / AlmaLinux 9 / Ubuntu 22.04)

```bash
git clone https://github.com/devops-revanth/Linux-Ops-Portal.git
cd Linux-Ops-Portal
sudo ./scripts/install.sh
```

### Update

```bash
sudo lop update
```

### Service Management

Day-to-day service operations are handled by `scripts/service.sh`:

```bash
sudo ./scripts/service.sh start    # Start PostgreSQL → lop-backend → nginx
sudo ./scripts/service.sh stop     # Stop lop-backend and nginx gracefully
sudo ./scripts/service.sh restart  # Restart services; verify both active
sudo ./scripts/service.sh reload   # Reload nginx config; reload systemd daemon
sudo ./scripts/service.sh status   # Concise status summary
sudo ./scripts/service.sh health   # HTTP health checks (nginx + app endpoint)
sudo ./scripts/service.sh logs     # Last 50 log lines from lop-backend + nginx
```

**`status` output example:**

```
 LOP Service Status
─────────────────────────────────────
  LOP Backend :        running
  nginx :              running
  PostgreSQL :         running
─────────────────────────────────────
  Health :             OK
```

**`health` output example:**

```
[STEP] Probing http://localhost/ (nginx → lop-backend)...
[OK]   http://localhost/              HTTP 200   [PASS]
[STEP] Probing http://localhost/health (application)...
[OK]   http://localhost/health        HTTP 200   [PASS]

[OK]   Health check: PASS
```

### Management CLI

```bash
sudo lop health          # health report
sudo lop backup          # create a backup
sudo lop restore <file>  # restore from a backup archive
sudo lop repair          # re-apply venv, dependencies, and service unit
sudo lop diagnostics     # generate troubleshooting bundle
sudo lop status          # service status
sudo lop restart         # restart the backend service
sudo lop logs            # tail application logs
lop version              # show installed version info
```

---

## Module Status

| Module | Status |
|---------|--------|
| Dashboard | ✅ Complete |
| Inventory | ✅ Complete |
| Server Details | ✅ Complete |
| Settings | ✅ Complete |
| Patching & Compliance | ✅ Complete |
| Compliance Policy Configuration | ✅ Complete |
| Global Search | ✅ Complete |
| Reports & Export | ✅ Complete |
| VMware vCenter Integration (Multi-vCenter) | ✅ Complete |
| Ansible Integration — SSH Connection & Inventory | ✅ Complete |
| Ansible Playbook Execution (Ops Workspace) | ✅ Complete |
| LDAP / FreeIPA Authentication | ✅ Complete |
| Audit Log | ✅ Complete |
| User Management | ✅ Complete |
| Encryption at rest | ✅ Complete |
| Background Scheduler | ✅ Complete |
| Lifecycle Management CLI (`lop`) | ✅ Complete |

---

## Documentation

Project documentation is available in the `docs/` directory.

- Installation Guide
- Architecture
- Database Schema
- REST API
- Changelog

---

## License

MIT License

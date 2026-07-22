# Linux Operations Portal (LOP)

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

### Management CLI

```bash
sudo lop health          # health report
sudo lop backup          # create a backup
sudo lop diagnostics     # generate troubleshooting bundle
sudo lop status          # service status
sudo lop logs            # tail application logs
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
| Global Search | ✅ Complete |
| Reports & Export | ✅ Complete |
| VMware vCenter Integration | ✅ Complete |
| Ansible Integration (Foundation) | ✅ Complete |
| LDAP / FreeIPA Authentication | ✅ Complete |
| Audit Log | ✅ Complete |
| User Management | ✅ Complete |
| Encryption at rest | ✅ Complete |
| Background Scheduler | ✅ Complete |

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

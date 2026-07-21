# Linux Operations Portal (LOP)

Enterprise web application for Linux Infrastructure Operations teams.

Linux Operations Portal (LOP) replaces Excel-based server inventories with a centralized platform for Linux server inventory, patch management, automation, reporting, and infrastructure operations.

---

## Features

- 📊 Dashboard
- 🖥️ Inventory Management
- 📄 Server Details
- ⚙️ Settings Management
- 🛡️ Patching & Compliance
- 🔍 Global Search
- 📈 Reports & Export (CSV / Excel)
- 🤖 Ansible Integration (Inventory Sync API)
- 🔐 Authentication & Login
- 👥 User Management
- 🐘 PostgreSQL Backend
- 🐳 Docker Deployment

---

## Technology Stack

| Layer | Technology |
|--------|------------|
| Backend | Flask |
| Database | PostgreSQL |
| ORM | SQLAlchemy |
| Frontend | Bootstrap 5, Jinja2 |
| Migrations | Alembic |
| Security | Flask-WTF, CSRF Protection |
| Automation | Ansible |
| Deployment | Docker & Docker Compose |

---

## Screenshots

- Dashboard
- Inventory
- Server Details
- Patching
- Search
- Reports
- Settings
- Login

*(Screenshots will be updated as development progresses.)*

---

## Quick Start

```bash
git clone https://github.com/devops-revanth/Linux-Ops-Portal.git
cd Linux-Ops-Portal

cp .env.example .env

docker compose up -d

flask db upgrade
```

Open:

```
http://localhost:5000
```

---

## Current Status

| Module | Status |
|---------|--------|
| Dashboard | ✅ Complete |
| Inventory | ✅ Complete |
| Server Details | ✅ Complete |
| Settings | ✅ Complete |
| Patching | ✅ Complete |
| Global Search | ✅ Complete |
| Reports | ✅ Complete |
| Ansible Integration | ✅ Complete |
| Authentication | ✅ Complete |
| User Management | ✅ Complete |

---

## Roadmap

### Next Phase


- ⬜ LDAP / Active Directory Authentication
- ⬜ Audit Logs
- ⬜ Production Monitoring Dashboard

---

## Documentation

Project documentation is available in the `docs/` directory.

- Installation Guide
- Architecture
- Database Schema
- REST API
- Roadmap
- Changelog

---

## License

MIT License

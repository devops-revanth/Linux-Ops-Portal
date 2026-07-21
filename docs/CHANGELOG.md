# Changelog — Linux Operations Portal

All notable changes to this project are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- `docs/` directory with PRD, DATABASE, API, ARCHITECTURE, ROADMAP, and CHANGELOG documents
- `ansible/` placeholder directory with integration architecture notes
- `tests/` directory with planned test structure
- `docker/` directory for supplementary Docker files
- `LICENSE` (MIT)

### Changed
- Project flattened from `lop/` subdirectory to repository root for cleaner structure
- Improved `README.md` with full feature list, architecture overview, and installation guide
- `.gitignore` consolidated — Python + Node patterns unified at root level

### Removed
- `attached_assets/` — chat-pasted text snippets, not application code
- `scripts/src/hello.ts` — unused scaffold placeholder

---

## [1.1.0] — 2024

### Added
- **Settings module — full CRUD** for Locations, Environments, and Owners
  - Bootstrap 5 modal dialogs for Add / Edit / Delete on all three entities
  - Deletion blocked when records are referenced by servers (user-friendly error)
  - Duplicate name validation (case-insensitive) on all entities
  - Active / Inactive status toggle for all entities
  - CSRF protection on all forms
  - All DB logic isolated in `app/blueprints/settings/queries.py`

---

## [1.0.0] — 2024

### Added
- **Foundation** — Flask 3.1 application factory, PostgreSQL 16, Alembic migrations, Bootstrap 5.3 dark theme
- **Dashboard** — live statistics, environment cards, location summary, patch status ring, 60-second auto-refresh
- **Inventory** — server list with search, filters, multi-column sort, pagination; Add / Edit / Delete server
- **Server Details** — tabbed view (Overview, Hardware, Patching, Packages, Notes); add/delete notes
- **Settings** — read-only display of Locations and Environments
- **Health check** — `GET /health` returns `{"status": "ok", "version": "1.0.0"}`
- **Docker** — multi-stage Dockerfile + docker-compose with PostgreSQL service and health checks
- **Seeder** — idempotent reference data (3 locations, 4 environments) on first run

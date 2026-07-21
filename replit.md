# Linux Operations Portal (LOP)

A production-quality internal web application for Linux Infrastructure Operations. Replaces manual Excel-based server inventories with a centralised portal that automatically collects and maintains Linux server inventory and patching information using Ansible — without ever SSHing directly to servers.

## Running the App

The app starts automatically via the **Linux Operations Portal** workflow (`cd lop && python run.py`).

- Dev server: http://localhost:5000
- Health check: http://localhost:5000/health
- Dashboard: http://localhost:5000/dashboard

## Technology Stack

| Layer       | Technology                              |
|-------------|------------------------------------------|
| Backend     | Python 3.12 · Flask 3.1                 |
| ORM         | Flask-SQLAlchemy · Flask-Migrate (Alembic) |
| Database    | Replit PostgreSQL (via DATABASE_URL)    |
| Frontend    | Bootstrap 5.3 · Jinja2 · Bootstrap Icons |
| CSRF        | Flask-WTF                               |

## Project Structure

```
lop/
├── app/
│   ├── __init__.py           # Application factory (create_app)
│   ├── config.py             # Dev/Prod/Testing config classes
│   ├── extensions.py         # db, migrate, csrf singletons
│   ├── seeder.py             # Idempotent reference data seeder
│   ├── models/               # SQLAlchemy models
│   │   ├── server.py         # linux_servers table
│   │   ├── location.py       # locations table
│   │   ├── environment.py    # environments table
│   │   ├── owner.py          # owners table
│   │   ├── patching.py       # patching table
│   │   ├── package.py        # packages + server_packages tables
│   │   └── note.py           # notes table
│   ├── blueprints/
│   │   ├── main/             # Root redirect + /health
│   │   ├── dashboard/        # Live stats, environment & location cards
│   │   ├── inventory/        # Server list, search, filters, CRUD
│   │   └── settings/         # Locations, Environments, Owners CRUD
│   ├── templates/            # Jinja2 HTML templates
│   └── static/               # CSS (lop.css) + JS (lop.js)
├── migrations/               # Alembic migration files
├── requirements.txt
└── run.py                    # Entry point (reads PORT env var)
```

## Implemented Modules

| Module       | Status      | Features                                        |
|--------------|-------------|-------------------------------------------------|
| Foundation   | ✅ Complete | Flask, PostgreSQL, SQLAlchemy, Alembic, Bootstrap 5 |
| Dashboard    | ✅ Complete | Live stats, environment cards, location summary, patch status, auto-refresh |
| Inventory    | ✅ Complete | Server list, search, filters, sorting, pagination, Add/Edit/Delete |
| Server Detail| ✅ Complete | Overview, hardware, identity, patching, packages, notes tabs |
| Settings     | ✅ Complete | CRUD for Locations, Environments, Owners with Bootstrap 5 modals |
| Patching     | ⏳ Next     | Patch status dashboard, kernel history, reboot dates |
| Reports      | ⏳ Planned  | Exportable server reports                       |
| Ansible API  | ⏳ Planned  | REST API endpoints for Ansible push model       |

## Database Migrations

```bash
cd lop
flask db migrate -m "describe change"   # generate migration
flask db upgrade                         # apply migrations
flask db downgrade                       # rollback one step
```

## Blueprint Architecture

Each module follows this pattern:
- **`queries.py`** — all database logic (reads, writes, validation)
- **`routes.py`** — thin controllers, call queries and redirect/render
- **`templates/<blueprint>/`** — Jinja2 templates extending `base.html`

CSRF protection is global (Flask-WTF `CSRFProtect`). All POST forms include `{{ csrf_token() }}`.

## Environment Variables

| Variable        | Source                    | Description               |
|-----------------|---------------------------|---------------------------|
| `DATABASE_URL`  | Replit managed            | PostgreSQL connection     |
| `SESSION_SECRET`| Replit Secret             | Flask SECRET_KEY fallback |
| `FLASK_ENV`     | `.replit` userenv         | `development`             |
| `LOG_LEVEL`     | `.replit` userenv         | `DEBUG`                   |
| `PORT`          | Replit managed            | Workflow port (5000)      |

## GitHub Repository

https://github.com/devops-revanth/Linux-Ops-Portal

**The GitHub repository is the single source of truth.** Always sync before making changes.

## User Preferences

- GitHub repository is the single source of truth — always pull latest before coding
- Do not overwrite existing work or regenerate modules that already exist
- All database logic must stay in `queries.py`; routes must stay lightweight
- Use Bootstrap 5 modal dialogs for all CRUD operations in Settings
- Maintain the existing dark theme throughout
- Work iteratively — complete one module at a time before starting the next
- Stop after completing the requested module and provide a review summary

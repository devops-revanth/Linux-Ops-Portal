# Linux Operations Portal (LOP)

A production-quality internal web application for Linux Infrastructure Operations. Replaces manual Excel-based server inventories with a centralised portal that automatically collects and maintains Linux server inventory and patching information using Ansible.

## Running the App

The app starts automatically via the **Linux Operations Portal** workflow (`python run.py`).

- Dev server: http://localhost:5000
- Health check: http://localhost:5000/health
- Dashboard: http://localhost:5000/dashboard

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12 · Flask 3.1 |
| ORM | Flask-SQLAlchemy · Flask-Migrate (Alembic) |
| Database | Replit PostgreSQL (via DATABASE_URL) |
| Frontend | Bootstrap 5.3 · Jinja2 · Bootstrap Icons |
| CSRF | Flask-WTF |

## Project Structure

```
Linux-Ops-Portal/
├── app/                    # Flask application package
│   ├── __init__.py         # Application factory (create_app)
│   ├── config.py           # Dev/Prod/Testing config classes
│   ├── extensions.py       # db, migrate, csrf singletons
│   ├── seeder.py           # Idempotent reference data seeder
│   ├── models/             # SQLAlchemy models
│   ├── blueprints/         # main, dashboard, inventory, settings
│   ├── templates/          # Jinja2 HTML (extends base.html)
│   └── static/             # lop.css · lop.js
├── migrations/             # Alembic migration files
├── docker/                 # Supplementary Docker files
├── docs/                   # Project documentation
├── ansible/                # Ansible playbook templates
├── tests/                  # Test suite
├── Dockerfile              # Multi-stage production image
├── docker-compose.yml      # PostgreSQL + Flask services
├── requirements.txt        # Python dependencies
├── run.py                  # Entry point
├── .env.example            # Environment variable template
└── .flaskenv               # Flask CLI configuration
```

## Replit Infrastructure (do not remove)

The following are required for the Replit workspace and must not be deleted:

| Path | Purpose |
|------|---------|
| `artifacts/` | Replit workspace artifacts (api-server, mockup-sandbox) |
| `lib/` | Replit monorepo libraries (api-spec, api-client, db) |
| `scripts/post-merge.sh` | Post-merge task runner (referenced by `.replit [postMerge]`) |
| `pnpm-workspace.yaml` | pnpm monorepo configuration |
| `package.json` | Root monorepo package |
| `tsconfig*.json` | TypeScript project references |

## Implemented Modules

| Module | Status | Features |
|--------|--------|---------|
| Foundation | ✅ | Flask, PostgreSQL, SQLAlchemy, Alembic, Bootstrap 5 |
| Dashboard | ✅ | Live stats, environment cards, location summary, patch status, auto-refresh |
| Inventory | ✅ | Server list, search, filters, sorting, pagination, Add/Edit/Delete |
| Server Detail | ✅ | Overview, hardware, identity, patching, packages, notes tabs |
| Settings | ✅ | CRUD for Locations, Environments, Owners with Bootstrap 5 modals |
| Patching | ⏳ | Next module |
| Reports | ⏳ | Planned |
| Ansible API | ⏳ | Planned |

## Database Migrations

```bash
flask db migrate -m "describe change"   # generate migration
flask db upgrade                         # apply migrations
flask db downgrade                       # rollback one step
```

## Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `DATABASE_URL` | Replit managed | PostgreSQL connection |
| `SESSION_SECRET` | Replit Secret | Flask SECRET_KEY fallback |
| `FLASK_ENV` | `.replit` userenv | `development` |
| `LOG_LEVEL` | `.replit` userenv | `DEBUG` |
| `PORT` | Replit managed | Workflow port (5000) |

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

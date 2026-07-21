# Linux Operations Portal (LOP)

A production-quality internal web application for Linux Infrastructure Operations. Replaces manual Excel-based server inventories with a centralized portal that automatically collects and maintains Linux server inventory and patching information using Ansible.

## How to Run

The app is configured with a single workflow: **Linux Operations Portal**  
Command: `cd lop && python run.py`

The app reads `PORT` from the environment (default 5000). It connects to Replit's managed PostgreSQL via the runtime-managed `DATABASE_URL` env var.

## Technology Stack

- **Backend**: Python 3.12 · Flask 3.1 · Flask-SQLAlchemy · Flask-Migrate (Alembic)
- **Database**: PostgreSQL (Replit managed) — `DATABASE_URL` is runtime-managed
- **Frontend**: Bootstrap 5.3 dark theme · Jinja2 templates · Bootstrap Icons
- **WSGI**: Gunicorn (production) / Flask dev server (development)

## Environment Variables

| Variable      | Source          | Notes                                      |
|---------------|-----------------|--------------------------------------------|
| `DATABASE_URL`| Runtime-managed | Auto-provided by Replit — do not set manually |
| `SECRET_KEY`  | Shared env var  | Set in Replit Secrets/Env; required for sessions |
| `FLASK_ENV`   | Shared env var  | `development` (current)                    |
| `FLASK_APP`   | Shared env var  | `run.py`                                   |
| `LOG_LEVEL`   | Shared env var  | `DEBUG` (current)                          |

## Database Migrations

Migrations are managed by Flask-Migrate (Alembic). To apply:

```bash
cd lop && flask db upgrade
```

Migration files live in `lop/migrations/versions/`.  
The initial schema (`f199ced7abac_initial_schema.py`) creates all tables.

## Project Structure

```
lop/
├── app/
│   ├── __init__.py           # Application factory (create_app)
│   ├── config.py             # DevelopmentConfig / ProductionConfig / TestingConfig
│   ├── extensions.py         # SQLAlchemy, Migrate, CSRF singletons
│   ├── seeder.py             # Seeds locations and environments on startup
│   ├── models/               # SQLAlchemy ORM models
│   │   ├── server.py         # linux_servers — central inventory record
│   │   ├── patching.py       # Patch status, kernel history, reboot dates
│   │   ├── package.py        # Package catalogue + per-server versions
│   │   ├── note.py           # Free-text notes per server
│   │   ├── environment.py    # Production / Dev / Stage / Demo
│   │   ├── location.py       # Data-centre / site locations
│   │   └── owner.py          # Responsible team or individual
│   ├── blueprints/
│   │   ├── main/             # Root redirect + health check
│   │   ├── dashboard/        # Aggregated stats overview
│   │   ├── inventory/        # Server list, add, edit, delete, detail, notes
│   │   └── settings/         # Locations and environments management
│   ├── templates/
│   │   ├── base.html         # Bootstrap 5 dark theme shell + sidebar
│   │   ├── dashboard/        # Dashboard stats page
│   │   ├── inventory/        # Inventory list + server detail page
│   │   ├── settings/         # Settings page
│   │   └── errors/           # 403 · 404 · 500 custom error pages
│   └── static/
│       ├── css/lop.css       # Custom portal styles
│       └── js/lop.js         # Bootstrap tooltips, popovers, flash dismiss
├── migrations/               # Alembic migration files
├── requirements.txt
├── run.py                    # Entry point — reads PORT env var
└── .flaskenv                 # FLASK_APP=run.py, FLASK_ENV=development
```

## Seeded Reference Data

Locations and environments are automatically seeded on first startup (idempotent):

**Locations**: USEG (US East – Global), UKDL (UK – Data Centre London), DEFR (DE – Frankfurt)  
**Environments**: Development, Stage, Demo, Production

## Module Status

| Module         | Status    | URL pattern                |
|----------------|-----------|----------------------------|
| Dashboard      | ✅ Complete | `/dashboard`             |
| Inventory      | ✅ Complete | `/inventory`             |
| Server Details | ✅ Complete | `/inventory/<id>`        |
| Patching       | ⏳ Pending  | —                        |
| Reports        | ⏳ Pending  | —                        |
| Settings       | ✅ Complete | `/settings`              |
| Ansible API    | ⏳ Pending  | —                        |

## User Preferences

- Build one module at a time and wait for approval before proceeding to the next.
- Do not redesign, refactor, or replace the existing Flask + PostgreSQL + Bootstrap 5 architecture.
- Maintain clean modular design: separate blueprints, queries.py per blueprint, thin routes.
- Do not generate multiple modules at once.

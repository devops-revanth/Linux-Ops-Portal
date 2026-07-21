# Linux Operations Portal (LOP)

A production-quality internal web portal for Linux infrastructure operations — replaces manual Excel-based server inventories with a centralised portal that collects and maintains Linux server inventory and patching information via Ansible.

## Run & Operate

- **Workflow**: `Linux Operations Portal` — `cd lop && python run.py` (port 5000)
- `cd lop && FLASK_APP=run.py flask db upgrade` — apply pending DB migrations
- `cd lop && FLASK_APP=run.py flask db migrate -m "description"` — generate a new migration after model changes
- Required env: `DATABASE_URL` — Postgres connection string (runtime-managed by Replit, always available)
- Required secret: `SESSION_SECRET` — available in Replit Secrets

## Stack

- Python 3.12, Flask 3.1, Gunicorn 23
- DB: PostgreSQL + Flask-SQLAlchemy + Flask-Migrate (Alembic)
- Frontend: Bootstrap 5.3 dark theme + Jinja2 templates
- Forms: Flask-WTF / WTForms (CSRF enabled)
- Automation: Ansible pushes data via REST API (no direct SSH from the portal)

## Where things live

_Populate as you build — short repo map plus pointers to the source-of-truth file for DB schema, API contracts, theme files, etc._

## Architecture decisions

_Populate as you build — non-obvious choices a reader couldn't infer from the code (3-5 bullets)._

## Product

_Describe the high-level user-facing capabilities of this app once they exist._

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

_Populate as you build — sharp edges, "always run X before Y" rules._

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details

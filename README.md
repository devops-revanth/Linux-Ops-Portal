# Linux Operations Portal (LOP)

A production-quality internal web application for Linux Infrastructure Operations teams.

LOP replaces manual Excel-based server inventories with a centralised, automatically-updated portal. Ansible playbooks push server facts via a REST API — LOP never initiates outbound SSH connections to managed servers.

---

## Screenshots

> _Screenshots will be added once the portal is deployed to a stable environment._
>
> **Dashboard** — server counts by environment and location, patch status ring  
> **Inventory** — searchable, filterable, paginated server list  
> **Server Details** — tabbed view: overview, hardware, patching, packages, notes  
> **Settings** — manage locations, environments, and owners

---

## Features

### Implemented ✅

| Module | Highlights |
|--------|-----------|
| **Dashboard** | Live server stats, environment cards with counts, location summary, patch status ring, 60-second auto-refresh |
| **Inventory** | Server list with search (hostname, IP, owner), filters (env/location/status), multi-column sort, pagination, full CRUD |
| **Server Details** | Tabbed view — Overview, Hardware, Patching, Packages, Notes — with edit and delete |
| **Settings** | Bootstrap 5 modal CRUD for Locations, Environments (colour badges), and Owners; deletion blocked on referenced records |
| **Foundation** | Flask factory pattern, PostgreSQL, Alembic migrations, CSRF protection, rotating logs, health check |

### Planned ⏳

- Patching dashboard (compliance overview, overdue alerts, kernel history)
- Ansible REST API (server sync, patch status push, package versions)
- Reports (CSV/JSON export, compliance by environment)
- Global search across all fields
- Role-based access control

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12 · Flask 3.1 · Gunicorn |
| ORM | Flask-SQLAlchemy 3.1 · Flask-Migrate (Alembic) |
| Database | PostgreSQL 16 |
| Frontend | Bootstrap 5.3 · Jinja2 · Bootstrap Icons |
| Security | Flask-WTF (CSRF) |
| Deployment | Docker · Docker Compose |
| Automation | Ansible (external — pushes data via REST API) |

---

## Project Structure

```
Linux-Ops-Portal/
├── app/                        # Flask application package
│   ├── __init__.py             # Application factory (create_app)
│   ├── config.py               # Dev / Prod / Testing configuration
│   ├── extensions.py           # db, migrate, csrf singletons
│   ├── seeder.py               # Idempotent reference data seeder
│   ├── models/                 # SQLAlchemy models
│   │   ├── server.py           # linux_servers (central inventory)
│   │   ├── location.py         # locations
│   │   ├── environment.py      # environments
│   │   ├── owner.py            # owners
│   │   ├── patching.py         # patch status + kernel history
│   │   ├── package.py          # packages + server_packages junction
│   │   └── note.py             # per-server notes
│   ├── blueprints/
│   │   ├── main/               # / root redirect + /health
│   │   ├── dashboard/          # /dashboard
│   │   ├── inventory/          # /inventory — full CRUD
│   │   └── settings/           # /settings — master data CRUD
│   ├── templates/              # Jinja2 templates (extends base.html)
│   └── static/                 # lop.css · lop.js
├── migrations/                 # Alembic migration scripts
├── docker/                     # Supplementary Docker files
├── docs/                       # Project documentation
│   ├── PRD.md                  # Product requirements
│   ├── DATABASE.md             # Schema reference
│   ├── API.md                  # Endpoint reference
│   ├── ARCHITECTURE.md         # Architecture decisions
│   ├── ROADMAP.md              # Feature roadmap
│   └── CHANGELOG.md            # Version history
├── ansible/                    # Ansible playbook templates
├── tests/                      # Test suite
├── Dockerfile                  # Multi-stage production image
├── docker-compose.yml          # PostgreSQL + Flask services
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variable template
└── run.py                      # Application entry point
```

---

## Installation

### Prerequisites

- Python 3.12+
- PostgreSQL 16

### Local Development (without Docker)

```bash
# 1. Clone the repository
git clone https://github.com/devops-revanth/Linux-Ops-Portal.git
cd Linux-Ops-Portal

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env — set SECRET_KEY and DATABASE_URL

# 5. Apply database migrations
flask db upgrade

# 6. Start the development server
python run.py
```

The portal will be available at **http://localhost:5000**

---

## Docker Deployment

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env — set at minimum: SECRET_KEY, POSTGRES_PASSWORD

# 2. Start the full stack (app + PostgreSQL)
docker compose up -d

# 3. Apply database migrations
docker compose exec app flask db upgrade

# 4. Follow application logs
docker compose logs -f app
```

The portal will be available at **http://localhost:5000**

### Docker Commands Reference

```bash
# Stop all services
docker compose down

# Stop and remove volumes (destroys database data)
docker compose down -v

# Rebuild the application image
docker compose build app

# Open a shell in the app container
docker compose exec app bash
```

---

## Database Migrations

```bash
# Generate a migration after model changes
flask db migrate -m "describe your change"

# Apply pending migrations
flask db upgrade

# Roll back one step
flask db downgrade

# Show current revision
flask db current
```

See [`docs/DATABASE.md`](docs/DATABASE.md) for the full schema reference.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | Yes | — | Flask session signing key |
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `FLASK_ENV` | No | `development` | Runtime environment |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity |
| `POSTGRES_DB` | No | `lop_db` | Docker Compose DB name |
| `POSTGRES_USER` | No | `lop_user` | Docker Compose DB user |
| `POSTGRES_PASSWORD` | No | — | Docker Compose DB password |

---

## Health Check

```
GET /health
→ {"status": "ok", "version": "1.0.0"}
```

Used by Docker Compose and load balancers.

---

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full architecture document including:

- Blueprint pattern and data flow diagrams
- Application factory explanation
- Configuration hierarchy
- Key architectural decisions

---

## Documentation

| Document | Description |
|----------|-------------|
| [`docs/PRD.md`](docs/PRD.md) | Product requirements and user personas |
| [`docs/DATABASE.md`](docs/DATABASE.md) | Full schema reference with column types |
| [`docs/API.md`](docs/API.md) | Current web endpoints + planned REST API spec |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Architecture decisions and data flow |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Feature roadmap with status |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | Version history |

---

## Contributing

1. The GitHub repository is the **single source of truth**
2. Always pull the latest before making changes
3. All database logic must live in `queries.py` — keep routes thin
4. Follow the existing blueprint pattern for new modules
5. Maintain the Bootstrap 5 dark theme throughout
6. Complete one module fully before starting the next

---

## License

MIT — see [`LICENSE`](LICENSE)

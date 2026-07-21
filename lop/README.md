# Linux Operations Portal (LOP)

A production-quality internal web application for Linux Infrastructure Operations.

LOP replaces manual Excel-based server inventories with a centralized portal that
automatically collects and maintains Linux server inventory and patching information
using Ansible — without ever SSHing directly to servers.

---

## Technology Stack

| Layer       | Technology                              |
|-------------|------------------------------------------|
| Backend     | Python 3.13 · Flask 3.1 · Gunicorn      |
| ORM         | Flask-SQLAlchemy · Flask-Migrate (Alembic) |
| Database    | PostgreSQL 16                            |
| Frontend    | Bootstrap 5.3 · Jinja2 · Bootstrap Icons |
| Deployment  | Docker · Docker Compose                  |
| Automation  | Ansible (external – pushes data via API) |

---

## Project Structure

```
lop/
├── app/
│   ├── __init__.py           # Application factory (create_app)
│   ├── config.py             # DevelopmentConfig / ProductionConfig / TestingConfig
│   ├── extensions.py         # SQLAlchemy, Migrate, CSRF singletons
│   ├── models/
│   │   ├── location.py       # Data-centre / site locations
│   │   ├── environment.py    # Production / Dev / Stage / Demo
│   │   ├── owner.py          # Responsible team or individual
│   │   ├── server.py         # linux_servers – central inventory record
│   │   ├── patching.py       # Patch status, kernel history, reboot dates
│   │   ├── package.py        # Package catalogue + per-server versions
│   │   └── note.py           # Free-text notes per server
│   ├── blueprints/
│   │   └── main/             # Root blueprint – index & health routes
│   ├── templates/
│   │   ├── base.html         # Bootstrap 5 dark theme shell + sidebar
│   │   ├── main/index.html   # Landing page / module roadmap
│   │   └── errors/           # 403 · 404 · 500 custom error pages
│   └── static/
│       ├── css/lop.css       # Custom portal styles
│       └── js/lop.js         # Client-side initialisation
├── logs/                     # Rotating log files (auto-created, gitignored)
├── migrations/               # Alembic migration files (generated)
├── Dockerfile                # Multi-stage production image
├── docker-compose.yml        # PostgreSQL + Flask services
├── requirements.txt          # Python dependencies
├── run.py                    # Application entry point
├── .env.example              # Template – copy to .env and fill in
└── .flaskenv                 # Flask CLI config (FLASK_APP, FLASK_ENV)
```

---

## Quick Start (Local Development)

### 1. Clone & enter the project

```bash
cd lop
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env – set SECRET_KEY and DATABASE_URL
```

### 5. Start PostgreSQL (Docker)

```bash
docker compose up -d db
```

### 6. Run database migrations

```bash
flask db upgrade
```

### 7. Run the development server

```bash
python run.py
# or: flask run
```

The portal will be available at **http://localhost:5000**

---

## Docker Compose (Full Stack)

```bash
cp .env.example .env        # fill in SECRET_KEY at minimum
docker compose up -d        # starts both db and app
docker compose logs -f app  # follow application logs
```

The portal will be available at **http://localhost:5000**

---

## Database Migrations

```bash
# Generate a new migration after model changes
flask db migrate -m "describe your change"

# Apply pending migrations
flask db upgrade

# Rollback one step
flask db downgrade
```

---

## Health Check

```
GET /health
```

Returns `{"status": "ok", "version": "1.0.0"}` — used by Docker Compose and
load balancers to verify the application is alive.

---

## Architecture Decisions

| Decision | Rationale |
|----------|-----------|
| Application factory (`create_app`) | Enables multiple configs (dev/prod/test) and avoids circular imports |
| Flask Blueprints | Modular structure — each portal module will be its own blueprint |
| Alembic (Flask-Migrate) | Schema version control, safe production migrations |
| Ansible push model | LOP never SSHs to servers — Ansible pushes data to the REST API |
| Docker multi-stage build | Keeps production image small; build tools excluded from runtime image |
| Bootstrap 5 dark theme | Clean, modern UI suitable for operations teams |

---

## Core Modules (Roadmap)

| Module          | Status    |
|-----------------|-----------|
| Foundation      | ✅ Complete |
| Dashboard       | ⏳ Pending |
| Inventory       | ⏳ Pending |
| Server Details  | ⏳ Pending |
| Patching        | ⏳ Pending |
| Reports         | ⏳ Pending |
| Settings        | ⏳ Pending |
| Ansible API     | ⏳ Pending |

---

## Environment Variables

| Variable            | Required | Default               | Description                          |
|---------------------|----------|-----------------------|--------------------------------------|
| `SECRET_KEY`        | Yes      | —                     | Flask session signing key            |
| `DATABASE_URL`      | Yes      | —                     | PostgreSQL connection string         |
| `FLASK_ENV`         | No       | `development`         | Runtime environment                  |
| `LOG_LEVEL`         | No       | `INFO`                | Logging verbosity                    |
| `POSTGRES_DB`       | No       | `lop_db`              | Docker Compose DB name               |
| `POSTGRES_USER`     | No       | `lop_user`            | Docker Compose DB user               |
| `POSTGRES_PASSWORD` | No       | —                     | Docker Compose DB password           |

---

## Ansible Integration

Ansible playbooks collect server facts and push them to LOP via REST API
endpoints (to be implemented in the Ansible API module). The application
**never** initiates outbound SSH connections to managed servers.

Fields collected by Ansible:
- Hostname, IP address, FQDN
- Operating system, OS version, kernel version
- CPU count/model, RAM
- Installed package versions (Docker, Python, Java, OpenSSL)
- Patch status, last patch date, last reboot date

Fields managed manually:
- Owner assignment
- Server notes

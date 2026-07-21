# Architecture — Linux Operations Portal

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser                              │
│               Bootstrap 5 Dark UI (Jinja2)                  │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP
┌──────────────────────────▼──────────────────────────────────┐
│                   Flask Application                          │
│                                                             │
│  ┌─────────────┐  ┌────────────┐  ┌──────────────────────┐  │
│  │  main BP    │  │ dashboard  │  │    inventory BP       │  │
│  │  / health   │  │    BP      │  │  list/add/edit/delete │  │
│  └─────────────┘  └────────────┘  └──────────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                  settings BP                         │    │
│  │    Locations · Environments · Owners  (CRUD)        │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Flask-SQLAlchemy ORM  ·  Flask-Migrate (Alembic)   │   │
│  └──────────────────────┬───────────────────────────────┘   │
└─────────────────────────┼───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                   PostgreSQL 16                              │
│  locations · environments · owners · linux_servers          │
│  patching · packages · server_packages · notes              │
└─────────────────────────────────────────────────────────────┘

                                              ┌──────────────┐
  Ansible Control Node ──── HTTP POST ───────▶│  REST API    │
  (external, push model)   /api/v1/servers/*  │  (planned)   │
                                              └──────────────┘
```

---

## Application Factory Pattern

```python
# run.py
app = create_app(os.environ.get("FLASK_ENV", "development"))

# app/__init__.py
def create_app(config_name):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    # register blueprints
    # register error handlers
    return app
```

Benefits:
- Multiple configurations (development / production / testing) via a single factory
- Avoids circular imports — extensions initialised separately from the app object
- Testable — each test can get a fresh app with `TestingConfig`

---

## Blueprint Structure

Each portal module is a Flask Blueprint:

```
app/blueprints/<module>/
├── __init__.py      # Blueprint definition
├── routes.py        # Thin controllers — validate input, call queries, redirect/render
└── queries.py       # All database logic — selects, inserts, updates, deletes
```

**Rule:** Routes never contain raw SQL or ORM queries. All DB work lives in `queries.py`.  
**Why:** Keeps routes readable; queries are independently testable without an HTTP client.

---

## Data Flow — Web Request

```
Browser POST /inventory/add
        │
        ▼
Flask-WTF CSRF validation (global, via CSRFProtect)
        │
        ▼
inventory.routes.add_server()
  └─ validates required fields
  └─ calls db.session.add() / commit()
  └─ flash success/error message
  └─ redirect → /inventory
        │
        ▼
inventory.routes.index()
  └─ calls get_inventory_page(filters, page, per_page)
        │
        ▼
inventory.queries.get_inventory_page()
  └─ SQLAlchemy query with outerjoin + filter + sort + paginate
  └─ returns InventoryPage dataclass
        │
        ▼
render_template("inventory/index.html", inventory=...)
        │
        ▼
Browser receives HTML
```

---

## Configuration Hierarchy

```
Config (base)
├── DevelopmentConfig  — DEBUG=True, verbose logging, localhost DB
├── ProductionConfig   — DEBUG=False, validates SECRET_KEY
└── TestingConfig      — SQLite in-memory, CSRF disabled
```

`SECRET_KEY` resolution order:
1. `SECRET_KEY` environment variable
2. `SESSION_SECRET` environment variable (Replit managed secret)
3. Hardcoded fallback `"change-me-in-production"` (raises warning)

`DATABASE_URL` resolution:
1. `DATABASE_URL` environment variable
2. Default: `postgresql://lop_user:lop_pass@localhost:5432/lop_db`
3. Normalises `postgres://` → `postgresql://` for psycopg2 compatibility

---

## Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| Application factory (`create_app`) | Supports multiple configs; avoids circular imports |
| Flask Blueprints | Each module is independently maintainable |
| Alembic (Flask-Migrate) | Schema version-controlled; safe production upgrades |
| Ansible push model | LOP has no outbound network access to managed servers |
| Bootstrap 5 dark theme | Suitable for operations teams; CDN-served (no build step) |
| All DB logic in `queries.py` | Routes stay thin; queries are unit-testable |
| CSRF on all POST forms | Flask-WTF `CSRFProtect` is global — no per-form opt-in |

---

## Directory Structure

```
Linux-Ops-Portal/
├── app/                        # Flask application package
│   ├── __init__.py             # Application factory
│   ├── config.py               # Configuration classes
│   ├── extensions.py           # db, migrate, csrf singletons
│   ├── seeder.py               # Idempotent reference data seeder
│   ├── models/                 # SQLAlchemy models
│   │   ├── server.py           # linux_servers
│   │   ├── location.py         # locations
│   │   ├── environment.py      # environments
│   │   ├── owner.py            # owners
│   │   ├── patching.py         # patching
│   │   ├── package.py          # packages + server_packages
│   │   └── note.py             # notes
│   ├── blueprints/
│   │   ├── main/               # / and /health
│   │   ├── dashboard/          # /dashboard
│   │   ├── inventory/          # /inventory (full CRUD)
│   │   └── settings/           # /settings (Locations, Envs, Owners CRUD)
│   ├── templates/              # Jinja2 HTML templates
│   │   ├── base.html           # Bootstrap 5 shell + sidebar
│   │   └── <blueprint>/        # Per-blueprint templates
│   └── static/
│       ├── css/lop.css         # Custom portal styles
│       └── js/lop.js           # Client-side initialisation
├── migrations/                 # Alembic migration files
├── docker/                     # Supplementary Docker files
├── docs/                       # Project documentation
├── ansible/                    # Ansible playbook templates
├── tests/                      # Test suite
├── Dockerfile                  # Multi-stage production image
├── docker-compose.yml          # PostgreSQL + Flask services
├── requirements.txt            # Python dependencies
├── run.py                      # Entry point
├── .env.example                # Environment variable template
└── .flaskenv                   # Flask CLI configuration
```

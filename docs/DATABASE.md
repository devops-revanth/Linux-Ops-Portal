# Database Reference — Linux Operations Portal

**ORM:** Flask-SQLAlchemy 3.1  
**Migration tool:** Flask-Migrate (Alembic)  
**Database:** PostgreSQL 16

---

## Schema Overview

```
environments ──────────────────────────┐
locations    ──────────────────────────┤
owners       ──────────────────────────┤
                                       ▼
                              linux_servers
                              ┌────────────┐
                              │ id (PK)    │
                              │ hostname   │
                              │ ip_address │
                              │ fqdn       │
                              │ env_id FK  │
                              │ loc_id FK  │
                              │ owner_id FK│
                              │ os_*       │
                              │ cpu_*      │
                              │ ram_gb     │
                              │ status     │
                              └─────┬──────┘
                                    │
              ┌─────────────────────┼──────────────────────┐
              ▼                     ▼                        ▼
           patching               notes              server_packages
        (1-to-1, cascade)    (1-to-many, cascade)   (many-to-many via packages)
```

---

## Tables

### `locations`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK, auto-increment |
| `name` | VARCHAR(100) | NOT NULL, UNIQUE |
| `description` | VARCHAR(255) | nullable |
| `is_active` | BOOLEAN | NOT NULL, default TRUE |
| `created_at` | TIMESTAMPTZ | NOT NULL |
| `updated_at` | TIMESTAMPTZ | NOT NULL |

**Seeded defaults:** USEG (US East), UKDL (UK London), DEFR (DE Frankfurt)

---

### `environments`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK, auto-increment |
| `name` | VARCHAR(100) | NOT NULL, UNIQUE |
| `label` | VARCHAR(50) | NOT NULL |
| `color` | VARCHAR(20) | NOT NULL, default "secondary" |
| `is_active` | BOOLEAN | NOT NULL, default TRUE |
| `created_at` | TIMESTAMPTZ | NOT NULL |
| `updated_at` | TIMESTAMPTZ | NOT NULL |

Valid colours: `primary`, `secondary`, `success`, `danger`, `warning`, `info`

**Seeded defaults:** Development (primary), Stage (info), Demo (warning), Production (danger)

---

### `owners`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK, auto-increment |
| `name` | VARCHAR(150) | NOT NULL, UNIQUE |
| `email` | VARCHAR(255) | nullable |
| `is_active` | BOOLEAN | NOT NULL, default TRUE |
| `created_at` | TIMESTAMPTZ | NOT NULL |
| `updated_at` | TIMESTAMPTZ | NOT NULL |

---

### `linux_servers`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK, auto-increment |
| `hostname` | VARCHAR(255) | NOT NULL, UNIQUE, indexed |
| `fqdn` | VARCHAR(255) | nullable |
| `ip_address` | VARCHAR(45) | NOT NULL, indexed |
| `environment_id` | INTEGER | FK → environments.id, nullable, indexed |
| `location_id` | INTEGER | FK → locations.id, nullable, indexed |
| `owner_id` | INTEGER | FK → owners.id, nullable, indexed |
| `operating_system` | VARCHAR(100) | nullable |
| `os_version` | VARCHAR(100) | nullable |
| `kernel_version` | VARCHAR(150) | nullable |
| `cpu_count` | INTEGER | nullable |
| `cpu_model` | VARCHAR(255) | nullable |
| `ram_gb` | FLOAT | nullable |
| `status` | VARCHAR(50) | NOT NULL, default "active" |
| `last_ansible_sync` | TIMESTAMPTZ | nullable |
| `created_at` | TIMESTAMPTZ | NOT NULL |
| `updated_at` | TIMESTAMPTZ | NOT NULL |

Valid statuses: `active`, `inactive`, `maintenance`, `decommissioned`

---

### `patching`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK |
| `server_id` | INTEGER | FK → linux_servers.id, UNIQUE, cascade delete |
| `patch_status` | VARCHAR(50) | NOT NULL, default "unknown" |
| `current_kernel` | VARCHAR(150) | nullable |
| `available_kernel` | VARCHAR(150) | nullable |
| `last_patch_date` | DATE | nullable |
| `last_reboot_date` | DATE | nullable |
| `updates_available` | INTEGER | nullable |
| `created_at` | TIMESTAMPTZ | NOT NULL |
| `updated_at` | TIMESTAMPTZ | NOT NULL |

Valid patch statuses: `up-to-date`, `pending`, `failed`, `unknown`

---

### `packages`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK |
| `name` | VARCHAR(100) | NOT NULL, UNIQUE |
| `description` | VARCHAR(255) | nullable |

---

### `server_packages`

Junction table linking servers to their installed package versions.

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK |
| `server_id` | INTEGER | FK → linux_servers.id, cascade delete |
| `package_id` | INTEGER | FK → packages.id |
| `version` | VARCHAR(100) | nullable |
| `updated_at` | TIMESTAMPTZ | NOT NULL |

Unique constraint: `(server_id, package_id)`

---

### `notes`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK |
| `server_id` | INTEGER | FK → linux_servers.id, cascade delete |
| `author` | VARCHAR(100) | nullable |
| `body` | TEXT | NOT NULL |
| `created_at` | TIMESTAMPTZ | NOT NULL |
| `updated_at` | TIMESTAMPTZ | NOT NULL |

---

## Migration Commands

```bash
# Generate a new migration after model changes
flask db migrate -m "describe your change"

# Apply all pending migrations
flask db upgrade

# Roll back one revision
flask db downgrade

# Show current revision
flask db current

# Show migration history
flask db history
```

---

## Cascade Delete Rules

| Parent deleted | Cascades to |
|----------------|-------------|
| `linux_servers` | `patching`, `server_packages`, `notes` (all cascade delete) |
| `locations` | Blocked — servers must be reassigned first |
| `environments` | Blocked — servers must be reassigned first |
| `owners` | Blocked — servers must be reassigned first |
| `packages` | `server_packages` rows (no cascade — package catalogue is independent) |

---

## Connection

On Replit, `DATABASE_URL` is injected automatically. Locally, set it in `.env`:

```
DATABASE_URL=postgresql://lop_user:lop_pass@localhost:5432/lop_db
```

The `Config` base class normalises legacy `postgres://` prefixes to `postgresql://`.

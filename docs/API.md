# API Reference — Linux Operations Portal

**Status:** Partially implemented (web routes only). REST API for Ansible integration is planned.

---

## Current Endpoints (Web / Browser)

These are standard HTML form endpoints — they return redirects, not JSON.

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Returns `{"status": "ok", "version": "1.0.0"}` |

### Dashboard

| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard` | Dashboard overview page |

### Inventory

| Method | Path | Description |
|--------|------|-------------|
| GET | `/inventory` | Server list (search, filter, sort, paginate) |
| POST | `/inventory/add` | Create a new server |
| GET | `/inventory/<id>` | Server detail page |
| POST | `/inventory/<id>/edit` | Update a server |
| POST | `/inventory/<id>/delete` | Delete a server |
| POST | `/inventory/<id>/notes/add` | Add a note to a server |
| POST | `/inventory/<id>/notes/<note_id>/delete` | Delete a note |

### Settings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/settings` | Settings overview |
| POST | `/settings/locations/add` | Create a location |
| POST | `/settings/locations/<id>/edit` | Update a location |
| POST | `/settings/locations/<id>/delete` | Delete a location |
| POST | `/settings/environments/add` | Create an environment |
| POST | `/settings/environments/<id>/edit` | Update an environment |
| POST | `/settings/environments/<id>/delete` | Delete an environment |
| POST | `/settings/owners/add` | Create an owner |
| POST | `/settings/owners/<id>/edit` | Update an owner |
| POST | `/settings/owners/<id>/delete` | Delete an owner |

---

## Planned REST API (Ansible Integration)

The following endpoints will be implemented to support the Ansible push model.
All endpoints will require an `X-API-Key` header.

### Base URL

```
/api/v1/
```

### Authentication

```
X-API-Key: <provisioned-api-key>
```

---

### Server Sync

#### `POST /api/v1/servers/sync`

Upsert a server record from Ansible facts. Creates the server if it does not exist; updates it if it does (matched by `hostname`).

**Request body:**
```json
{
  "hostname": "web-prod-01",
  "ip_address": "10.0.1.10",
  "fqdn": "web-prod-01.example.com",
  "operating_system": "Rocky Linux",
  "os_version": "9.3",
  "kernel_version": "5.14.0-362.8.1.el9_3.x86_64",
  "cpu_count": 8,
  "cpu_model": "Intel Xeon E5-2690",
  "ram_gb": 32.0
}
```

**Response (201 Created / 200 OK):**
```json
{
  "status": "created",
  "server_id": 42,
  "hostname": "web-prod-01"
}
```

---

#### `POST /api/v1/servers/<hostname>/patching`

Update patch status for a specific server.

**Request body:**
```json
{
  "patch_status": "pending",
  "current_kernel": "5.14.0-362.8.1.el9_3.x86_64",
  "available_kernel": "5.14.0-427.13.1.el9_4.x86_64",
  "updates_available": 14,
  "last_patch_date": "2024-03-15",
  "last_reboot_date": "2024-03-15"
}
```

**Response (200 OK):**
```json
{
  "status": "updated",
  "server_id": 42,
  "patch_status": "pending"
}
```

---

#### `POST /api/v1/servers/<hostname>/packages`

Sync installed package versions for a server.

**Request body:**
```json
{
  "packages": [
    { "name": "docker", "version": "24.0.7" },
    { "name": "python3", "version": "3.11.5" },
    { "name": "openssl", "version": "3.0.7" }
  ]
}
```

---

### Error Responses

All REST API errors return JSON:

```json
{
  "error": "Server 'web-prod-99' not found.",
  "code": 404
}
```

| HTTP Status | Meaning |
|-------------|---------|
| 200 | Success (update) |
| 201 | Success (create) |
| 400 | Bad request / validation error |
| 401 | Missing or invalid API key |
| 404 | Resource not found |
| 409 | Conflict (e.g. duplicate hostname on create) |
| 500 | Internal server error |

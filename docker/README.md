# Docker Supplementary Files

The primary Docker configuration lives at the project root:

- `../Dockerfile` — Multi-stage production image (Python 3.13 slim)
- `../docker-compose.yml` — Orchestrates the `app` and `db` (PostgreSQL 16) services

## Usage

```bash
# Copy env template and fill in values
cp ../.env.example ../.env

# Start the full stack (app + database)
docker compose -f ../docker-compose.yml up -d

# Follow application logs
docker compose -f ../docker-compose.yml logs -f app

# Run database migrations inside the container
docker compose -f ../docker-compose.yml exec app flask db upgrade

# Stop all services
docker compose -f ../docker-compose.yml down
```

## Future Additions

Place supplementary Docker files here:

- `nginx/nginx.conf` — Reverse proxy configuration
- `init-db/` — PostgreSQL initialisation scripts
- `healthcheck.sh` — Custom health check script

# ─────────────────────────────────────────────────────────────
# Linux Operations Portal – Production Dockerfile
# Base: Python 3.13 slim (matches Rocky Linux 9 target runtime)
# ─────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ──────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# Install build dependencies for psycopg2 (libpq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: production image ────────────────────────────────
FROM python:3.13-slim AS production

# Runtime Postgres client library
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
  && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN groupadd -r lop && useradd -r -g lop -d /app -s /sbin/nologin lop

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application source
COPY --chown=lop:lop . .

# Create logs directory
RUN mkdir -p /app/logs && chown lop:lop /app/logs

USER lop

EXPOSE 5000

# Health check (Docker will mark container unhealthy if Flask is down)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:5000/health || exit 1

# Production entry point via gunicorn
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "4", \
     "--worker-class", "sync", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info", \
     "run:app"]

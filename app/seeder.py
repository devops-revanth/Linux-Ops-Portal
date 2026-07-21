"""
Database seeder.

Seeds reference / master data on first run.  Each seed function is
idempotent — it only inserts rows that do not already exist.
"""
from __future__ import annotations

import logging

from .extensions import db
from .models.environment import Environment
from .models.location import Location

logger = logging.getLogger(__name__)

# ── Seed definitions ─────────────────────────────────────────────────────── #

_LOCATIONS: list[dict] = [
    {"name": "USEG", "description": "US East – Global"},
    {"name": "UKDL", "description": "UK – Data Centre London"},
    {"name": "DEFR", "description": "DE – Frankfurt"},
]

_ENVIRONMENTS: list[dict] = [
    {"name": "Development", "label": "Dev",   "color": "primary"},
    {"name": "Stage",       "label": "Stage", "color": "info"},
    {"name": "Demo",        "label": "Demo",  "color": "warning"},
    {"name": "Production",  "label": "Prod",  "color": "danger"},
]


# ── Public entry point ────────────────────────────────────────────────────── #

def seed_all() -> None:
    """Seed all reference data.  Safe to call on every application start."""
    _seed_locations()
    _seed_environments()
    _seed_admin_user()


# ── Private helpers ───────────────────────────────────────────────────────── #

def _seed_locations() -> None:
    inserted = 0
    for data in _LOCATIONS:
        exists = db.session.query(
            Location.query.filter_by(name=data["name"]).exists()
        ).scalar()
        if not exists:
            db.session.add(Location(**data))
            inserted += 1
    if inserted:
        db.session.commit()
        logger.info("Seeder: inserted %d location(s)", inserted)
    else:
        logger.debug("Seeder: locations already present, skipping")


def _seed_environments() -> None:
    inserted = 0
    for data in _ENVIRONMENTS:
        exists = db.session.query(
            Environment.query.filter_by(name=data["name"]).exists()
        ).scalar()
        if not exists:
            db.session.add(Environment(**data))
            inserted += 1
    if inserted:
        db.session.commit()
        logger.info("Seeder: inserted %d environment(s)", inserted)
    else:
        logger.debug("Seeder: environments already present, skipping")


def _seed_admin_user() -> None:
    """Create an initial admin user if no users exist.

    Credentials are sourced from environment variables:
      ADMIN_USERNAME  – defaults to "admin" if not set
      ADMIN_PASSWORD  – must be set for a known password; if absent a
                        cryptographically random password is generated,
                        logged once at WARNING level, and must be copied
                        from the application log before it is lost.

    This function never creates a user with a predictable static password.
    In production, always set ADMIN_PASSWORD before first deployment.
    """
    import os
    import secrets

    from .models.user import User

    if User.query.first() is not None:
        logger.debug("Seeder: users already present, skipping")
        return

    username = os.environ.get("ADMIN_USERNAME", "admin").strip() or "admin"

    password = os.environ.get("ADMIN_PASSWORD", "").strip()
    generated = False
    if not password:
        # No password supplied — generate a strong random one.
        # The operator MUST read it from the application log to log in.
        password = secrets.token_urlsafe(20)
        generated = True

    admin = User(username=username, email="admin@localhost")
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()

    if generated:
        logger.warning(
            "Seeder: created initial admin account — "
            "username=%s  password=%s  "
            "(auto-generated; copy it now — it will not be shown again). "
            "Set the ADMIN_PASSWORD environment variable before the next deployment "
            "to use a known password.",
            username, password,
        )
    else:
        logger.info(
            "Seeder: created initial admin account (username=%s) "
            "using the supplied ADMIN_PASSWORD.",
            username,
        )

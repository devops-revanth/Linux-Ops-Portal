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

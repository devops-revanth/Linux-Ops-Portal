"""
Database seeder.

Seeds reference / master data on first run.  Each seed function is
idempotent — it only inserts rows that do not already exist.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

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


# ── Public entry points ───────────────────────────────────────────────────── #

def seed_all() -> None:
    """
    Seed production reference data only.  Safe to call on every application
    start — never creates demo or sample inventory.

    Seeded:
      • Locations    (USEG, UKDL, DEFR)
      • Environments (Development, Stage, Demo, Production)
      • Admin user   (only when no users exist)

    NOT seeded automatically:
      • Demo servers — call seed_demo() explicitly via 'flask seed-demo'
    """
    _seed_locations()
    _seed_environments()
    _seed_admin_user()


def seed_demo() -> None:
    """
    Load sample servers for development/demo purposes.

    Creates three realistic servers:
      web-prod-01   RHEL 9.3       — Compliant   (0 pending, patched 20 days ago)
      db-prod-01    RHEL 8.10      — Due Soon    (5 pending, patched 75 days ago)
      jump-test-01  Rocky Linux 9  — Overdue     (6 pending, patched 120 days ago)

    This function is NEVER called automatically.  To load demo data, run:
        flask seed-demo

    It is idempotent — skips if any of the demo hostnames already exist.
    """
    _seed_demo_servers()


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
    """Create an initial admin user if no users exist."""
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
        password = secrets.token_urlsafe(20)
        generated = True

    admin = User(
        username=username,
        email="admin@localhost",
        role="administrator",
        auth_source="local",
    )
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()

    if generated:
        logger.warning(
            "Seeder: created initial admin account — "
            "username=%s  password=%s  "
            "(auto-generated; copy it now — it will not be shown again).",
            username, password,
        )
    else:
        logger.info(
            "Seeder: created initial admin account (username=%s).", username
        )


def _seed_demo_servers() -> None:
    """
    Seed three realistic demo servers.

    web-prod-01   RHEL 9.3     — No updates,  Compliant  (patched 20 days ago)
    db-prod-01    RHEL 8.10    — Updates YES,  Due Soon   (patched 75 days ago)
    jump-test-01  Rocky Linux 9 — Updates YES, Overdue    (patched 120 days ago)

    Idempotent: skips if any of the three hostnames already exists.
    """
    from .models.server import Server
    from .models.patching import Patching
    from .models.package import Package, ServerPackage

    demo_hostnames = {"web-prod-01", "db-prod-01", "jump-test-01"}
    existing = {
        s.hostname
        for s in Server.query.filter(Server.hostname.in_(demo_hostnames)).all()
    }
    if existing:
        logger.debug("Seeder: demo servers already present, skipping")
        return

    now = datetime.now(timezone.utc)

    # ── Resolve environment + location FKs ───────────────────────────────
    prod_env  = Environment.query.filter_by(name="Production").first()
    stage_env = Environment.query.filter_by(name="Stage").first()
    useg_loc  = Location.query.filter_by(name="USEG").first()
    ukdl_loc  = Location.query.filter_by(name="UKDL").first()
    defr_loc  = Location.query.filter_by(name="DEFR").first()

    def _pkg(name: str, display: str | None = None) -> Package:
        p = Package.query.filter_by(name=name).first()
        if p is None:
            p = Package(name=name, display_name=display or name)
            db.session.add(p)
            db.session.flush()
        return p

    # ─────────────────────────────────────────────────────────────────────
    # Server 1: web-prod-01 — RHEL 9.3, Compliant, no updates
    # ─────────────────────────────────────────────────────────────────────
    web = Server(
        hostname          = "web-prod-01",
        fqdn              = "web-prod-01.corp.example.com",
        ip_address        = "10.0.1.10",
        environment_id    = prod_env.id  if prod_env  else None,
        location_id       = useg_loc.id  if useg_loc  else None,
        operating_system  = "Red Hat Enterprise Linux",
        os_version        = "9.3",
        kernel_version    = "5.14.0-362.8.1.el9_3.x86_64",
        cpu_count         = 4,
        ram_gb            = 16.0,
        status            = "active",
        last_ansible_sync = now - timedelta(days=1),
    )
    db.session.add(web)
    db.session.flush()

    db.session.add(Patching(
        server_id        = web.id,
        patch_status     = "up-to-date",
        current_kernel   = "5.14.0-362.8.1.el9_3.x86_64",
        previous_kernel  = "5.14.0-284.30.1.el9_2.x86_64",
        last_patch_date  = now - timedelta(days=20),
        last_reboot_date = now - timedelta(days=20),
        pending_updates  = 0,
        reboot_required  = False,
    ))

    for pkg_name, display, version, repo, delta in [
        ("openssl",         "OpenSSL",         "3.0.7-27.el9_3",      "rhel-9-baseos",    timedelta(days=20)),
        ("nginx",           "nginx",           "1.24.0-3.el9",        "rhel-9-appstream", timedelta(days=35)),
        ("python3",         "Python 3",        "3.11.5-1.el9",        "rhel-9-appstream", timedelta(days=50)),
        ("curl",            "curl",            "7.76.1-26.el9_3.1",   "rhel-9-baseos",    timedelta(days=20)),
        ("ca-certificates", "CA Certificates", "2023.2.60-90.0.el9_3","rhel-9-baseos",    timedelta(days=20)),
    ]:
        p = _pkg(pkg_name, display)
        db.session.add(ServerPackage(
            server_id        = web.id,
            package_id       = p.id,
            version          = version,
            collected_at     = now - delta,
            update_available = False,
            repository       = repo,
        ))

    # ─────────────────────────────────────────────────────────────────────
    # Server 2: db-prod-01 — RHEL 8.10, Due Soon, 5 pending updates
    # Patched 75 days ago → within 90-day window → Due Soon
    # ─────────────────────────────────────────────────────────────────────
    db_srv = Server(
        hostname          = "db-prod-01",
        fqdn              = "db-prod-01.corp.example.com",
        ip_address        = "10.0.1.20",
        environment_id    = prod_env.id  if prod_env  else None,
        location_id       = ukdl_loc.id  if ukdl_loc  else None,
        operating_system  = "Red Hat Enterprise Linux",
        os_version        = "8.10",
        kernel_version    = "4.18.0-553.22.1.el8_10.x86_64",
        cpu_count         = 8,
        ram_gb            = 64.0,
        status            = "active",
        last_ansible_sync = now - timedelta(days=2),
    )
    db.session.add(db_srv)
    db.session.flush()

    db.session.add(Patching(
        server_id        = db_srv.id,
        patch_status     = "pending",
        current_kernel   = "4.18.0-553.22.1.el8_10.x86_64",
        previous_kernel  = "4.18.0-513.18.1.el8_9.x86_64",
        last_patch_date  = now - timedelta(days=75),
        last_reboot_date = now - timedelta(days=75),
        pending_updates  = 5,
        reboot_required  = False,
    ))

    # Recently installed
    for pkg_name, display, version, repo, delta in [
        ("postgresql",   "PostgreSQL",    "13.14-1.el8",       "rhel-8-appstream", timedelta(days=75)),
        ("glibc",        "GNU C Library", "2.28-236.el8_10.1", "rhel-8-baseos",    timedelta(days=75)),
        ("systemd",      "systemd",       "239-78.el8_10.2",   "rhel-8-baseos",    timedelta(days=75)),
    ]:
        p = _pkg(pkg_name, display)
        db.session.add(ServerPackage(
            server_id        = db_srv.id,
            package_id       = p.id,
            version          = version,
            collected_at     = now - delta,
            update_available = False,
            repository       = repo,
        ))

    # Available updates
    for pkg_name, display, cur_ver, avail_ver, repo, upd_type in [
        ("openssl",  "OpenSSL",      "1.1.1k-12.el8",    "1.1.1k-14.el8_10",  "rhel-8-baseos",    "security"),
        ("sudo",     "sudo",         "1.9.5p2-1.el8",    "1.9.5p2-3.el8_10",  "rhel-8-baseos",    "security"),
        ("bash",     "GNU Bash",     "5.1.8-6.el8",      "5.1.8-9.el8_10",    "rhel-8-baseos",    "bugfix"),
        ("podman",   "Podman",       "4.4.1-17.el8",     "4.9.4-5.el8_10",    "rhel-8-appstream", "enhancement"),
        ("firewalld","firewalld",    "0.9.4-2.el8",      "0.9.4-6.el8_10",    "rhel-8-baseos",    "bugfix"),
    ]:
        p = _pkg(pkg_name, display)
        db.session.add(ServerPackage(
            server_id         = db_srv.id,
            package_id        = p.id,
            version           = cur_ver,
            collected_at      = now - timedelta(days=77),
            update_available  = True,
            available_version = avail_ver,
            update_type       = upd_type,
            repository        = repo,
        ))

    # ─────────────────────────────────────────────────────────────────────
    # Server 3: jump-test-01 — Rocky Linux 9, Overdue, 6 pending updates
    # Patched 120 days ago → beyond 90+15=105 day threshold → Overdue
    # ─────────────────────────────────────────────────────────────────────
    jump = Server(
        hostname          = "jump-test-01",
        fqdn              = "jump-test-01.stage.example.com",
        ip_address        = "10.1.2.30",
        environment_id    = stage_env.id if stage_env else None,
        location_id       = defr_loc.id  if defr_loc  else None,
        operating_system  = "Rocky Linux",
        os_version        = "9.3",
        kernel_version    = "5.14.0-362.18.1.el9_3.x86_64",
        cpu_count         = 2,
        ram_gb            = 8.0,
        status            = "active",
        last_ansible_sync = now - timedelta(days=3),
    )
    db.session.add(jump)
    db.session.flush()

    db.session.add(Patching(
        server_id        = jump.id,
        patch_status     = "pending",
        current_kernel   = "5.14.0-362.18.1.el9_3.x86_64",
        previous_kernel  = "5.14.0-284.30.1.el9_2.x86_64",
        last_patch_date  = now - timedelta(days=120),
        last_reboot_date = now - timedelta(days=120),
        pending_updates  = 6,
        reboot_required  = True,
    ))

    # Recently installed
    for pkg_name, display, version, repo, delta in [
        ("python3", "Python 3", "3.9.18-3.el9",    "rhel-9-appstream", timedelta(days=120)),
        ("chrony",  "chrony",   "4.3-1.el9",        "rhel-9-baseos",    timedelta(days=120)),
        ("rpm",     "RPM",      "4.16.1.3-27.el9",  "rhel-9-baseos",    timedelta(days=120)),
    ]:
        p = _pkg(pkg_name, display)
        db.session.add(ServerPackage(
            server_id        = jump.id,
            package_id       = p.id,
            version          = version,
            collected_at     = now - delta,
            update_available = False,
            repository       = repo,
        ))

    # Available updates
    for pkg_name, display, cur_ver, avail_ver, repo, upd_type in [
        ("kernel",     "Linux Kernel","5.14.0-362.18.1.el9_3.x86_64","5.14.0-503.14.1.el9_5","rhel-9-baseos",    "bugfix"),
        ("openssl",    "OpenSSL",     "3.0.7-24.el9",                 "3.0.7-27.el9_3",       "rhel-9-baseos",    "security"),
        ("glibc",      "GNU C Library","2.34-60.el9",                 "2.34-125.el9_5.4",     "rhel-9-baseos",    "security"),
        ("systemd",    "systemd",     "252-18.el9",                   "252-46.el9_5",          "rhel-9-baseos",    "bugfix"),
        ("sudo",       "sudo",        "1.9.5p2-9.el9",                "1.9.5p2-10.el9_3",     "rhel-9-baseos",    "security"),
        ("podman",     "Podman",      "4.6.1-7.el9",                  "5.2.2-1.el9",           "rhel-9-appstream", "enhancement"),
    ]:
        p = _pkg(pkg_name, display)
        existing_sp = ServerPackage.query.filter_by(
            server_id=jump.id, package_id=p.id
        ).first()
        if existing_sp is None:
            db.session.add(ServerPackage(
                server_id         = jump.id,
                package_id        = p.id,
                version           = cur_ver,
                collected_at      = now - timedelta(days=122),
                update_available  = True,
                available_version = avail_ver,
                update_type       = upd_type,
                repository        = repo,
            ))

    try:
        db.session.commit()
        logger.info(
            "Seeder: inserted 3 demo servers "
            "(web-prod-01/RHEL 9.3, db-prod-01/RHEL 8.10, jump-test-01/Rocky Linux 9)"
        )
    except Exception:
        db.session.rollback()
        logger.exception("Seeder: failed to insert demo servers")

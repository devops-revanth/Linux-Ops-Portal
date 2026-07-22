"""
Background scheduler for VMware and Ansible scheduled operations.

Phase 4 changes:
  • reschedule_vmware_connections(app) — replaces the old single-connection
    reschedule(). Clears all vmware_conn_* jobs and re-adds one per enabled
    VmwareConnection with a non-disabled schedule.
  • _add_vmware_connection_job(scheduler, app, conn) — registers one job.
  • _run_scheduled_connection_sync(app, connection_id) — job target.
  • reschedule(app, schedule) kept as a backward-compat no-op alias.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_SCHEDULE_MAP: dict[str, dict] = {
    "hourly": {"hours": 1},
    "6h":     {"hours": 6},
    "12h":    {"hours": 12},
    "daily":  {"hours": 24},
}

_ANSIBLE_JOB_ID = "ansible_scheduled_facts"

# Legacy single-connection job ID kept for backward compat
_VMWARE_JOB_ID = "vmware_scheduled_sync"
_JOB_ID        = _VMWARE_JOB_ID


def init_scheduler(app) -> None:
    """
    Start APScheduler and restore all scheduled jobs from the database.
    Guards against the Werkzeug reloader watchdog process.
    """
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
    except ImportError:
        logger.warning("APScheduler not installed — scheduled syncs unavailable")
        return

    try:
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.start()
        app.extensions["vmware_scheduler"] = scheduler
        app.logger.info("APScheduler started")

        # ── Restore VMware connection schedules (Phase 4) ──────────────── #
        try:
            with app.app_context():
                _restore_vmware_connection_schedules(scheduler, app)
        except Exception as exc:
            logger.debug("Could not restore VMware connection schedules: %s", exc)

        # ── Restore Ansible fact collection schedule ───────────────────── #
        try:
            with app.app_context():
                from .models.ansible_config import AnsibleConfig
                acfg = AnsibleConfig.query.first()
                if (
                    acfg and acfg.enabled and acfg.sync_enabled
                    and acfg.sync_schedule
                    and acfg.sync_schedule != "disabled"
                ):
                    _add_ansible_job(scheduler, app, acfg.sync_schedule)
                    app.logger.info(
                        "Ansible fact collection schedule restored: %s", acfg.sync_schedule
                    )
        except Exception as exc:
            logger.debug("Could not restore Ansible fact schedule on startup: %s", exc)

        # ── Restore playbook schedules ─────────────────────────────────── #
        try:
            with app.app_context():
                reschedule_playbooks(app)
        except Exception as exc:
            logger.debug("Could not restore playbook schedules on startup: %s", exc)

    except Exception as exc:
        logger.warning("Could not start APScheduler: %s", exc)


def _restore_vmware_connection_schedules(scheduler, app) -> None:
    """Load all enabled VmwareConnections with schedules and register jobs."""
    try:
        from .models.vmware_connection import VmwareConnection
        conns = VmwareConnection.query.filter(
            VmwareConnection.enabled == True,  # noqa: E712
            VmwareConnection.sync_schedule != "disabled",
        ).all()
        for conn in conns:
            _add_vmware_connection_job(scheduler, app, conn)
            logger.info(
                "VMware connection '%s' schedule restored: %s",
                conn.name, conn.sync_schedule,
            )
    except Exception as exc:
        logger.debug("_restore_vmware_connection_schedules failed: %s", exc)


# ── Per-connection scheduler helpers ─────────────────────────────────────── #

def reschedule_vmware_connections(app) -> None:
    """
    Sync ALL enabled VmwareConnection schedules into APScheduler.

    Removes all existing vmware_conn_* jobs, then re-adds one per enabled
    connection that has a non-disabled schedule.  Call after any connection
    is added, edited, deleted, or toggled.
    """
    scheduler = app.extensions.get("vmware_scheduler")
    if scheduler is None:
        return

    try:
        # Clear all per-connection jobs
        for job in scheduler.get_jobs():
            if job.id.startswith("vmware_conn_"):
                try:
                    scheduler.remove_job(job.id)
                except Exception:
                    pass

        with app.app_context():
            from .models.vmware_connection import VmwareConnection
            conns = VmwareConnection.query.filter(
                VmwareConnection.enabled == True,  # noqa: E712
                VmwareConnection.sync_schedule != "disabled",
            ).all()
            for conn in conns:
                _add_vmware_connection_job(scheduler, app, conn)

    except Exception as exc:
        logger.warning("reschedule_vmware_connections failed: %s", exc)


def _add_vmware_connection_job(scheduler, app, conn) -> None:
    """Register a single VmwareConnection sync job in APScheduler."""
    kwargs = _SCHEDULE_MAP.get(conn.sync_schedule)
    if not kwargs:
        logger.warning("Unknown schedule %r for connection %s", conn.sync_schedule, conn.name)
        return

    job_id = f"vmware_conn_{conn.id}"
    scheduler.add_job(
        id=job_id,
        func=_run_scheduled_connection_sync,
        args=[app, conn.id],
        trigger="interval",
        replace_existing=True,
        misfire_grace_time=300,
        **kwargs,
    )
    logger.debug("Registered vmware job %s (%s)", job_id, conn.sync_schedule)


def remove_vmware_connection_job(app, connection_id: int) -> None:
    """Remove the APScheduler job for a specific connection (on delete/disable)."""
    scheduler = app.extensions.get("vmware_scheduler")
    if scheduler is None:
        return
    try:
        scheduler.remove_job(f"vmware_conn_{connection_id}")
    except Exception:
        pass


def _run_scheduled_connection_sync(app, connection_id: int) -> None:
    """APScheduler job target for a single VmwareConnection."""
    try:
        from .services.vmware_service import sync_connection
        sync_connection(app, connection_id, triggered_by="scheduled")
    except Exception as exc:
        logger.error("Scheduled VMware sync (conn_id=%d) failed: %s", connection_id, exc)


# ── Legacy backward-compat aliases ───────────────────────────────────────── #

def reschedule(app, schedule: str) -> None:
    """
    Legacy single-connection reschedule — now delegates to
    reschedule_vmware_connections() which handles all connections.
    Kept so any direct callers don't break.
    """
    reschedule_vmware_connections(app)


def _add_vmware_job(scheduler, app, schedule: str) -> None:
    """Legacy helper — kept for backward compat but no longer used directly."""
    pass


_add_job = _add_vmware_job
_run_scheduled_sync = None  # no longer a function; kept to prevent AttributeError


# ── Ansible fact collection scheduler ────────────────────────────────────── #

def reschedule_ansible(app, schedule: str) -> None:
    """Update the Ansible fact collection scheduled job."""
    scheduler = app.extensions.get("vmware_scheduler")
    if scheduler is None:
        return
    try:
        scheduler.remove_job(_ANSIBLE_JOB_ID)
    except Exception:
        pass
    if schedule and schedule != "disabled":
        _add_ansible_job(scheduler, app, schedule)
        logger.info("Ansible fact collection rescheduled: %s", schedule)


def _add_ansible_job(scheduler, app, schedule: str) -> None:
    kwargs = _SCHEDULE_MAP.get(schedule)
    if not kwargs:
        logger.warning("Unknown Ansible sync schedule: %r", schedule)
        return
    scheduler.add_job(
        id=_ANSIBLE_JOB_ID,
        func=_run_scheduled_ansible_facts,
        args=[app],
        trigger="interval",
        replace_existing=True,
        misfire_grace_time=600,
        **kwargs,
    )


def _run_scheduled_ansible_facts(app) -> None:
    try:
        with app.app_context():
            from .models.ansible_config import AnsibleConfig
            cfg = AnsibleConfig.query.first()
            if not cfg or not cfg.enabled or not cfg.sync_enabled:
                return
            if cfg.connection_status != "Connected":
                return
            from .services.ansible_fact_service import collect_facts
            collect_facts(cfg, app, triggered_by="scheduled")
    except Exception as exc:
        logger.error("Scheduled Ansible fact collection job failed: %s", exc)


# ── Playbook scheduler ────────────────────────────────────────────────────── #

def reschedule_playbooks(app) -> None:
    """
    Sync all enabled PlaybookSchedule records into APScheduler.
    Removes stale jobs for deleted/disabled schedules.
    """
    scheduler = app.extensions.get("vmware_scheduler")
    if scheduler is None:
        return

    try:
        with app.app_context():
            from .models.playbook import PlaybookSchedule

            for job in scheduler.get_jobs():
                if job.id.startswith("playbook_sched_"):
                    try:
                        scheduler.remove_job(job.id)
                    except Exception:
                        pass

            for sched in PlaybookSchedule.query.filter_by(is_enabled=True).all():
                _add_playbook_job(scheduler, app, sched)
    except Exception as exc:
        logger.warning("reschedule_playbooks failed: %s", exc)


def _add_playbook_job(scheduler, app, sched) -> None:
    job_id = f"playbook_sched_{sched.id}"
    try:
        if sched.schedule_type == "cron" and sched.cron_expression:
            fields = sched.cron_expression.strip().split()
            if len(fields) == 5:
                minute, hour, day, month, day_of_week = fields
                scheduler.add_job(
                    id=job_id,
                    func=_run_scheduled_playbook,
                    args=[app, sched.id],
                    trigger="cron",
                    minute=minute, hour=hour,
                    day=day, month=month, day_of_week=day_of_week,
                    replace_existing=True, misfire_grace_time=600,
                )
        else:
            interval_map = {
                "hourly":  {"hours": 1},
                "daily":   {"hours": 24},
                "weekly":  {"weeks": 1},
                "monthly": {"days": 30},
            }
            kwargs = interval_map.get(sched.schedule_type)
            if kwargs:
                scheduler.add_job(
                    id=job_id,
                    func=_run_scheduled_playbook,
                    args=[app, sched.id],
                    trigger="interval",
                    replace_existing=True, misfire_grace_time=600,
                    **kwargs,
                )
    except Exception as exc:
        logger.warning("Failed to register playbook schedule %d: %s", sched.id, exc)


def _run_scheduled_playbook(app, schedule_id: int) -> None:
    import threading
    try:
        with app.app_context():
            from .models.playbook import PlaybookSchedule
            from .models.ansible_config import AnsibleConfig
            from .extensions import db
            from datetime import datetime, timezone

            sched = PlaybookSchedule.query.get(schedule_id)
            if sched is None or not sched.is_enabled:
                return

            t = sched.template
            if t is None:
                return

            cfg = AnsibleConfig.query.first()
            if cfg is None or not cfg.enabled:
                return

            settings      = t.get_settings()
            playbook_path = (settings.get("playbook_path") or "").strip()
            if not playbook_path:
                return

            from .models.playbook import PlaybookJob
            now = datetime.now(timezone.utc)
            job = PlaybookJob(
                playbook_id   = t.playbook_id,
                playbook_path = playbook_path,
                playbook_name = (
                    settings.get("playbook_name") or playbook_path.rsplit("/", 1)[-1]
                ),
                template_id      = t.id,
                triggered_by     = f"schedule:{sched.name}",
                status           = "pending",
                limit_expression = settings.get("limit_expression"),
                inventory_type   = settings.get("inventory_type") or "default",
                inventory_value  = settings.get("inventory_value"),
                become     = str(settings.get("become", "")).lower() in ("1", "true", "yes"),
                check_mode = str(settings.get("check_mode", "")).lower() in ("1", "true", "yes"),
                forks      = int(settings.get("forks") or 5),
                verbosity  = int(settings.get("verbosity") or 0),
                tags       = settings.get("tags"),
                skip_tags  = settings.get("skip_tags"),
                extra_vars = settings.get("extra_vars"),
                created_at = now,
            )
            db.session.add(job)
            sched.last_run_at = now
            db.session.commit()
            job_id = job.id

        from .services.playbook_service import launch_job
        threading.Thread(target=launch_job, args=(job_id, app), daemon=True).start()

    except Exception as exc:
        logger.error("Scheduled playbook job (schedule_id=%d) failed: %s", schedule_id, exc)

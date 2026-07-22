"""
Background scheduler for VMware and Ansible scheduled operations.

Uses APScheduler's BackgroundScheduler (daemon thread) so it lives
alongside the Flask dev/production server without requiring a separate
process.

Only one instance is started — guarded against the Werkzeug reloader
watchdog process which would otherwise start a duplicate.
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

_VMWARE_JOB_ID  = "vmware_scheduled_sync"
_ANSIBLE_JOB_ID = "ansible_scheduled_facts"

# Keep the old alias so existing callers still work
_JOB_ID = _VMWARE_JOB_ID


def init_scheduler(app) -> None:
    """
    Start APScheduler and load the VMware sync schedule from the database.

    Safe to call from create_app() — guards against the Werkzeug reloader
    watchdog process and import errors when APScheduler is unavailable.
    """
    # In debug mode the reloader forks a child process; only the child
    # (WERKZEUG_RUN_MAIN=true) should own the scheduler.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
    except ImportError:
        logger.warning("APScheduler not installed — scheduled VMware sync unavailable")
        return

    try:
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.start()
        app.extensions["vmware_scheduler"] = scheduler
        app.logger.info("APScheduler started")

        # Restore VMware schedule from the database
        try:
            with app.app_context():
                from .models.vmware_config import VmwareConfig
                cfg = VmwareConfig.query.first()
                if (
                    cfg and cfg.enabled
                    and cfg.sync_schedule
                    and cfg.sync_schedule != "disabled"
                ):
                    _add_vmware_job(scheduler, app, cfg.sync_schedule)
                    app.logger.info(
                        "VMware scheduled sync restored: %s", cfg.sync_schedule
                    )
        except Exception as exc:
            logger.debug("Could not restore VMware schedule on startup: %s", exc)

        # Restore Ansible fact collection schedule from the database
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

    except Exception as exc:
        logger.warning("Could not start APScheduler: %s", exc)


def reschedule(app, schedule: str) -> None:
    """
    Update the VMware scheduled sync job.
    Called from settings routes after saving VMware config.
    Silently no-ops if the scheduler is not running.
    """
    scheduler = app.extensions.get("vmware_scheduler")
    if scheduler is None:
        return
    try:
        scheduler.remove_job(_VMWARE_JOB_ID)
    except Exception:
        pass
    if schedule and schedule != "disabled":
        _add_vmware_job(scheduler, app, schedule)
        logger.info("VMware sync rescheduled: %s", schedule)


def reschedule_ansible(app, schedule: str) -> None:
    """
    Update the Ansible fact collection scheduled job.
    Called from settings routes after saving Ansible config.
    Silently no-ops if the scheduler is not running.
    """
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


def _add_vmware_job(scheduler, app, schedule: str) -> None:
    """Register the VMware sync job with the given schedule string."""
    kwargs = _SCHEDULE_MAP.get(schedule)
    if not kwargs:
        logger.warning("Unknown VMware sync schedule: %r", schedule)
        return
    scheduler.add_job(
        id=_VMWARE_JOB_ID,
        func=_run_scheduled_vmware_sync,
        args=[app],
        trigger="interval",
        replace_existing=True,
        misfire_grace_time=300,
        **kwargs,
    )


def _add_ansible_job(scheduler, app, schedule: str) -> None:
    """Register the Ansible fact collection job with the given schedule string."""
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


# ── Keep old name as alias so callers using _add_job still work ────────────── #
_add_job = _add_vmware_job


def _run_scheduled_vmware_sync(app) -> None:
    """APScheduler job target for VMware — runs inside a new app context."""
    from .services.vmware_service import VmwareService, is_sync_running
    try:
        with app.app_context():
            from .models.vmware_config import VmwareConfig
            cfg = VmwareConfig.query.first()
            if not cfg or not cfg.enabled:
                return
            if is_sync_running():
                logger.info("Scheduled VMware sync skipped — sync already running")
                return
            svc = VmwareService.from_config(cfg)
            svc.sync_now(app, triggered_by="scheduled")
    except Exception as exc:
        logger.error("Scheduled VMware sync job failed: %s", exc)


# Keep old name as alias
_run_scheduled_sync = _run_scheduled_vmware_sync


def _run_scheduled_ansible_facts(app) -> None:
    """APScheduler job target for Ansible fact collection — runs inside a new app context."""
    try:
        with app.app_context():
            from .models.ansible_config import AnsibleConfig
            cfg = AnsibleConfig.query.first()
            if not cfg or not cfg.enabled or not cfg.sync_enabled:
                return
            if cfg.connection_status != "Connected":
                logger.info(
                    "Scheduled Ansible fact collection skipped — "
                    "control node not connected (status=%s)", cfg.connection_status
                )
                return
            from .services.ansible_fact_service import collect_facts
            collect_facts(cfg, app, triggered_by="scheduled")
    except Exception as exc:
        logger.error("Scheduled Ansible fact collection job failed: %s", exc)

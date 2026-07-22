"""
Background scheduler for VMware scheduled synchronisation.

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

_JOB_ID = "vmware_scheduled_sync"


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

        # Restore any active schedule from the database
        try:
            with app.app_context():
                from .models.vmware_config import VmwareConfig
                cfg = VmwareConfig.query.first()
                if (
                    cfg and cfg.enabled
                    and cfg.sync_schedule
                    and cfg.sync_schedule != "disabled"
                ):
                    _add_job(scheduler, app, cfg.sync_schedule)
                    app.logger.info(
                        "VMware scheduled sync restored: %s", cfg.sync_schedule
                    )
        except Exception as exc:
            logger.debug("Could not restore VMware schedule on startup: %s", exc)

    except Exception as exc:
        logger.warning("Could not start APScheduler: %s", exc)


def reschedule(app, schedule: str) -> None:
    """
    Called from routes after settings are saved to update the active job.
    Silently no-ops if the scheduler is not running.
    """
    scheduler = app.extensions.get("vmware_scheduler")
    if scheduler is None:
        return
    # Remove existing job
    try:
        scheduler.remove_job(_JOB_ID)
    except Exception:
        pass
    if schedule and schedule != "disabled":
        _add_job(scheduler, app, schedule)
        logger.info("VMware sync rescheduled: %s", schedule)


def _add_job(scheduler, app, schedule: str) -> None:
    """Register the sync job with the given schedule string."""
    kwargs = _SCHEDULE_MAP.get(schedule)
    if not kwargs:
        logger.warning("Unknown VMware sync schedule: %r", schedule)
        return
    scheduler.add_job(
        id=_JOB_ID,
        func=_run_scheduled_sync,
        args=[app],
        trigger="interval",
        replace_existing=True,
        misfire_grace_time=300,
        **kwargs,
    )


def _run_scheduled_sync(app) -> None:
    """APScheduler job target — runs inside a new app context."""
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

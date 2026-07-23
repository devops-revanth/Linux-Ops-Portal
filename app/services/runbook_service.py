"""
Runbook execution service.

Orchestrates sequential PlaybookJob executions for a RunbookJob.
Reuses the existing playbook_service.launch_job() without modification.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def execute_runbook(runbook_job_id: int, app) -> None:
    """
    Background-thread entry point.

    Runs each RunbookStepExecution in order, calling launch_job() for
    playbook/template steps.  Respects on_failure policy per step.
    """
    with app.app_context():
        from ..extensions import db
        from ..models.runbook import RunbookJob, RunbookStepExecution
        from ..models.playbook import PlaybookJob
        from ..models.ansible_config import AnsibleConfig

        job: RunbookJob = RunbookJob.query.get(runbook_job_id)
        if not job:
            logger.error("execute_runbook: RunbookJob #%d not found", runbook_job_id)
            return

        logger.info("RunbookJob #%d (%s) starting", job.id, job.runbook_name)
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        db.session.commit()

        cfg = AnsibleConfig.query.first()
        if not cfg or not cfg.enabled:
            _fail_job(job, "Ansible is not configured or disabled.", db)
            return

        steps: list[RunbookStepExecution] = job.step_executions

        for step in steps:
            # Re-check for cancellation before each step
            db.session.refresh(job)
            if job.status == "cancelled":
                _mark_remaining_skipped(step, steps, db)
                return

            # Disabled or operator-skipped steps
            if step.skipped or step.status == "disabled":
                step.status = "skipped"
                db.session.commit()
                continue

            # ── Mark step as running ────────────────────────────────────── #
            step.status = "running"
            step.started_at = datetime.now(timezone.utc)
            db.session.commit()
            logger.info("  RunbookJob #%d step %d (%s) starting",
                        job.id, step.position, step.display_name)

            # ── Resolve playbook path ────────────────────────────────────── #
            playbook_path = _resolve_playbook_path(step)
            if not playbook_path:
                _fail_step(step, "Cannot resolve playbook path for this step.", db)
                if step.on_failure == "stop":
                    _fail_job(job, f"Step {step.position} ({step.display_name}) failed: no playbook path.", db)
                    return
                continue

            # ── Build execution params ───────────────────────────────────── #
            params = step.get_params()
            become     = job.become or _bool(params.get("become"))
            check_mode = job.check_mode or _bool(params.get("check_mode"))
            forks      = int(params.get("forks") or 5)
            verbosity  = int(params.get("verbosity") or 0)
            extra_vars = job.extra_vars or params.get("extra_vars") or None
            tags       = params.get("tags") or None
            skip_tags  = params.get("skip_tags") or None

            # ── Create the PlaybookJob record ────────────────────────────── #
            now = datetime.now(timezone.utc)
            pjob = PlaybookJob(
                playbook_path    = playbook_path,
                playbook_name    = step.playbook_name or playbook_path.rsplit("/", 1)[-1],
                triggered_by     = f"runbook:{job.runbook_name}",
                status           = "pending",
                target_type      = job.target_type,
                target_value     = job.target_value,
                limit_expression = job.limit_expression,
                become           = become,
                check_mode       = check_mode,
                forks            = forks,
                verbosity        = verbosity,
                tags             = tags,
                skip_tags        = skip_tags,
                extra_vars       = extra_vars,
                created_at       = now,
            )
            db.session.add(pjob)
            db.session.commit()

            step.playbook_job_id = pjob.id
            db.session.commit()

            # ── Execute (blocking) ────────────────────────────────────────── #
            try:
                from .playbook_service import launch_job
                launch_job(pjob.id, app)
            except Exception as exc:
                logger.exception("RunbookJob #%d step %d launch_job failed",
                                 job.id, step.position)
                _fail_step(step, str(exc), db)
                if step.on_failure == "stop":
                    _fail_job(job, f"Step {step.position} ({step.display_name}) raised an exception.", db)
                    return
                continue

            # ── Evaluate result ──────────────────────────────────────────── #
            db.session.refresh(pjob)
            step.finished_at = datetime.now(timezone.utc)

            if pjob.status == "completed":
                step.status = "completed"
                db.session.commit()
                logger.info("  RunbookJob #%d step %d completed OK", job.id, step.position)

            elif pjob.status == "cancelled":
                step.status = "skipped"
                step.error_message = "PlaybookJob was cancelled."
                db.session.commit()
                job.status = "cancelled"
                job.finished_at = datetime.now(timezone.utc)
                db.session.commit()
                logger.warning("RunbookJob #%d cancelled at step %d", job.id, step.position)
                return

            else:
                # failed / timed-out / unexpected status
                _fail_step(step, f"PlaybookJob #{pjob.id} finished with status '{pjob.status}'.", db)
                logger.warning("  RunbookJob #%d step %d FAILED (pjob status=%s)",
                               job.id, step.position, pjob.status)
                if step.on_failure == "stop":
                    _fail_job(job, f"Step {step.position} ({step.display_name}) failed.", db)
                    return
                # continue to next step

        # ── All steps processed ──────────────────────────────────────────── #
        db.session.refresh(job)
        if job.status not in ("failed", "cancelled"):
            any_failed = any(s.status == "failed" for s in job.step_executions)
            job.status = "failed" if any_failed else "completed"
            job.finished_at = datetime.now(timezone.utc)
            db.session.commit()
            logger.info("RunbookJob #%d finished with status '%s'", job.id, job.status)


# ── Internal helpers ─────────────────────────────────────────────────────── #

def _resolve_playbook_path(step) -> str:
    """Return the ansible-playbook path for a step, or empty string."""
    if step.step_type == "playbook":
        return step.playbook_path or ""
    if step.step_type == "template":
        params = step.get_params()
        return params.get("playbook_path") or ""
    return ""


def _fail_step(step, message: str, db) -> None:
    step.status = "failed"
    step.error_message = message
    step.finished_at = datetime.now(timezone.utc)
    db.session.commit()


def _fail_job(job, message: str, db) -> None:
    job.status = "failed"
    job.error_message = message
    job.finished_at = datetime.now(timezone.utc)
    db.session.commit()
    logger.error("RunbookJob #%d failed: %s", job.id, message)


def _mark_remaining_skipped(current_step, all_steps, db) -> None:
    """Mark current and all following steps as skipped after cancellation."""
    mark = False
    for s in all_steps:
        if s.id == current_step.id:
            mark = True
        if mark and s.status == "pending":
            s.status = "skipped"
    db.session.commit()


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return bool(v)
    return str(v).lower() in ("1", "true", "yes", "on")

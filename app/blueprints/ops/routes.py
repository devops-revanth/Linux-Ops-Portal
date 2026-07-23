"""
Ansible Operations workspace routes — Phase 3.

URL prefix: /ansible (ops_bp)

Pages:
  GET  /ansible              → redirect to catalog
  GET  /ansible/catalog      → playbook catalog
  GET  /ansible/jobs         → jobs list
  GET  /ansible/jobs/<id>    → job detail + live output
  GET  /ansible/templates    → saved templates
  GET  /ansible/schedules    → schedule management

AJAX:
  POST /ansible/catalog/discover         → refresh catalog
  POST /ansible/catalog/<id>/toggle      → enable/disable
  POST /ansible/jobs/launch              → start a job
  GET  /ansible/jobs/<id>/output         → stream log (offset param)
  POST /ansible/jobs/<id>/cancel         → cancel
  GET  /ansible/jobs/<id>/download       → download log
  POST /ansible/templates/save           → create/update template
  POST /ansible/templates/<id>/delete    → delete
  POST /ansible/templates/<id>/launch    → one-click launch
  POST /ansible/schedules/save           → create/update schedule
  POST /ansible/schedules/<id>/toggle    → enable/disable
  POST /ansible/schedules/<id>/delete    → delete
  POST /ansible/schedules/<id>/run-now   → trigger immediately
  GET  /ansible/api/hosts                → host selector (AJAX)
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

from flask import (
    Response,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from . import ops_bp
from ...audit import commit_audit, log_action
from ...extensions import db

logger = logging.getLogger(__name__)

# Guard against concurrent discover calls
_discover_lock = threading.Lock()


# ── Helpers ────────────────────────────────────────────────────────────────── #

def _get_cfg():
    from ...models.ansible_config import AnsibleConfig
    return AnsibleConfig.query.first()


def _username() -> str:
    try:
        return current_user.username or current_user.display_name or "unknown"
    except Exception:
        return "unknown"


def _detect_production(limit_expr: str, target_value: str) -> bool:
    """Return True if any target host belongs to a Production environment."""
    try:
        from ...models.server import Server
        from ...models.environment import Environment
        prod_env = Environment.query.filter(
            Environment.name.ilike("%prod%")
        ).first()
        if prod_env is None:
            return False
        if Server.query.filter(
            Server.environment_id == prod_env.id
        ).count() > 0:
            # Broad check: if limit is empty, all servers run (including prod)
            if not limit_expr and not target_value:
                return True
            # If a specific environment was chosen and it's production
            if "production" in (target_value or "").lower():
                return True
    except Exception:
        pass
    return False


# ── Index redirect ─────────────────────────────────────────────────────────── #

@ops_bp.route("/ansible")
@login_required
def index():
    return redirect(url_for("ops.summary"))


# ═══════════════════════════════════════════════════════════════════════════════
# ANSIBLE SUMMARY (DASHBOARD)
# ═══════════════════════════════════════════════════════════════════════════════

@ops_bp.route("/ansible/summary")
@login_required
def summary():
    """Ansible section landing page — status cards + recent activity."""
    from ...models.playbook import Playbook, PlaybookJob, PlaybookJobTemplate, PlaybookSchedule
    from ...models.ansible_config import AnsibleInventoryHost
    from ...extensions import db

    cfg = _get_cfg()
    migration_needed = False

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Runbook count — guarded: table may not exist if migration hasn't been applied.
    runbooks_total = 0
    try:
        from ...models.runbook import Runbook
        runbooks_total = Runbook.query.filter_by(is_enabled=True).count()
    except Exception:
        db.session.rollback()
        migration_needed = True
        current_app.logger.warning(
            "Runbook tables missing — run `flask db upgrade`. Defaulting to 0."
        )

    stats = {
        "playbooks_total":   Playbook.query.count(),
        "playbooks_enabled": Playbook.query.filter_by(is_enabled=True).count(),
        "templates_total":   PlaybookJobTemplate.query.count(),
        "schedules_active":  PlaybookSchedule.query.filter_by(is_enabled=True).count(),
        "inventory_hosts":   AnsibleInventoryHost.query.count(),
        "runbooks_total":    runbooks_total,
        "jobs_running":      PlaybookJob.query.filter(PlaybookJob.status == "running").count(),
        "jobs_pending":      PlaybookJob.query.filter(PlaybookJob.status == "pending").count(),
        "jobs_failed_today": PlaybookJob.query.filter(
            PlaybookJob.status == "failed",
            PlaybookJob.created_at >= today_start,
        ).count(),
        "jobs_ok_today": PlaybookJob.query.filter(
            PlaybookJob.status == "completed",
            PlaybookJob.created_at >= today_start,
        ).count(),
        "jobs_total": PlaybookJob.query.count(),
    }

    recent_jobs = (
        PlaybookJob.query
        .order_by(PlaybookJob.created_at.desc())
        .limit(10)
        .all()
    )

    return render_template(
        "ops/summary.html",
        cfg=cfg,
        stats=stats,
        recent_jobs=recent_jobs,
        migration_needed=migration_needed,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ANSIBLE INVENTORY VIEW
# ═══════════════════════════════════════════════════════════════════════════════

@ops_bp.route("/ansible/inventory")
@login_required
def ansible_inventory():
    """Show hosts discovered from the Ansible inventory."""
    from ...models.ansible_config import AnsibleInventoryHost

    search = request.args.get("q", "").strip()
    group  = request.args.get("group", "").strip()

    q = AnsibleInventoryHost.query
    if search:
        q = q.filter(AnsibleInventoryHost.hostname.ilike(f"%{search}%"))
    if group:
        q = q.filter(AnsibleInventoryHost.groups.ilike(f"%{group}%"))

    hosts = q.order_by(AnsibleInventoryHost.hostname).all()

    # Build group list for filter dropdown
    all_groups: list[str] = sorted({
        g.strip()
        for h in AnsibleInventoryHost.query.all()
        for g in (h.groups or "").split(",")
        if g.strip()
    })

    cfg = _get_cfg()

    return render_template(
        "ops/ansible_inventory.html",
        cfg=cfg,
        hosts=hosts,
        all_groups=all_groups,
        search=search,
        group_filter=group,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# RUNBOOKS
# ═══════════════════════════════════════════════════════════════════════════════

@ops_bp.route("/ansible/runbooks")
@login_required
def runbooks():
    from ...extensions import db

    migration_needed = False
    rb_list: list = []
    last_jobs: dict = {}

    try:
        from ...models.runbook import Runbook, RunbookJob
        rb_list = Runbook.query.order_by(Runbook.name).all()

        # Last job status per runbook
        for rb in rb_list:
            last_job = (
                RunbookJob.query
                .filter_by(runbook_id=rb.id)
                .order_by(RunbookJob.created_at.desc())
                .first()
            )
            if last_job:
                last_jobs[rb.id] = last_job
    except Exception:
        db.session.rollback()
        migration_needed = True
        current_app.logger.warning(
            "Runbook tables missing — run `flask db upgrade`. Showing empty list."
        )

    return render_template(
        "ops/runbooks.html",
        runbooks=rb_list,
        last_jobs=last_jobs,
        migration_needed=migration_needed,
        cfg=_get_cfg(),
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


@ops_bp.route("/ansible/runbooks/new")
@login_required
def runbook_new():
    from ...models.playbook import Playbook, PlaybookJobTemplate
    playbooks = Playbook.query.filter_by(is_enabled=True).order_by(Playbook.name).all()
    templates = PlaybookJobTemplate.query.order_by(PlaybookJobTemplate.name).all()
    return render_template(
        "ops/runbook_detail.html",
        rb=None,
        playbooks=playbooks,
        templates=templates,
        cfg=_get_cfg(),
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


@ops_bp.route("/ansible/runbooks/<int:rb_id>")
@login_required
def runbook_detail(rb_id: int):
    from ...models.runbook import Runbook
    from ...models.playbook import Playbook, PlaybookJobTemplate
    rb = Runbook.query.get_or_404(rb_id)
    playbooks = Playbook.query.filter_by(is_enabled=True).order_by(Playbook.name).all()
    templates = PlaybookJobTemplate.query.order_by(PlaybookJobTemplate.name).all()
    return render_template(
        "ops/runbook_detail.html",
        rb=rb,
        playbooks=playbooks,
        templates=templates,
        cfg=_get_cfg(),
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


@ops_bp.route("/ansible/runbooks/save", methods=["POST"])
@login_required
def runbook_save():
    from ...models.runbook import Runbook
    data   = request.get_json(silent=True) or request.form
    rb_id  = _int_or_none(data.get("id"))
    name   = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "message": "Runbook name is required."})

    now = datetime.now(timezone.utc)
    if rb_id:
        rb = Runbook.query.get(rb_id)
        if rb is None:
            return jsonify({"success": False, "message": "Runbook not found."})
        action = "runbook.update"
    else:
        rb = Runbook(created_by=_username(), created_at=now)
        db.session.add(rb)
        action = "runbook.create"

    rb.name        = name
    rb.description = (data.get("description") or "").strip() or None
    rb.category    = (data.get("category") or "").strip() or None
    rb.is_enabled  = _bool(data.get("is_enabled", True))
    rb.updated_at  = now
    db.session.commit()

    commit_audit(action, target=rb.name, result="success")
    return jsonify({"success": True, "id": rb.id, "message": f"Runbook '{rb.name}' saved."})


@ops_bp.route("/ansible/runbooks/<int:rb_id>/clone", methods=["POST"])
@login_required
def runbook_clone(rb_id: int):
    from ...models.runbook import Runbook, RunbookStep
    import copy
    rb = Runbook.query.get_or_404(rb_id)
    now = datetime.now(timezone.utc)

    clone = Runbook(
        name        = f"Copy of {rb.name}",
        description = rb.description,
        category    = rb.category,
        is_enabled  = False,  # clones start disabled to avoid accidental runs
        created_by  = _username(),
        created_at  = now,
        updated_at  = now,
    )
    db.session.add(clone)
    db.session.flush()  # get clone.id

    for step in rb.steps:
        s = RunbookStep(
            runbook_id  = clone.id,
            step_type   = step.step_type,
            playbook_id = step.playbook_id,
            template_id = step.template_id,
            position    = step.position,
            label       = step.label,
            notes       = step.notes,
            is_required = step.is_required,
            is_enabled  = step.is_enabled,
            on_failure  = step.on_failure,
        )
        db.session.add(s)

    db.session.commit()
    commit_audit("runbook.clone", target=rb.name,
                 details=f"clone_id={clone.id}", result="success")
    return jsonify({
        "success":  True,
        "id":       clone.id,
        "redirect": url_for("ops.runbook_detail", rb_id=clone.id),
        "message":  f"Runbook cloned as '{clone.name}'.",
    })


@ops_bp.route("/ansible/runbooks/<int:rb_id>/delete", methods=["POST"])
@login_required
def runbook_delete(rb_id: int):
    from ...models.runbook import Runbook
    rb = Runbook.query.get_or_404(rb_id)
    name = rb.name
    db.session.delete(rb)
    db.session.commit()
    commit_audit("runbook.delete", target=name, result="success")
    return jsonify({"success": True, "message": f"Runbook '{name}' deleted."})


# ── Runbook Steps CRUD ──────────────────────────────────────────────────────── #

@ops_bp.route("/ansible/runbooks/<int:rb_id>/steps/add", methods=["POST"])
@login_required
def runbook_step_add(rb_id: int):
    from ...models.runbook import Runbook, RunbookStep
    rb   = Runbook.query.get_or_404(rb_id)
    data = request.get_json(silent=True) or request.form

    step_type = (data.get("step_type") or "playbook").strip()
    pb_id     = _int_or_none(data.get("playbook_id"))
    tmpl_id   = _int_or_none(data.get("template_id"))

    if step_type == "playbook" and not pb_id:
        return jsonify({"success": False, "message": "Select a playbook for this step."})
    if step_type == "template" and not tmpl_id:
        return jsonify({"success": False, "message": "Select a template for this step."})

    max_pos = max((s.position for s in rb.steps), default=0)
    step = RunbookStep(
        runbook_id  = rb.id,
        step_type   = step_type,
        playbook_id = pb_id  if step_type == "playbook" else None,
        template_id = tmpl_id if step_type == "template" else None,
        position    = max_pos + 1,
        label       = (data.get("label") or "").strip() or None,
        notes       = (data.get("notes") or "").strip() or None,
        is_required = _bool(data.get("is_required", False)),
        is_enabled  = _bool(data.get("is_enabled", True)),
        on_failure  = (data.get("on_failure") or "stop").strip(),
    )
    db.session.add(step)
    db.session.commit()
    commit_audit("runbook.step.add", target=rb.name,
                 details=f"pos={step.position} type={step_type}", result="success")
    return jsonify({"success": True, "message": "Step added."})


@ops_bp.route("/ansible/runbooks/<int:rb_id>/steps/<int:step_id>/update", methods=["POST"])
@login_required
def runbook_step_update(rb_id: int, step_id: int):
    from ...models.runbook import RunbookStep
    step = RunbookStep.query.get_or_404(step_id)
    if step.runbook_id != rb_id:
        return jsonify({"success": False, "message": "Step not found."})

    data = request.get_json(silent=True) or request.form
    step_type = (data.get("step_type") or step.step_type).strip()

    step.step_type   = step_type
    step.playbook_id = _int_or_none(data.get("playbook_id")) if step_type == "playbook" else None
    step.template_id = _int_or_none(data.get("template_id")) if step_type == "template" else None
    step.label       = (data.get("label") or "").strip() or None
    step.notes       = (data.get("notes") or "").strip() or None
    step.is_required = _bool(data.get("is_required", step.is_required))
    step.is_enabled  = _bool(data.get("is_enabled", step.is_enabled))
    step.on_failure  = (data.get("on_failure") or step.on_failure).strip()
    db.session.commit()
    commit_audit("runbook.step.update", target=str(rb_id),
                 details=f"step_id={step_id}", result="success")
    return jsonify({"success": True, "message": "Step updated."})


@ops_bp.route("/ansible/runbooks/<int:rb_id>/steps/<int:step_id>/delete", methods=["POST"])
@login_required
def runbook_step_delete(rb_id: int, step_id: int):
    from ...models.runbook import Runbook, RunbookStep
    step = RunbookStep.query.get_or_404(step_id)
    if step.runbook_id != rb_id:
        return jsonify({"success": False, "message": "Step not found."})

    rb = Runbook.query.get(rb_id)
    db.session.delete(step)
    db.session.flush()

    # Renumber remaining steps
    remaining = RunbookStep.query.filter_by(runbook_id=rb_id).order_by(RunbookStep.position).all()
    for i, s in enumerate(remaining, start=1):
        s.position = i
    db.session.commit()
    commit_audit("runbook.step.delete", target=rb.name if rb else str(rb_id),
                 details=f"step_id={step_id}", result="success")
    return jsonify({"success": True, "message": "Step removed."})


@ops_bp.route("/ansible/runbooks/<int:rb_id>/steps/<int:step_id>/move", methods=["POST"])
@login_required
def runbook_step_move(rb_id: int, step_id: int):
    from ...models.runbook import RunbookStep
    data      = request.get_json(silent=True) or request.form
    direction = (data.get("direction") or "").strip()  # "up" | "down"

    step = RunbookStep.query.get_or_404(step_id)
    if step.runbook_id != rb_id:
        return jsonify({"success": False, "message": "Step not found."})

    siblings = (
        RunbookStep.query
        .filter_by(runbook_id=rb_id)
        .order_by(RunbookStep.position)
        .all()
    )
    idx = next((i for i, s in enumerate(siblings) if s.id == step_id), None)
    if idx is None:
        return jsonify({"success": False, "message": "Step not found in list."})

    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(siblings):
        return jsonify({"success": False, "message": "Cannot move further."})

    # Swap positions
    siblings[idx].position, siblings[swap_idx].position = (
        siblings[swap_idx].position, siblings[idx].position
    )
    db.session.commit()
    return jsonify({"success": True})


# ── Runbook launch page ─────────────────────────────────────────────────────── #

@ops_bp.route("/ansible/runbooks/<int:rb_id>/launch")
@login_required
def runbook_launch(rb_id: int):
    from ...models.runbook import Runbook
    from ...models.environment import Environment
    rb = Runbook.query.get_or_404(rb_id)
    envs = Environment.query.filter_by(is_active=True).order_by(Environment.name).all()
    cfg  = _get_cfg()
    return render_template(
        "ops/runbook_launch.html",
        rb=rb,
        envs=envs,
        cfg=cfg,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


# ── Runbook execute (AJAX POST) ─────────────────────────────────────────────── #

@ops_bp.route("/ansible/runbooks/<int:rb_id>/execute", methods=["POST"])
@login_required
def runbook_execute(rb_id: int):
    import json as _json
    from ...models.runbook import Runbook, RunbookJob, RunbookStepExecution
    from ...models.playbook import Playbook, PlaybookJobTemplate

    rb  = Runbook.query.get_or_404(rb_id)
    cfg = _get_cfg()
    if cfg is None or not cfg.enabled:
        return jsonify({"success": False, "message": "Ansible is not configured."})
    if cfg.connection_status != "Connected":
        return jsonify({"success": False, "message": "Control node is not connected."})

    data = request.get_json(silent=True) or request.form

    target_type  = (data.get("target_type") or "all").strip()
    target_value = (data.get("target_value") or "").strip() or None
    become       = _bool(data.get("become"))
    check_mode   = _bool(data.get("check_mode"))
    extra_vars   = (data.get("extra_vars") or "").strip() or None

    # Build limit expression from target
    limit_expression = _build_limit(target_type, target_value)

    # Operator-skipped optional step IDs
    skipped_ids: set[int] = set()
    raw_skipped = data.get("skipped_steps") or data.getlist("skipped_steps[]") if hasattr(data, "getlist") else []
    if isinstance(raw_skipped, str):
        try:
            raw_skipped = _json.loads(raw_skipped)
        except Exception:
            raw_skipped = [raw_skipped]
    for v in (raw_skipped or []):
        sid = _int_or_none(v)
        if sid:
            skipped_ids.add(sid)

    # Only include enabled steps
    enabled_steps = [s for s in rb.steps if s.is_enabled]
    if not enabled_steps:
        return jsonify({"success": False, "message": "This runbook has no enabled steps."})

    now = datetime.now(timezone.utc)
    job = RunbookJob(
        runbook_id       = rb.id,
        runbook_name     = rb.name,
        triggered_by     = _username(),
        status           = "pending",
        target_type      = target_type,
        target_value     = target_value,
        limit_expression = limit_expression,
        become           = become,
        check_mode       = check_mode,
        extra_vars       = extra_vars,
        created_at       = now,
    )
    db.session.add(job)
    db.session.flush()  # get job.id

    for step in enabled_steps:
        is_skipped = (step.id in skipped_ids) and not step.is_required

        # Resolve snapshot values
        playbook_path = ""
        playbook_name = ""
        template_name = ""
        exec_params   = {}

        if step.step_type == "playbook" and step.playbook:
            pb = step.playbook
            playbook_path = pb.relative_path
            playbook_name = pb.name
            exec_params   = {
                "requires_become": pb.requires_become,
                "forks": 5, "verbosity": 0,
            }
        elif step.step_type == "template" and step.template:
            tmpl = step.template
            template_name = tmpl.name
            settings      = tmpl.get_settings()
            playbook_path = settings.get("playbook_path") or ""
            playbook_name = settings.get("playbook_name") or playbook_path.rsplit("/", 1)[-1]
            exec_params   = settings

        step_exec = RunbookStepExecution(
            runbook_job_id   = job.id,
            runbook_step_id  = step.id,
            position         = step.position,
            step_type        = step.step_type,
            label            = step.label or step.display_name,
            playbook_path    = playbook_path,
            playbook_name    = playbook_name,
            template_name    = template_name,
            execution_params = _json.dumps(exec_params),
            on_failure       = step.on_failure,
            status           = "skipped" if is_skipped else "pending",
            skipped          = is_skipped,
        )
        db.session.add(step_exec)

    db.session.commit()

    app = current_app._get_current_object()

    def _run():
        from ...services.runbook_service import execute_runbook
        try:
            execute_runbook(job.id, app)
        except Exception:
            logger.exception("execute_runbook(%d) unhandled exception", job.id)

    threading.Thread(target=_run, daemon=True).start()

    commit_audit("runbook.execute", target=rb.name,
                 details=f"job_id={job.id} target={target_type}:{target_value}",
                 result="success")
    return jsonify({
        "success":  True,
        "job_id":   job.id,
        "message":  f"Runbook '{rb.name}' started as Job #{job.id}.",
        "redirect": url_for("ops.runbook_job_detail", job_id=job.id),
    })


# ── Runbook job detail ──────────────────────────────────────────────────────── #

@ops_bp.route("/ansible/runbook-jobs/<int:job_id>")
@login_required
def runbook_job_detail(job_id: int):
    from ...models.runbook import RunbookJob
    job = RunbookJob.query.get_or_404(job_id)
    return render_template(
        "ops/runbook_job.html",
        job=job,
        cfg=_get_cfg(),
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


@ops_bp.route("/ansible/runbook-jobs/<int:job_id>/status")
@login_required
def runbook_job_status(job_id: int):
    from ...models.runbook import RunbookJob
    job = RunbookJob.query.get_or_404(job_id)

    steps_data = []
    for s in job.step_executions:
        d = {
            "id":             s.id,
            "position":       s.position,
            "label":          s.display_name,
            "step_type":      s.step_type,
            "status":         s.status,
            "skipped":        s.skipped,
            "on_failure":     s.on_failure,
            "playbook_job_id": s.playbook_job_id,
            "started_at":     s.started_at.isoformat() if s.started_at else None,
            "finished_at":    s.finished_at.isoformat() if s.finished_at else None,
            "duration":       s.duration_seconds,
            "error_message":  s.error_message,
        }
        steps_data.append(d)

    return jsonify({
        "status":      job.status,
        "started_at":  job.started_at.isoformat()  if job.started_at  else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "duration":    job.duration_seconds,
        "error":       job.error_message,
        "steps":       steps_data,
    })


# ── Helper ─────────────────────────────────────────────────────────────────── #

def _build_limit(target_type: str, target_value: str | None) -> str | None:
    """Translate UI target selection into an Ansible --limit expression."""
    if target_type == "all" or not target_value:
        return None
    if target_type == "server":
        return target_value.strip()
    if target_type in ("group", "environment"):
        return target_value.strip()
    return target_value or None


# ═══════════════════════════════════════════════════════════════════════════════
# CATALOG
# ═══════════════════════════════════════════════════════════════════════════════

@ops_bp.route("/ansible/catalog")
@login_required
def catalog():
    from ...models.playbook import Playbook, PlaybookJob
    cfg = _get_cfg()

    search   = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    tag      = request.args.get("tag", "").strip()
    hide_int = request.args.get("hide_internal", "0") == "1"

    q = Playbook.query
    if search:
        like = f"%{search}%"
        q = q.filter(
            db.or_(Playbook.name.ilike(like), Playbook.relative_path.ilike(like),
                   Playbook.description.ilike(like))
        )
    if category:
        q = q.filter(Playbook.category.ilike(f"%{category}%"))
    if tag:
        q = q.filter(Playbook.tags.ilike(f"%{tag}%"))
    if hide_int:
        q = q.filter(Playbook.is_internal == False)  # noqa: E712

    playbooks = q.order_by(Playbook.category, Playbook.name).all()

    # Summary counts
    all_pbs = Playbook.query.all()
    categories = sorted({pb.category for pb in all_pbs if pb.category})
    all_tags   = sorted({t for pb in all_pbs for t in pb.tag_list})

    # Last 5 jobs for the sidebar
    recent_jobs = (
        PlaybookJob.query
        .order_by(PlaybookJob.created_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "ops/catalog.html",
        playbooks=playbooks,
        cfg=cfg,
        categories=categories,
        all_tags=all_tags,
        recent_jobs=recent_jobs,
        search=search,
        category=category,
        tag=tag,
        hide_internal=hide_int,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


@ops_bp.route("/ansible/catalog/discover", methods=["POST"])
@login_required
def catalog_discover():
    """AJAX: SSH to control node and refresh the playbook catalog."""
    cfg = _get_cfg()
    if cfg is None:
        return jsonify({"success": False, "message": "Ansible not configured."})
    if not cfg.enabled or cfg.connection_status != "Connected":
        return jsonify({"success": False, "message": "Control node not connected."})

    if not _discover_lock.acquire(blocking=False):
        return jsonify({"success": False, "message": "Discovery already in progress."})

    # Pass the primary key only.  commit_audit() below calls db.session.commit()
    # which marks every tracked SQLAlchemy instance (including cfg) as expired.
    # The request context then ends, fully detaching cfg.  If the thread received
    # the object instead of its ID it would raise DetachedInstanceError on the
    # first attribute access and produce zero playbooks with no UI feedback.
    cfg_id = cfg.id
    app    = current_app._get_current_object()

    def _run():
        try:
            from ...services.playbook_service import discover_playbooks
            summary = discover_playbooks(cfg_id, app)

            found   = summary.get("found", 0)
            new     = summary.get("new", 0)
            updated = summary.get("updated", 0)
            errors  = summary.get("errors", [])

            # Audit the actual outcome with counts so the log is useful.
            details = f"{found} playbook(s) discovered — new={new} updated={updated}"
            if errors:
                details += f"; errors: {'; '.join(str(e) for e in errors[:2])}"

            with app.app_context():
                from ...audit import commit_audit as _ca
                _ca(
                    "playbook.catalog.discover",
                    result  = "failure" if errors and found == 0 else "success",
                    details = details,
                )

            if errors and found == 0:
                logger.error("Catalog discovery failed: %s", errors)
            elif errors:
                logger.warning(
                    "Catalog discovery finished with warnings: found=%d new=%d updated=%d errors=%s",
                    found, new, updated, errors,
                )
            else:
                logger.info(
                    "Catalog discovery finished: found=%d new=%d updated=%d",
                    found, new, updated,
                )
        except Exception:
            logger.exception("Catalog discovery: unhandled exception in background thread")
        finally:
            _discover_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"success": True, "message": "Discovery started. Refresh the page in a moment."})


@ops_bp.route("/ansible/catalog/<int:pb_id>/toggle", methods=["POST"])
@login_required
def catalog_toggle(pb_id: int):
    """AJAX: enable or disable a playbook in the catalog."""
    from ...models.playbook import Playbook
    pb = Playbook.query.get_or_404(pb_id)
    pb.is_enabled = not pb.is_enabled
    db.session.commit()
    commit_audit(
        "playbook.catalog.toggle",
        target=pb.relative_path,
        details=f"enabled={pb.is_enabled}",
        result="success",
    )
    return jsonify({"success": True, "enabled": pb.is_enabled})


# ═══════════════════════════════════════════════════════════════════════════════
# JOB LAUNCH
# ═══════════════════════════════════════════════════════════════════════════════

@ops_bp.route("/ansible/jobs/launch", methods=["POST"])
@login_required
def launch():
    """
    AJAX: create and launch a PlaybookJob from the wizard payload.

    Payload (JSON or form):
      playbook_id, playbook_path, playbook_name,
      inventory_type, inventory_value,
      target_type, target_value, limit_expression, host_count,
      become, check_mode, diff_mode, dry_run, forks, verbosity,
      tags, skip_tags, extra_vars,
      production_confirmed, template_id (optional)
    """
    from ...models.playbook import PlaybookJob

    data = request.get_json(silent=True) or request.form

    # Basic validation
    playbook_path = (data.get("playbook_path") or "").strip()
    if not playbook_path:
        return jsonify({"success": False, "message": "No playbook path provided."})

    cfg = _get_cfg()
    if cfg is None:
        return jsonify({"success": False, "message": "Ansible not configured."})
    if not cfg.enabled or cfg.connection_status != "Connected":
        return jsonify({"success": False, "message": "Control node not connected."})

    limit_expr   = (data.get("limit_expression") or "").strip()
    target_value = (data.get("target_value") or "").strip()

    # Production safety check
    prod_hit = _detect_production(limit_expr, target_value)
    if prod_hit and not _bool(data.get("production_confirmed")):
        return jsonify({
            "success":          False,
            "requires_confirm": True,
            "message":          "This playbook targets Production hosts. Please confirm.",
        })

    # Duplicate-run guard: same playbook already running against same limit
    existing = (
        PlaybookJob.query
        .filter(
            PlaybookJob.playbook_path == playbook_path,
            PlaybookJob.status.in_(["pending", "running"]),
            PlaybookJob.limit_expression == (limit_expr or None),
        )
        .first()
    )
    if existing:
        return jsonify({
            "success": False,
            "message": f"Job #{existing.id} is already running this playbook against the same hosts.",
        })

    now = datetime.now(timezone.utc)
    job = PlaybookJob(
        playbook_id          = _int_or_none(data.get("playbook_id")),
        playbook_path        = playbook_path,
        playbook_name        = (data.get("playbook_name") or playbook_path.rsplit("/", 1)[-1]).strip(),
        template_id          = _int_or_none(data.get("template_id")),
        triggered_by         = _username(),
        status               = "pending",
        target_type          = (data.get("target_type") or "").strip() or None,
        target_value         = target_value or None,
        limit_expression     = limit_expr or None,
        host_count           = _int_or_none(data.get("host_count")),
        inventory_type       = (data.get("inventory_type") or "default").strip(),
        inventory_value      = (data.get("inventory_value") or "").strip() or None,
        become               = _bool(data.get("become")),
        check_mode           = _bool(data.get("check_mode")),
        diff_mode            = _bool(data.get("diff_mode")),
        dry_run              = _bool(data.get("dry_run")),
        forks                = int(data.get("forks") or 5),
        verbosity            = int(data.get("verbosity") or 0),
        tags                 = (data.get("tags") or "").strip() or None,
        skip_tags            = (data.get("skip_tags") or "").strip() or None,
        extra_vars           = (data.get("extra_vars") or "").strip() or None,
        production_confirmed = _bool(data.get("production_confirmed")) or prod_hit,
        created_at           = now,
    )
    db.session.add(job)
    db.session.commit()

    app = current_app._get_current_object()

    def _run():
        from ...services.playbook_service import launch_job
        try:
            launch_job(job.id, app)
        except Exception:
            logger.exception("launch_job(%d) failed", job.id)

    threading.Thread(target=_run, daemon=True).start()

    log_action(
        "playbook.job.create",
        target  = job.playbook_name,
        details = f"job_id={job.id} limit={job.limit_expression!r} become={job.become}",
        result  = "success",
    )
    db.session.commit()

    return jsonify({
        "success": True,
        "job_id":  job.id,
        "message": f"Job #{job.id} started.",
        "redirect": url_for("ops.job_detail", job_id=job.id),
    })


# ═══════════════════════════════════════════════════════════════════════════════
# JOBS LIST
# ═══════════════════════════════════════════════════════════════════════════════

@ops_bp.route("/ansible/jobs")
@login_required
def jobs():
    from ...models.playbook import PlaybookJob

    status  = request.args.get("status",   "").strip()
    search  = request.args.get("q",        "").strip()
    user    = request.args.get("user",     "").strip()
    pb_name = request.args.get("playbook", "").strip()
    page    = max(1, request.args.get("page", 1, type=int))
    per_page = 25

    q = PlaybookJob.query
    if status:
        q = q.filter(PlaybookJob.status == status)
    if search:
        like = f"%{search}%"
        q = q.filter(
            db.or_(PlaybookJob.playbook_name.ilike(like),
                   PlaybookJob.playbook_path.ilike(like),
                   PlaybookJob.limit_expression.ilike(like))
        )
    if user:
        q = q.filter(PlaybookJob.triggered_by.ilike(f"%{user}%"))
    if pb_name:
        q = q.filter(PlaybookJob.playbook_name.ilike(f"%{pb_name}%"))

    total   = q.count()
    job_rows = (
        q.order_by(PlaybookJob.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    # Status counts for filter tabs
    status_counts = {
        "running":   PlaybookJob.query.filter(PlaybookJob.status == "running").count(),
        "pending":   PlaybookJob.query.filter(PlaybookJob.status == "pending").count(),
        "completed": PlaybookJob.query.filter(PlaybookJob.status == "completed").count(),
        "failed":    PlaybookJob.query.filter(PlaybookJob.status == "failed").count(),
        "cancelled": PlaybookJob.query.filter(PlaybookJob.status == "cancelled").count(),
    }

    from ...models.playbook import Playbook
    import json as _json
    playbooks_qs = Playbook.query.filter_by(is_enabled=True).order_by(Playbook.name).all()
    playbooks_json = _json.dumps([pb.to_dict() for pb in playbooks_qs])

    return render_template(
        "ops/jobs.html",
        jobs=job_rows,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=max(1, -(-total // per_page)),
        status_filter=status,
        status_counts=status_counts,
        search=search,
        cfg=_get_cfg(),
        playbooks_json=playbooks_json,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# JOB DETAIL
# ═══════════════════════════════════════════════════════════════════════════════

@ops_bp.route("/ansible/jobs/<int:job_id>")
@login_required
def job_detail(job_id: int):
    from ...models.playbook import PlaybookJob
    job = PlaybookJob.query.get_or_404(job_id)
    return render_template(
        "ops/job_detail.html",
        job=job,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


@ops_bp.route("/ansible/jobs/<int:job_id>/output")
@login_required
def job_output(job_id: int):
    """AJAX: stream log output from a given byte offset."""
    from ...models.playbook import PlaybookJob
    job    = PlaybookJob.query.get_or_404(job_id)
    offset = request.args.get("offset", 0, type=int)
    raw    = job.log_output or ""
    chunk  = raw[offset:]
    return jsonify({
        "output":    chunk,
        "offset":    offset + len(chunk),
        "done":      job.status not in ("pending", "running"),
        "status":    job.status,
        "exit_code": job.exit_code,
        "hosts_ok":  job.hosts_ok,
        "hosts_failed": job.hosts_failed,
        "hosts_changed": job.hosts_changed,
    })


@ops_bp.route("/ansible/catalog/<int:pb_id>/json")
@login_required
def catalog_json(pb_id: int):
    """AJAX: return a single enabled playbook as JSON (for the jobs wizard)."""
    from ...models.playbook import Playbook
    pb = Playbook.query.get_or_404(pb_id)
    return jsonify(pb.to_dict())


@ops_bp.route("/ansible/jobs/<int:job_id>/rerun", methods=["POST"])
@login_required
def job_rerun(job_id: int):
    """AJAX: clone a completed/failed/cancelled job and re-run it."""
    from ...models.playbook import PlaybookJob

    orig = PlaybookJob.query.get_or_404(job_id)
    if orig.status in ("pending", "running"):
        return jsonify({"success": False, "message": "Job is still active — stop it first."})

    cfg = _get_cfg()
    if cfg is None or not cfg.enabled or cfg.connection_status != "Connected":
        return jsonify({"success": False, "message": "Control node not connected."})

    now = datetime.now(timezone.utc)
    job = PlaybookJob(
        playbook_id      = orig.playbook_id,
        playbook_path    = orig.playbook_path,
        playbook_name    = orig.playbook_name,
        template_id      = orig.template_id,
        triggered_by     = _username(),
        status           = "pending",
        target_type      = orig.target_type,
        target_value     = orig.target_value,
        limit_expression = orig.limit_expression,
        host_count       = orig.host_count,
        inventory_type   = orig.inventory_type,
        inventory_value  = orig.inventory_value,
        become           = orig.become,
        check_mode       = orig.check_mode,
        diff_mode        = orig.diff_mode,
        forks            = orig.forks,
        verbosity        = orig.verbosity,
        tags             = orig.tags,
        skip_tags        = orig.skip_tags,
        extra_vars       = orig.extra_vars,
        created_at       = now,
    )
    db.session.add(job)
    db.session.commit()

    app = current_app._get_current_object()

    def _run():
        from ...services.playbook_service import launch_job
        try:
            launch_job(job.id, app)
        except Exception:
            logger.exception("job_rerun launch_job(%d) failed", job.id)

    threading.Thread(target=_run, daemon=True).start()

    commit_audit(
        "playbook.job.rerun",
        target  = job.playbook_name,
        details = f"new_job_id={job.id} original_job_id={job_id}",
        result  = "success",
    )
    return jsonify({
        "success":  True,
        "job_id":   job.id,
        "message":  f"Job #{job.id} started.",
        "redirect": url_for("ops.job_detail", job_id=job.id),
    })


@ops_bp.route("/ansible/inventory/refresh", methods=["POST"])
@login_required
def inventory_refresh():
    """AJAX: re-run validate_inventory() and persist the host count."""
    cfg = _get_cfg()
    if cfg is None or not cfg.enabled:
        return jsonify({"success": False, "message": "Ansible not configured."})
    if cfg.connection_status != "Connected":
        return jsonify({"success": False, "message": "Control node not connected."})

    try:
        from ...services.ansible_service import AnsibleService
        svc    = AnsibleService.from_config(cfg)
        result = svc.validate_inventory()
        if result.get("success"):
            cfg.last_inventory_hosts = result["host_count"]
            db.session.commit()
        return jsonify({
            "success":    result.get("success", False),
            "host_count": result.get("host_count", 0),
            "message":    (
                f"{result['host_count']} host(s) found."
                if result.get("success")
                else (result.get("errors") or ["Inventory validation failed"])[0]
            ),
        })
    except Exception as exc:
        logger.exception("inventory_refresh failed")
        return jsonify({"success": False, "message": str(exc)})


@ops_bp.route("/ansible/jobs/<int:job_id>/cancel", methods=["POST"])
@login_required
def job_cancel(job_id: int):
    """AJAX: cancel a running job."""
    app = current_app._get_current_object()
    from ...services.playbook_service import cancel_job as _cancel
    ok = _cancel(job_id, app)
    if ok:
        commit_audit(
            "playbook.job.cancel",
            target=f"job:{job_id}",
            result="success",
        )
        return jsonify({"success": True, "message": f"Job #{job_id} cancelled."})
    return jsonify({"success": False, "message": "Job cannot be cancelled (not running)."})


@ops_bp.route("/ansible/jobs/<int:job_id>/download")
@login_required
def job_download(job_id: int):
    """Download the full job log as a plain-text file."""
    from ...models.playbook import PlaybookJob
    from ...services.playbook_service import strip_ansi
    job  = PlaybookJob.query.get_or_404(job_id)
    text = strip_ansi(job.log_output or "— No output captured —")
    filename = f"lop-job-{job.id}-{job.playbook_name or 'output'}.txt"
    return Response(
        text,
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SAVED TEMPLATES
# ═══════════════════════════════════════════════════════════════════════════════

@ops_bp.route("/ansible/templates")
@login_required
def templates():
    from ...models.playbook import PlaybookJobTemplate
    tmpl_list = (
        PlaybookJobTemplate.query
        .order_by(PlaybookJobTemplate.name)
        .all()
    )
    from ...models.playbook import Playbook
    cfg = _get_cfg()
    playbooks = Playbook.query.filter_by(is_enabled=True).order_by(Playbook.name).all()
    return render_template(
        "ops/templates.html",
        templates=tmpl_list,
        cfg=cfg,
        playbooks=playbooks,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


@ops_bp.route("/ansible/templates/save", methods=["POST"])
@login_required
def template_save():
    """AJAX: create or update a saved template."""
    from ...models.playbook import PlaybookJobTemplate, Playbook
    data = request.get_json(silent=True) or request.form

    tmpl_id = _int_or_none(data.get("id"))
    name    = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "message": "Template name is required."})

    now = datetime.now(timezone.utc)
    if tmpl_id:
        t = PlaybookJobTemplate.query.get(tmpl_id)
        if t is None:
            return jsonify({"success": False, "message": "Template not found."})
        action = "playbook.template.update"
    else:
        t = PlaybookJobTemplate(created_by=_username(), created_at=now)
        db.session.add(t)
        action = "playbook.template.create"

    t.name        = name
    t.description = (data.get("description") or "").strip() or None
    t.playbook_id = _int_or_none(data.get("playbook_id"))
    t.updated_at  = now

    # Store all execution options
    settings = {
        k: data.get(k)
        for k in (
            "playbook_path", "playbook_name",
            "inventory_type", "inventory_value",
            "target_type", "target_value", "limit_expression",
            "become", "check_mode", "diff_mode", "dry_run",
            "forks", "verbosity", "tags", "skip_tags", "extra_vars",
        )
    }
    t.set_settings(settings)
    db.session.commit()

    commit_audit(action, target=name, result="success")
    return jsonify({"success": True, "id": t.id, "message": f"Template '{name}' saved."})


@ops_bp.route("/ansible/templates/<int:tmpl_id>/delete", methods=["POST"])
@login_required
def template_delete(tmpl_id: int):
    from ...models.playbook import PlaybookJobTemplate
    t = PlaybookJobTemplate.query.get_or_404(tmpl_id)
    name = t.name
    db.session.delete(t)
    db.session.commit()
    commit_audit("playbook.template.delete", target=name, result="success")
    return jsonify({"success": True, "message": f"Template '{name}' deleted."})


@ops_bp.route("/ansible/templates/<int:tmpl_id>/launch", methods=["POST"])
@login_required
def template_launch(tmpl_id: int):
    """One-click launch from a saved template."""
    from ...models.playbook import PlaybookJobTemplate
    t = PlaybookJobTemplate.query.get_or_404(tmpl_id)
    settings = t.get_settings()
    settings["template_id"] = tmpl_id
    settings["playbook_id"] = t.playbook_id
    settings["production_confirmed"] = request.form.get("production_confirmed", "0")

    # Delegate to launch() by constructing a local POST request payload
    with current_app.test_request_context(
        "/ansible/jobs/launch",
        method="POST",
        json=settings,
    ):
        # Can't call launch() directly — use the service layer
        pass

    # Actually just call the launch logic inline
    from ...models.playbook import PlaybookJob
    from ...services.playbook_service import launch_job as _launch

    playbook_path = (settings.get("playbook_path") or "").strip()
    if not playbook_path:
        return jsonify({"success": False, "message": "Template has no playbook path."})

    cfg = _get_cfg()
    if cfg is None or not cfg.enabled:
        return jsonify({"success": False, "message": "Ansible not configured."})

    now = datetime.now(timezone.utc)
    job = PlaybookJob(
        playbook_id   = t.playbook_id,
        playbook_path = playbook_path,
        playbook_name = settings.get("playbook_name") or playbook_path.rsplit("/", 1)[-1],
        template_id   = tmpl_id,
        triggered_by  = _username(),
        status        = "pending",
        target_type   = settings.get("target_type"),
        target_value  = settings.get("target_value"),
        limit_expression = settings.get("limit_expression"),
        inventory_type   = settings.get("inventory_type") or "default",
        inventory_value  = settings.get("inventory_value"),
        become      = _bool(settings.get("become")),
        check_mode  = _bool(settings.get("check_mode")),
        diff_mode   = _bool(settings.get("diff_mode")),
        forks       = int(settings.get("forks") or 5),
        verbosity   = int(settings.get("verbosity") or 0),
        tags        = settings.get("tags"),
        skip_tags   = settings.get("skip_tags"),
        extra_vars  = settings.get("extra_vars"),
        created_at  = now,
    )
    db.session.add(job)
    db.session.commit()

    app = current_app._get_current_object()
    threading.Thread(target=_launch, args=(job.id, app), daemon=True).start()

    commit_audit("playbook.template.launch", target=t.name,
                 details=f"job_id={job.id}", result="success")
    return jsonify({
        "success": True,
        "job_id": job.id,
        "redirect": url_for("ops.job_detail", job_id=job.id),
    })


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULES
# ═══════════════════════════════════════════════════════════════════════════════

@ops_bp.route("/ansible/schedules")
@login_required
def schedules():
    from ...models.playbook import PlaybookSchedule, PlaybookJobTemplate
    sched_list = (
        PlaybookSchedule.query
        .order_by(PlaybookSchedule.name)
        .all()
    )
    tmpl_list = PlaybookJobTemplate.query.order_by(PlaybookJobTemplate.name).all()
    return render_template(
        "ops/schedules.html",
        schedules=sched_list,
        templates=tmpl_list,
        app_name=current_app.config["APP_NAME"],
        app_version=current_app.config["APP_VERSION"],
    )


@ops_bp.route("/ansible/schedules/save", methods=["POST"])
@login_required
def schedule_save():
    from ...models.playbook import PlaybookSchedule
    from ...scheduler import reschedule_playbooks
    data    = request.get_json(silent=True) or request.form
    sched_id = _int_or_none(data.get("id"))
    name    = (data.get("name") or "").strip()
    tmpl_id = _int_or_none(data.get("template_id"))
    stype   = (data.get("schedule_type") or "").strip()
    cron_ex = (data.get("cron_expression") or "").strip() or None

    if not name:
        return jsonify({"success": False, "message": "Schedule name is required."})
    if not tmpl_id:
        return jsonify({"success": False, "message": "A job template is required."})
    if not stype:
        return jsonify({"success": False, "message": "Schedule type is required."})

    now = datetime.now(timezone.utc)
    if sched_id:
        s = PlaybookSchedule.query.get(sched_id)
        if s is None:
            return jsonify({"success": False, "message": "Schedule not found."})
        action = "playbook.schedule.update"
    else:
        s = PlaybookSchedule(created_by=_username(), created_at=now)
        db.session.add(s)
        action = "playbook.schedule.create"

    s.name            = name
    s.template_id     = tmpl_id
    s.schedule_type   = stype
    s.cron_expression = cron_ex
    s.is_enabled      = _bool(data.get("is_enabled", True))
    s.updated_at      = now
    db.session.commit()

    # Sync APScheduler
    try:
        app = current_app._get_current_object()
        reschedule_playbooks(app)
    except Exception as exc:
        logger.warning("reschedule_playbooks failed: %s", exc)

    commit_audit(action, target=name, result="success")
    return jsonify({"success": True, "id": s.id, "message": f"Schedule '{name}' saved."})


@ops_bp.route("/ansible/schedules/<int:sched_id>/toggle", methods=["POST"])
@login_required
def schedule_toggle(sched_id: int):
    from ...models.playbook import PlaybookSchedule
    from ...scheduler import reschedule_playbooks
    s = PlaybookSchedule.query.get_or_404(sched_id)
    s.is_enabled = not s.is_enabled
    db.session.commit()
    try:
        reschedule_playbooks(current_app._get_current_object())
    except Exception:
        pass
    commit_audit("playbook.schedule.toggle", target=s.name,
                 details=f"enabled={s.is_enabled}", result="success")
    return jsonify({"success": True, "enabled": s.is_enabled})


@ops_bp.route("/ansible/schedules/<int:sched_id>/delete", methods=["POST"])
@login_required
def schedule_delete(sched_id: int):
    from ...models.playbook import PlaybookSchedule
    s = PlaybookSchedule.query.get_or_404(sched_id)
    name = s.name
    db.session.delete(s)
    db.session.commit()
    commit_audit("playbook.schedule.delete", target=name, result="success")
    return jsonify({"success": True, "message": f"Schedule '{name}' deleted."})


@ops_bp.route("/ansible/schedules/<int:sched_id>/run-now", methods=["POST"])
@login_required
def schedule_run_now(sched_id: int):
    """Trigger a scheduled job immediately (one-off)."""
    from ...models.playbook import PlaybookSchedule
    s = PlaybookSchedule.query.get_or_404(sched_id)
    # Delegate to template_launch logic
    from ...models.playbook import PlaybookJob
    from ...services.playbook_service import launch_job as _launch

    t = s.template
    if t is None:
        return jsonify({"success": False, "message": "Template not found."})
    settings = t.get_settings()
    playbook_path = (settings.get("playbook_path") or "").strip()
    if not playbook_path:
        return jsonify({"success": False, "message": "Template has no playbook path."})

    cfg = _get_cfg()
    if cfg is None or not cfg.enabled:
        return jsonify({"success": False, "message": "Ansible not configured."})

    now = datetime.now(timezone.utc)
    job = PlaybookJob(
        playbook_id   = t.playbook_id,
        playbook_path = playbook_path,
        playbook_name = settings.get("playbook_name") or playbook_path.rsplit("/", 1)[-1],
        template_id   = t.id,
        triggered_by  = f"schedule:{s.name}",
        status        = "pending",
        limit_expression = settings.get("limit_expression"),
        inventory_type   = settings.get("inventory_type") or "default",
        inventory_value  = settings.get("inventory_value"),
        become      = _bool(settings.get("become")),
        check_mode  = _bool(settings.get("check_mode")),
        forks       = int(settings.get("forks") or 5),
        verbosity   = int(settings.get("verbosity") or 0),
        tags        = settings.get("tags"),
        skip_tags   = settings.get("skip_tags"),
        extra_vars  = settings.get("extra_vars"),
        created_at  = now,
    )
    db.session.add(job)
    s.last_run_at = now
    db.session.commit()

    app = current_app._get_current_object()
    threading.Thread(target=_launch, args=(job.id, app), daemon=True).start()
    commit_audit("playbook.schedule.run_now", target=s.name,
                 details=f"job_id={job.id}", result="success")
    return jsonify({"success": True, "job_id": job.id,
                    "redirect": url_for("ops.job_detail", job_id=job.id)})


# ═══════════════════════════════════════════════════════════════════════════════
# HOST SELECTOR API
# ═══════════════════════════════════════════════════════════════════════════════

@ops_bp.route("/ansible/api/hosts")
@login_required
def api_hosts():
    """
    AJAX: return servers for the launch wizard target-host selector.
    Supports ?env_id=&location_id=&q= for filtering.
    """
    from ...models.server import Server
    from ...models.environment import Environment
    from ...models.location import Location

    env_id  = request.args.get("env_id",      type=int)
    loc_id  = request.args.get("location_id", type=int)
    search  = request.args.get("q", "").strip()

    from sqlalchemy.orm import joinedload
    q = Server.query.options(joinedload(Server.environment)).filter(Server.status != "decommissioned")
    if env_id:
        q = q.filter(Server.environment_id == env_id)
    if loc_id:
        q = q.filter(Server.location_id == loc_id)
    if search:
        like = f"%{search}%"
        q = q.filter(
            db.or_(Server.hostname.ilike(like), Server.fqdn.ilike(like),
                   Server.ip_address.ilike(like))
        )

    servers = q.order_by(Server.hostname).limit(200).all()
    envs    = Environment.query.filter_by(is_active=True).order_by(Environment.name).all()
    locs    = Location.query.filter_by(is_active=True).order_by(Location.name).all()

    return jsonify({
        "servers":      [{"id": s.id, "hostname": s.hostname, "fqdn": s.fqdn,
                          "ip": s.ip_address, "env": s.environment.name if s.environment else ""} for s in servers],
        "environments": [{"id": e.id, "name": e.name, "label": e.label} for e in envs],
        "locations":    [{"id": l.id, "name": l.name} for l in locs],
        "total":        q.count(),
    })


# ── Internal helpers ───────────────────────────────────────────────────────── #

def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return bool(v)
    return str(v).lower() in ("1", "true", "yes", "on")


def _int_or_none(v) -> int | None:
    try:
        return int(v) if v is not None and str(v).strip() else None
    except (TypeError, ValueError):
        return None

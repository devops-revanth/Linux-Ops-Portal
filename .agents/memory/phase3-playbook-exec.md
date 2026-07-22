---
name: Phase 3 — Playbook Execution Engine
description: Architecture, file locations, and critical decisions for the AWX-style Ansible playbook execution module.
---

## What was built

New operational workspace at `/ansible/*` — entirely separate from Settings.

### New files
- `migrations/versions/i9j0k1l2m3n4_playbook_execution.py` — 4 new tables
- `app/models/playbook.py` — Playbook, PlaybookJob, PlaybookJobTemplate, PlaybookSchedule
- `app/services/playbook_service.py` — discovery, execution, cancellation, stats parsing
- `app/blueprints/ops/__init__.py` + `routes.py` — 20 routes on `ops_bp`
- `app/templates/ops/` — catalog.html, jobs.html, job_detail.html, templates.html, schedules.html

### Modified files
- `app/__init__.py` — registers `ops_bp`; added `lop_dt` as alias for `lop_ts` Jinja2 filter
- `app/models/__init__.py` — imports Playbook, PlaybookJob, PlaybookJobTemplate, PlaybookSchedule
- `app/templates/base.html` — added "Ansible" nav item with `bi-gear-wide-connected`; endpoint: `ops.catalog`
- `app/scheduler.py` — added `reschedule_playbooks()`, `_add_playbook_job()`, `_run_scheduled_playbook()`
- `app/static/css/lop.css` — added `.btn-xs`, `.lop-spin`, `.lop-pulse` animation utilities

## Architecture decisions

**Execution model:** LOP never runs Ansible locally. Uses paramiko SSH + PTY channel to run `ansible-playbook` on the configured control node.

**PID capture:** Wraps command as `bash -c 'echo "LOP_PID:$$"; exec ansible-playbook ...'`. The `LOP_PID:N` line is stripped from output and stored in `job.remote_pid` for SIGTERM cancellation.

**Output streaming:** Append-only SQL: `UPDATE playbook_jobs SET log_output = COALESCE(log_output, '') || :chunk`. Never re-loads the entire log. Frontend polls `/ansible/jobs/<id>/output?offset=N` every 2s, appends the returned chunk.

**Cancellation:** Sets `job.status = 'cancelled'` first (stops the streaming loop); then SSH `kill -SIGTERM <pid> 2>/dev/null` to the control node.

**Duplicate guard:** Before launch, checks for any `running|pending` job with same `playbook_path` and `limit_expression`.

**Production safety:** `_detect_production()` returns True if any target env name contains "prod". Returns `{requires_confirm: True}` to the wizard if confirmation not already set.

**Shell injection prevention:** `_q(s)` uses POSIX single-quoting (`'` + s.replace(`'`, `'\''`) + `'`). Note: the single-quote count in the result may be odd — that is correct for POSIX shell (e.g. `'test'\''s'` = `test's`).

**Scheduling:** APScheduler jobs created as `playbook_sched_<id>`. `reschedule_playbooks(app)` removes all `playbook_sched_*` jobs and re-adds all enabled schedules. Cron schedules use 5-field `trigger="cron"`, interval schedules use `trigger="interval"`.

**Template folder:** `ops_bp` uses `template_folder="../../templates"` (relative from the blueprint directory) because templates are kept in the top-level `app/templates/ops/` directory.

## Critical gotchas

- `ops/__init__.py` MUST `from . import routes` after Blueprint creation — otherwise no routes register and Flask silently shows 404.
- `lop_dt` filter is an alias of `lop_ts` — added in Phase 3. `lop_ts` is the canonical datetime filter.
- `PlaybookJobTemplate.get_settings()` / `set_settings()` use JSON — never access `settings` directly.
- `AnsibleService._exec` is a static/class method (lowercase) — check the signature before calling.
- `_parse_job_stats` uses `_RECAP_RE` which matches `hostname : ok=N changed=N unreachable=N failed=N`. Only the PLAY RECAP section is parsed — not individual task output.
- Stats are written to the job record in `_finish_progress` on the service side, not in the route.
- The `/ansible` blueprint conflicts only if the existing `ansible_bp` has routes at that prefix — it does not (all existing ansible routes use `/settings/ansible/*`).

## Security boundaries

- SSH passwords, private keys, vault passwords — never logged, never in error responses
- All execution is remote-only on the control node
- `_sanitize_error()` strips internal paths from exception messages
- Audit logging on all write operations: launch, cancel, toggle, template CRUD, schedule CRUD

**Why no WebSockets:** AJAX polling every 2s is sufficient for playbook output; avoids wsgi-layer complexity and proxy compatibility issues in the Replit preview environment.

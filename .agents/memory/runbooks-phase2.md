---
name: Runbooks Phase 2
description: Runbook feature implementation — models, routes, templates, migration, and execution engine.
---

## What was built
Four new models (`Runbook`, `RunbookStep`, `RunbookJob`, `RunbookStepExecution`) in `app/models/runbook.py`. Routes in `app/blueprints/ops/routes.py` (CRUD, step management, launch, execute, status poll). Migration `k1l2m3n4o5p6` (down_revision = `j0k1l2m3n4o5`).

## Templates (all in `app/templates/ops/`)
- `runbooks.html` — list; last-job status badge; clone/delete via fetch POST
- `runbook_detail.html` — metadata form saved via JSON POST to `/ansible/runbooks/save`; step builder modal toggles playbook vs template picker; move/edit/delete steps without page nav
- `runbook_launch.html` — target radio (all/environment/group/server), optional step checkboxes (required = disabled), collapsed Advanced (become, check_mode, extra_vars), POSTs JSON to `runbook_execute`, redirects to job detail
- `runbook_job.html` — step timeline; polls `/ansible/runbook-jobs/<id>/status` every 3 s while pending/running; reloads on completion; expandable log panels fetch `/ansible/jobs/<pjob_id>/output`

## Key decisions
- Execution reuses `playbook_service.launch_job()` sequentially in a background thread.
- Step executions snapshot playbook_name, template_name, display_name at launch time.
- Skipped optional steps get `status='skipped'` recorded rather than being omitted.
- `runbooks_placeholder.html` deleted once real template was in place.

**Why:** Avoids duplicating the AWX-integration code path. Snapshots ensure job history is self-contained even if playbooks/templates are later renamed or deleted.

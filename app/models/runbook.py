"""
Runbook models — Phase 2.

Four models cover the full runbook workflow:
  Runbook              — definition: ordered collection of playbooks/templates
  RunbookStep          — one step inside a runbook
  RunbookJob           — one execution of a runbook
  RunbookStepExecution — one step's execution within a RunbookJob
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..extensions import db

# Extensible step types: start with playbook + template, ready for
# WAIT / APPROVAL / NOTIFICATION / SCRIPT without a schema change.
STEP_TYPES = ("playbook", "template")
FAILURE_POLICIES = ("stop", "continue")


class Runbook(db.Model):
    __tablename__ = "runbooks"

    id:                 int = db.Column(db.Integer, primary_key=True)
    name:               str = db.Column(db.String(255), nullable=False)
    description:        str = db.Column(db.Text,        nullable=True)
    # ── Future-ready fields ────────────────────────────────────────────── #
    version:            str = db.Column(db.String(50),  nullable=True)
    category:           str = db.Column(db.String(100), nullable=True)
    estimated_duration: int = db.Column(db.Integer,     nullable=True)  # minutes
    # ── State ─────────────────────────────────────────────────────────── #
    is_enabled:        bool = db.Column(db.Boolean, nullable=False, default=True)
    created_by:         str = db.Column(db.String(100), nullable=True)
    created_at: datetime    = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at: datetime    = db.Column(db.DateTime(timezone=True), nullable=True)

    steps = db.relationship(
        "RunbookStep",
        back_populates="runbook",
        order_by="RunbookStep.position",
        cascade="all, delete-orphan",
        lazy="select",
    )
    jobs = db.relationship("RunbookJob", back_populates="runbook", lazy="dynamic")

    @property
    def enabled_step_count(self) -> int:
        return sum(1 for s in self.steps if s.is_enabled)

    def __repr__(self) -> str:
        return f"<Runbook {self.id} {self.name!r}>"


class RunbookStep(db.Model):
    __tablename__ = "runbook_steps"

    id:          int = db.Column(db.Integer, primary_key=True)
    runbook_id:  int = db.Column(
        db.Integer, db.ForeignKey("runbooks.id", ondelete="CASCADE"), nullable=False
    )
    # ── Step source ────────────────────────────────────────────────────── #
    step_type:   str = db.Column(db.String(30), nullable=False, default="playbook")
    # "playbook" | "template" | future: "wait" | "approval" | "notification" | "script"
    playbook_id: int = db.Column(
        db.Integer, db.ForeignKey("playbooks.id", ondelete="SET NULL"), nullable=True
    )
    template_id: int = db.Column(
        db.Integer,
        db.ForeignKey("playbook_job_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    # ── Display ────────────────────────────────────────────────────────── #
    position:    int = db.Column(db.Integer, nullable=False, default=1)
    label:       str = db.Column(db.String(255), nullable=True)  # overrides playbook/template name
    notes:       str = db.Column(db.Text,        nullable=True)
    # ── Behaviour ──────────────────────────────────────────────────────── #
    is_required: bool = db.Column(db.Boolean, nullable=False, default=False)
    # Required steps: checkbox locked at launch (cannot be skipped)
    is_enabled:  bool = db.Column(db.Boolean, nullable=False, default=True)
    # Disabled steps are always skipped — admin control without deletion
    on_failure:  str = db.Column(db.String(20), nullable=False, default="stop")
    # "stop" | "continue"

    runbook  = db.relationship("Runbook",             back_populates="steps")
    playbook = db.relationship("Playbook",             foreign_keys=[playbook_id])
    template = db.relationship("PlaybookJobTemplate",  foreign_keys=[template_id])

    @property
    def display_name(self) -> str:
        if self.label:
            return self.label
        if self.step_type == "playbook" and self.playbook:
            return self.playbook.name
        if self.step_type == "template" and self.template:
            return self.template.name
        return f"Step {self.position}"

    def __repr__(self) -> str:
        return f"<RunbookStep pos={self.position} type={self.step_type!r} {self.display_name!r}>"


class RunbookJob(db.Model):
    """One execution of a Runbook."""
    __tablename__ = "runbook_jobs"

    id:                int = db.Column(db.Integer, primary_key=True)
    runbook_id:        int = db.Column(
        db.Integer, db.ForeignKey("runbooks.id", ondelete="SET NULL"), nullable=True
    )
    runbook_name:      str = db.Column(db.String(255), nullable=False)  # snapshot
    triggered_by:      str = db.Column(db.String(100), nullable=True)
    status:            str = db.Column(db.String(20), nullable=False, default="pending")
    # pending | running | completed | failed | cancelled

    # ── Target ─────────────────────────────────────────────────────────── #
    target_type:       str = db.Column(db.String(30),  nullable=True)
    # server | group | environment | all
    target_value:      str = db.Column(db.Text,        nullable=True)
    limit_expression:  str = db.Column(db.String(512), nullable=True)

    # ── Execution options ───────────────────────────────────────────────── #
    become:           bool = db.Column(db.Boolean, nullable=False, default=False)
    check_mode:       bool = db.Column(db.Boolean, nullable=False, default=False)
    extra_vars:        str = db.Column(db.Text,    nullable=True)

    # ── Timestamps ─────────────────────────────────────────────────────── #
    created_at: datetime   = db.Column(db.DateTime(timezone=True), nullable=True)
    started_at: datetime   = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at: datetime  = db.Column(db.DateTime(timezone=True), nullable=True)
    error_message:     str = db.Column(db.Text, nullable=True)

    runbook = db.relationship("Runbook", back_populates="jobs")
    step_executions = db.relationship(
        "RunbookStepExecution",
        back_populates="runbook_job",
        order_by="RunbookStepExecution.position",
        cascade="all, delete-orphan",
        lazy="select",
    )

    @property
    def is_running(self) -> bool:
        return self.status in ("pending", "running")

    @property
    def duration_seconds(self) -> int | None:
        if self.started_at and self.finished_at:
            return int((self.finished_at - self.started_at).total_seconds())
        if self.started_at and self.is_running:
            return int((datetime.now(timezone.utc) - self.started_at).total_seconds())
        return None

    def __repr__(self) -> str:
        return f"<RunbookJob {self.id} {self.runbook_name!r} {self.status}>"


class RunbookStepExecution(db.Model):
    """One step's execution within a RunbookJob — snapshots are stored at launch."""
    __tablename__ = "runbook_step_executions"

    id:               int = db.Column(db.Integer, primary_key=True)
    runbook_job_id:   int = db.Column(
        db.Integer, db.ForeignKey("runbook_jobs.id", ondelete="CASCADE"), nullable=False
    )
    runbook_step_id:  int = db.Column(
        db.Integer, db.ForeignKey("runbook_steps.id", ondelete="SET NULL"), nullable=True
    )

    # ── Snapshots (preserved for history) ──────────────────────────────── #
    position:         int = db.Column(db.Integer, nullable=False)
    step_type:        str = db.Column(db.String(30), nullable=False)
    label:            str = db.Column(db.String(255), nullable=True)
    playbook_path:    str = db.Column(db.String(512), nullable=True)
    playbook_name:    str = db.Column(db.String(255), nullable=True)
    template_name:    str = db.Column(db.String(255), nullable=True)
    execution_params: str = db.Column(db.Text, nullable=True)   # JSON snapshot of settings
    on_failure:       str = db.Column(db.String(20), nullable=False, default="stop")

    # ── Runtime state ──────────────────────────────────────────────────── #
    status:           str = db.Column(db.String(20), nullable=False, default="pending")
    # pending | running | completed | failed | skipped | disabled
    skipped:         bool = db.Column(db.Boolean, nullable=False, default=False)
    # True when operator unchecked an optional step at launch

    # ── Linked PlaybookJob (the actual execution) ───────────────────────── #
    playbook_job_id:  int = db.Column(
        db.Integer, db.ForeignKey("playbook_jobs.id", ondelete="SET NULL"), nullable=True
    )
    error_message:    str = db.Column(db.Text, nullable=True)
    started_at: datetime  = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)

    runbook_job  = db.relationship("RunbookJob",  back_populates="step_executions")
    playbook_job = db.relationship("PlaybookJob", foreign_keys=[playbook_job_id])

    def get_params(self) -> dict:
        try:
            return json.loads(self.execution_params or "{}")
        except Exception:
            return {}

    @property
    def display_name(self) -> str:
        return self.label or self.playbook_name or self.template_name or f"Step {self.position}"

    @property
    def duration_seconds(self) -> int | None:
        if self.started_at and self.finished_at:
            return int((self.finished_at - self.started_at).total_seconds())
        if self.started_at and self.status == "running":
            return int((datetime.now(timezone.utc) - self.started_at).total_seconds())
        return None

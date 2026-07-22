"""
Playbook execution models — Phase 3.

Four models cover the full operational workspace:
  Playbook              — catalog entry (discovered from control node)
  PlaybookJobTemplate   — saved launch configuration
  PlaybookJob           — execution record with streamed log
  PlaybookSchedule      — cron/interval scheduling
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..extensions import db


class Playbook(db.Model):
    """
    A discovered playbook on the Ansible control node.

    Populated by the catalog discovery process; never executed
    directly from this record (execution goes through PlaybookJob).
    """
    __tablename__ = "playbooks"

    id:               int  = db.Column(db.Integer, primary_key=True)
    name:             str  = db.Column(db.String(255), nullable=False)
    description:      str  = db.Column(db.Text,        nullable=True)
    relative_path:    str  = db.Column(db.String(512), nullable=False, unique=True)
    category:         str  = db.Column(db.String(50),  nullable=True)
    # maintenance | patch | security | utility | custom
    tags:             str  = db.Column(db.Text,        nullable=True)   # comma-separated
    requires_become:  bool = db.Column(db.Boolean,     nullable=False, default=False)
    requires_variables: str = db.Column(db.Text,       nullable=True)
    last_modified:    datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    is_enabled:       bool = db.Column(db.Boolean,     nullable=False, default=True)
    is_internal:      bool = db.Column(db.Boolean,     nullable=False, default=False)
    metadata_source:  str  = db.Column(db.String(20),  nullable=True)  # 'comment' | 'filename'
    discovered_at:    datetime = db.Column(db.DateTime(timezone=True), nullable=True)

    # Relationships
    jobs      = db.relationship("PlaybookJob",         back_populates="playbook",  lazy="dynamic")
    templates = db.relationship("PlaybookJobTemplate", back_populates="playbook",  lazy="dynamic")

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "name":             self.name,
            "description":      self.description,
            "relative_path":    self.relative_path,
            "category":         self.category,
            "tags":             self.tag_list,
            "requires_become":  self.requires_become,
            "is_enabled":       self.is_enabled,
            "last_modified":    self.last_modified.isoformat() if self.last_modified else None,
        }


class PlaybookJobTemplate(db.Model):
    """
    A saved launch configuration.

    All execution options are stored as a JSON blob in `settings`.
    One-click launch creates a PlaybookJob from this template.
    """
    __tablename__ = "playbook_job_templates"

    id:          int = db.Column(db.Integer, primary_key=True)
    name:        str = db.Column(db.String(255), nullable=False)
    description: str = db.Column(db.Text,        nullable=True)
    playbook_id: int = db.Column(db.Integer, db.ForeignKey("playbooks.id", ondelete="SET NULL"), nullable=True)
    settings:    str = db.Column(db.Text,    nullable=True)   # JSON
    created_by:  str = db.Column(db.String(100), nullable=True)
    created_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)

    # Relationships
    playbook  = db.relationship("Playbook",       back_populates="templates")
    jobs      = db.relationship("PlaybookJob",    back_populates="template",   lazy="dynamic")
    schedules = db.relationship("PlaybookSchedule", back_populates="template", lazy="dynamic")

    def get_settings(self) -> dict:
        try:
            return json.loads(self.settings or "{}")
        except Exception:
            return {}

    def set_settings(self, data: dict) -> None:
        self.settings = json.dumps(data)


class PlaybookJob(db.Model):
    """
    A single playbook execution — pending → running → completed | failed | cancelled.

    log_output is appended-to during execution via SQL concatenation so the
    web layer can stream it at any byte offset without loading the full blob.
    """
    __tablename__ = "playbook_jobs"

    id:                  int = db.Column(db.Integer, primary_key=True)
    playbook_id:         int = db.Column(db.Integer, db.ForeignKey("playbooks.id", ondelete="SET NULL"), nullable=True)
    playbook_path:       str = db.Column(db.String(512), nullable=False)
    playbook_name:       str = db.Column(db.String(255), nullable=True)
    template_id:         int = db.Column(db.Integer, db.ForeignKey("playbook_job_templates.id", ondelete="SET NULL"), nullable=True)

    # Execution identity
    triggered_by:        str = db.Column(db.String(100), nullable=True)
    status:              str = db.Column(db.String(20),  nullable=False, default="pending")
    exit_code:           int = db.Column(db.Integer, nullable=True)
    started_at:    datetime  = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at:   datetime  = db.Column(db.DateTime(timezone=True), nullable=True)
    error_message:       str = db.Column(db.Text, nullable=True)
    created_at:    datetime  = db.Column(db.DateTime(timezone=True), nullable=True)

    # Target host selection
    target_type:         str = db.Column(db.String(30),  nullable=True)
    target_value:        str = db.Column(db.Text,        nullable=True)
    limit_expression:    str = db.Column(db.String(512), nullable=True)
    host_count:          int = db.Column(db.Integer, nullable=True)

    # Inventory
    inventory_type:      str = db.Column(db.String(20),  nullable=True)
    inventory_value:     str = db.Column(db.String(512), nullable=True)

    # Execution options
    become:             bool = db.Column(db.Boolean, nullable=False, default=False)
    check_mode:         bool = db.Column(db.Boolean, nullable=False, default=False)
    diff_mode:          bool = db.Column(db.Boolean, nullable=False, default=False)
    dry_run:            bool = db.Column(db.Boolean, nullable=False, default=False)
    forks:               int = db.Column(db.Integer, nullable=False, default=5)
    verbosity:           int = db.Column(db.Integer, nullable=False, default=0)
    tags:                str = db.Column(db.String(512), nullable=True)
    skip_tags:           str = db.Column(db.String(512), nullable=True)
    extra_vars:          str = db.Column(db.Text, nullable=True)

    # Safety
    production_confirmed: bool = db.Column(db.Boolean, nullable=False, default=False)

    # Streaming log
    log_output:          str = db.Column(db.Text, nullable=True)
    log_size:            int = db.Column(db.Integer, nullable=False, default=0)

    # Remote process (for cancellation)
    remote_pid:          int = db.Column(db.Integer, nullable=True)

    # Parsed statistics
    hosts_ok:            int = db.Column(db.Integer, nullable=True)
    hosts_changed:       int = db.Column(db.Integer, nullable=True)
    hosts_failed:        int = db.Column(db.Integer, nullable=True)
    hosts_skipped:       int = db.Column(db.Integer, nullable=True)
    hosts_unreachable:   int = db.Column(db.Integer, nullable=True)
    task_count:          int = db.Column(db.Integer, nullable=True)

    # Relationships
    playbook = db.relationship("Playbook",             back_populates="jobs")
    template = db.relationship("PlaybookJobTemplate",  back_populates="jobs")

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

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "playbook":     self.playbook_name,
            "status":       self.status,
            "triggered_by": self.triggered_by,
            "started_at":   self.started_at.isoformat() if self.started_at else None,
            "finished_at":  self.finished_at.isoformat() if self.finished_at else None,
            "duration":     self.duration_seconds,
            "exit_code":    self.exit_code,
            "host_count":   self.host_count,
        }


class PlaybookSchedule(db.Model):
    """
    Cron/interval-based scheduling for a saved job template.
    """
    __tablename__ = "playbook_schedules"

    id:              int = db.Column(db.Integer, primary_key=True)
    name:            str = db.Column(db.String(255), nullable=False)
    template_id:     int = db.Column(db.Integer, db.ForeignKey("playbook_job_templates.id", ondelete="CASCADE"), nullable=False)
    schedule_type:   str = db.Column(db.String(20), nullable=False)
    # once | hourly | daily | weekly | monthly | cron
    cron_expression: str = db.Column(db.String(100), nullable=True)
    next_run_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    last_run_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    last_job_id:     int = db.Column(db.Integer, db.ForeignKey("playbook_jobs.id", ondelete="SET NULL"), nullable=True)
    is_enabled:     bool = db.Column(db.Boolean, nullable=False, default=True)
    created_by:      str = db.Column(db.String(100), nullable=True)
    created_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)

    # Relationships
    template = db.relationship("PlaybookJobTemplate", back_populates="schedules")

"""Playbook execution engine — Phase 3.

Adds four tables for the Ansible operational workspace:
  playbooks            — catalog of discovered playbooks
  playbook_jobs        — execution records with streaming log
  playbook_job_templates — saved launch configurations
  playbook_schedules   — cron/interval-based scheduling

Revision ID: i9j0k1l2m3n4
Revises:     h8i9j0k1l2m3
Create Date: 2026-07-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision    = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── Playbook catalog ──────────────────────────────────────────────── #
    op.create_table(
        "playbooks",
        sa.Column("id",                 sa.Integer,     primary_key=True),
        sa.Column("name",               sa.String(255), nullable=False),
        sa.Column("description",        sa.Text,        nullable=True),
        sa.Column("relative_path",      sa.String(512), nullable=False, unique=True),
        sa.Column("category",           sa.String(50),  nullable=True),   # maintenance/patch/security/utility/custom
        sa.Column("tags",               sa.Text,        nullable=True),   # comma-separated
        sa.Column("requires_become",    sa.Boolean,     default=False, nullable=False),
        sa.Column("requires_variables", sa.Text,        nullable=True),   # YAML/JSON hint
        sa.Column("last_modified",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_enabled",         sa.Boolean,     default=True, nullable=False),
        sa.Column("is_internal",        sa.Boolean,     default=False, nullable=False),
        sa.Column("metadata_source",    sa.String(20),  nullable=True),   # 'comment' | 'filename'
        sa.Column("discovered_at",      sa.DateTime(timezone=True), nullable=True),
    )

    # ── Playbook job templates (saved configs) ────────────────────────── #
    op.create_table(
        "playbook_job_templates",
        sa.Column("id",          sa.Integer,     primary_key=True),
        sa.Column("name",        sa.String(255), nullable=False),
        sa.Column("description", sa.Text,        nullable=True),
        sa.Column("playbook_id", sa.Integer,     sa.ForeignKey("playbooks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("settings",    sa.Text,        nullable=True),   # JSON blob of all options
        sa.Column("created_by",  sa.String(100), nullable=True),
        sa.Column("created_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at",  sa.DateTime(timezone=True), nullable=True),
    )

    # ── Playbook execution jobs ───────────────────────────────────────── #
    op.create_table(
        "playbook_jobs",
        sa.Column("id",                  sa.Integer,     primary_key=True),
        sa.Column("playbook_id",         sa.Integer,     sa.ForeignKey("playbooks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("playbook_path",       sa.String(512), nullable=False),
        sa.Column("playbook_name",       sa.String(255), nullable=True),
        sa.Column("template_id",         sa.Integer,     sa.ForeignKey("playbook_job_templates.id", ondelete="SET NULL"), nullable=True),
        # Execution identity
        sa.Column("triggered_by",        sa.String(100), nullable=True),
        sa.Column("status",              sa.String(20),  nullable=False, default="pending"),
        # pending | running | completed | failed | cancelled
        sa.Column("exit_code",           sa.Integer,     nullable=True),
        sa.Column("started_at",          sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at",         sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message",       sa.Text,        nullable=True),
        # Target host selection
        sa.Column("target_type",         sa.String(30),  nullable=True),  # all|environment|location|hosts|limit
        sa.Column("target_value",        sa.Text,        nullable=True),  # JSON list or expression
        sa.Column("limit_expression",    sa.String(512), nullable=True),  # final --limit value
        sa.Column("host_count",          sa.Integer,     nullable=True),
        # Inventory
        sa.Column("inventory_type",      sa.String(20),  nullable=True),  # default|file|dynamic
        sa.Column("inventory_value",     sa.String(512), nullable=True),
        # Execution options
        sa.Column("become",              sa.Boolean,     default=False, nullable=False),
        sa.Column("check_mode",          sa.Boolean,     default=False, nullable=False),
        sa.Column("diff_mode",           sa.Boolean,     default=False, nullable=False),
        sa.Column("dry_run",             sa.Boolean,     default=False, nullable=False),
        sa.Column("forks",               sa.Integer,     default=5, nullable=False),
        sa.Column("verbosity",           sa.Integer,     default=0, nullable=False),
        sa.Column("tags",                sa.String(512), nullable=True),
        sa.Column("skip_tags",           sa.String(512), nullable=True),
        sa.Column("extra_vars",          sa.Text,        nullable=True),
        # Safety
        sa.Column("production_confirmed",sa.Boolean,     default=False, nullable=False),
        # Output streaming
        sa.Column("log_output",          sa.Text,        nullable=True),
        sa.Column("log_size",            sa.Integer,     default=0, nullable=False),
        # Remote process (for cancellation)
        sa.Column("remote_pid",          sa.Integer,     nullable=True),
        # Parsed statistics from output
        sa.Column("hosts_ok",            sa.Integer,     nullable=True),
        sa.Column("hosts_changed",       sa.Integer,     nullable=True),
        sa.Column("hosts_failed",        sa.Integer,     nullable=True),
        sa.Column("hosts_skipped",       sa.Integer,     nullable=True),
        sa.Column("hosts_unreachable",   sa.Integer,     nullable=True),
        sa.Column("task_count",          sa.Integer,     nullable=True),
        sa.Column("created_at",          sa.DateTime(timezone=True), nullable=True),
    )

    # ── Playbook schedules ─────────────────────────────────────────────── #
    op.create_table(
        "playbook_schedules",
        sa.Column("id",              sa.Integer,     primary_key=True),
        sa.Column("name",            sa.String(255), nullable=False),
        sa.Column("template_id",     sa.Integer,     sa.ForeignKey("playbook_job_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schedule_type",   sa.String(20),  nullable=False),  # once|hourly|daily|weekly|monthly|cron
        sa.Column("cron_expression", sa.String(100), nullable=True),   # for 'cron' type
        sa.Column("next_run_at",     sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at",     sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_job_id",     sa.Integer,     sa.ForeignKey("playbook_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_enabled",      sa.Boolean,     default=True, nullable=False),
        sa.Column("created_by",      sa.String(100), nullable=True),
        sa.Column("created_at",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at",      sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("playbook_schedules")
    op.drop_table("playbook_jobs")
    op.drop_table("playbook_job_templates")
    op.drop_table("playbooks")

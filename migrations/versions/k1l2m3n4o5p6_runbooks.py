"""Runbooks — four new tables for ordered playbook workflow execution.

Creates:
  runbooks              — runbook definitions (name, steps, metadata)
  runbook_steps         — ordered steps within a runbook
  runbook_jobs          — one execution of a runbook
  runbook_step_executions — one step execution within a runbook job

Revision ID: k1l2m3n4o5p6
Revises:     j0k1l2m3n4o5
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision      = "k1l2m3n4o5p6"
down_revision = "j0k1l2m3n4o5"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── 1. runbooks ───────────────────────────────────────────────────────── #
    op.create_table(
        "runbooks",
        sa.Column("id",                 sa.Integer,      primary_key=True),
        sa.Column("name",               sa.String(255),  nullable=False),
        sa.Column("description",        sa.Text,         nullable=True),
        sa.Column("version",            sa.String(50),   nullable=True),
        sa.Column("category",           sa.String(100),  nullable=True),
        sa.Column("estimated_duration", sa.Integer,      nullable=True),
        sa.Column("is_enabled",         sa.Boolean,      nullable=False, server_default="true"),
        sa.Column("created_by",         sa.String(100),  nullable=True),
        sa.Column("created_at",         sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at",         sa.DateTime(timezone=True), nullable=True),
    )

    # ── 2. runbook_steps ─────────────────────────────────────────────────── #
    op.create_table(
        "runbook_steps",
        sa.Column("id",          sa.Integer,     primary_key=True),
        sa.Column("runbook_id",  sa.Integer,     sa.ForeignKey("runbooks.id",                ondelete="CASCADE"),  nullable=False),
        sa.Column("step_type",   sa.String(30),  nullable=False, server_default="playbook"),
        sa.Column("playbook_id", sa.Integer,     sa.ForeignKey("playbooks.id",               ondelete="SET NULL"), nullable=True),
        sa.Column("template_id", sa.Integer,     sa.ForeignKey("playbook_job_templates.id",  ondelete="SET NULL"), nullable=True),
        sa.Column("position",    sa.Integer,     nullable=False, server_default="1"),
        sa.Column("label",       sa.String(255), nullable=True),
        sa.Column("notes",       sa.Text,        nullable=True),
        sa.Column("is_required", sa.Boolean,     nullable=False, server_default="false"),
        sa.Column("is_enabled",  sa.Boolean,     nullable=False, server_default="true"),
        sa.Column("on_failure",  sa.String(20),  nullable=False, server_default="stop"),
    )
    op.create_index("ix_runbook_steps_runbook_position", "runbook_steps",
                    ["runbook_id", "position"])

    # ── 3. runbook_jobs ──────────────────────────────────────────────────── #
    op.create_table(
        "runbook_jobs",
        sa.Column("id",               sa.Integer,      primary_key=True),
        sa.Column("runbook_id",       sa.Integer,      sa.ForeignKey("runbooks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("runbook_name",     sa.String(255),  nullable=False),
        sa.Column("triggered_by",     sa.String(100),  nullable=True),
        sa.Column("status",           sa.String(20),   nullable=False, server_default="pending"),
        sa.Column("target_type",      sa.String(30),   nullable=True),
        sa.Column("target_value",     sa.Text,         nullable=True),
        sa.Column("limit_expression", sa.String(512),  nullable=True),
        sa.Column("become",           sa.Boolean,      nullable=False, server_default="false"),
        sa.Column("check_mode",       sa.Boolean,      nullable=False, server_default="false"),
        sa.Column("extra_vars",       sa.Text,         nullable=True),
        sa.Column("error_message",    sa.Text,         nullable=True),
        sa.Column("created_at",       sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at",       sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at",      sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_runbook_jobs_runbook_id", "runbook_jobs", ["runbook_id"])
    op.create_index("ix_runbook_jobs_status",     "runbook_jobs", ["status"])

    # ── 4. runbook_step_executions ───────────────────────────────────────── #
    op.create_table(
        "runbook_step_executions",
        sa.Column("id",               sa.Integer,     primary_key=True),
        sa.Column("runbook_job_id",   sa.Integer,     sa.ForeignKey("runbook_jobs.id",  ondelete="CASCADE"),  nullable=False),
        sa.Column("runbook_step_id",  sa.Integer,     sa.ForeignKey("runbook_steps.id", ondelete="SET NULL"), nullable=True),
        sa.Column("position",         sa.Integer,     nullable=False),
        sa.Column("step_type",        sa.String(30),  nullable=False),
        sa.Column("label",            sa.String(255), nullable=True),
        sa.Column("playbook_path",    sa.String(512), nullable=True),
        sa.Column("playbook_name",    sa.String(255), nullable=True),
        sa.Column("template_name",    sa.String(255), nullable=True),
        sa.Column("execution_params", sa.Text,        nullable=True),
        sa.Column("on_failure",       sa.String(20),  nullable=False, server_default="stop"),
        sa.Column("status",           sa.String(20),  nullable=False, server_default="pending"),
        sa.Column("skipped",          sa.Boolean,     nullable=False, server_default="false"),
        sa.Column("playbook_job_id",  sa.Integer,     sa.ForeignKey("playbook_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error_message",    sa.Text,        nullable=True),
        sa.Column("started_at",       sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at",      sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_runbook_step_exec_job", "runbook_step_executions", ["runbook_job_id"])


def downgrade() -> None:
    op.drop_table("runbook_step_executions")
    op.drop_table("runbook_jobs")
    op.drop_table("runbook_steps")
    op.drop_table("runbooks")

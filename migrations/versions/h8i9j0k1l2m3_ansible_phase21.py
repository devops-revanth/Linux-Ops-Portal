"""Ansible Phase 2.1 — per-server fact sync status columns.

Adds ansible_fact_status, ansible_fact_duration_secs, and ansible_fact_error
to linux_servers so the UI can show per-server collection results without
storing raw Ansible output.

Revision ID: h8i9j0k1l2m3
Revises:     g7h8i9j0k1l2
Create Date: 2026-07-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "h8i9j0k1l2m3"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("linux_servers") as batch_op:
        batch_op.add_column(
            sa.Column("ansible_fact_status", sa.String(20), nullable=True)
        )  # success | failed | running | None(never)
        batch_op.add_column(
            sa.Column("ansible_fact_duration_secs", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("ansible_fact_error", sa.Text(), nullable=True)
        )  # sanitized — no stack traces


def downgrade() -> None:
    with op.batch_alter_table("linux_servers") as batch_op:
        for col in ("ansible_fact_error", "ansible_fact_duration_secs", "ansible_fact_status"):
            batch_op.drop_column(col)

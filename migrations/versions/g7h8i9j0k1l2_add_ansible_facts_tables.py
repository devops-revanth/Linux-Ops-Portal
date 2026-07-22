"""Add Ansible Phase 2 fact collection tables and columns.

Adds extended fact columns to linux_servers and ansible_config,
and creates four new tables for fact collection data.

Revision ID: g7h8i9j0k1l2
Revises:     f6a7b8c9d0e1
Create Date: 2026-07-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "g7h8i9j0k1l2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. linux_servers — Ansible-owned extended fact columns ──────────── #
    with op.batch_alter_table("linux_servers") as batch_op:
        batch_op.add_column(sa.Column("architecture",       sa.String(20),  nullable=True))
        batch_op.add_column(sa.Column("swap_gb",            sa.Float(),     nullable=True))
        batch_op.add_column(sa.Column("timezone",           sa.String(50),  nullable=True))
        batch_op.add_column(sa.Column("selinux_status",     sa.String(30),  nullable=True))
        batch_op.add_column(sa.Column("uptime_seconds",     sa.BigInteger(),nullable=True))
        batch_op.add_column(sa.Column("boot_time",          sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("default_gateway",    sa.String(45),  nullable=True))
        batch_op.add_column(sa.Column("dns_servers",        sa.Text(),      nullable=True))
        batch_op.add_column(sa.Column("primary_interface",  sa.String(50),  nullable=True))
        batch_op.add_column(sa.Column("mac_address",        sa.String(20),  nullable=True))
        batch_op.add_column(sa.Column("virtualization_type",sa.String(30),  nullable=True))

    # ── 2. ansible_config — scheduled sync + last sync tracking ─────────── #
    with op.batch_alter_table("ansible_config") as batch_op:
        batch_op.add_column(sa.Column("sync_enabled",         sa.Boolean(),  nullable=False, server_default="false"))
        batch_op.add_column(sa.Column("sync_schedule",        sa.String(20), nullable=False, server_default="disabled"))
        batch_op.add_column(sa.Column("last_fact_sync_at",    sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_fact_sync_status",sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("last_fact_sync_ok",    sa.Integer(),  nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("last_fact_sync_failed",sa.Integer(),  nullable=False, server_default="0"))

    # ── 3. ansible_filesystems ───────────────────────────────────────────── #
    op.create_table(
        "ansible_filesystems",
        sa.Column("id",        sa.Integer(), primary_key=True),
        sa.Column("server_id", sa.Integer(),
                  sa.ForeignKey("linux_servers.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("mount",    sa.String(255), nullable=False),
        sa.Column("device",   sa.String(255), nullable=True),
        sa.Column("fstype",   sa.String(50),  nullable=True),
        sa.Column("size_gb",  sa.Float(),     nullable=True),
        sa.Column("used_gb",  sa.Float(),     nullable=True),
        sa.Column("avail_gb", sa.Float(),     nullable=True),
        sa.Column("use_pct",  sa.Integer(),   nullable=True),
        sa.Column("synced_at",sa.DateTime(timezone=True), nullable=False),
    )
    # ── 4. ansible_server_services ──────────────────────────────────────── #
    op.create_table(
        "ansible_server_services",
        sa.Column("id",        sa.Integer(), primary_key=True),
        sa.Column("server_id", sa.Integer(),
                  sa.ForeignKey("linux_servers.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("name",     sa.String(100), nullable=False),
        sa.Column("state",    sa.String(30),  nullable=True),
        sa.Column("enabled",  sa.String(20),  nullable=True),
        sa.Column("synced_at",sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("server_id", "name", name="uq_server_service"),
    )

    # ── 5. ansible_repositories ─────────────────────────────────────────── #
    op.create_table(
        "ansible_repositories",
        sa.Column("id",        sa.Integer(), primary_key=True),
        sa.Column("server_id", sa.Integer(),
                  sa.ForeignKey("linux_servers.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("repo_id",   sa.String(200), nullable=False),
        sa.Column("repo_name", sa.String(255), nullable=True),
        sa.Column("enabled",   sa.Boolean(),   nullable=False, server_default="true"),
        sa.Column("baseurl",   sa.Text(),       nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("server_id", "repo_id", name="uq_server_repo"),
    )

    # ── 6. ansible_sync_jobs ─────────────────────────────────────────────── #
    op.create_table(
        "ansible_sync_jobs",
        sa.Column("id",              sa.Integer(), primary_key=True),
        sa.Column("started_at",      sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at",    sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_by",    sa.String(50),  nullable=False, server_default="manual"),
        sa.Column("status",          sa.String(20),  nullable=False, server_default="running"),
        sa.Column("servers_total",   sa.Integer(),   nullable=False, server_default="0"),
        sa.Column("servers_ok",      sa.Integer(),   nullable=False, server_default="0"),
        sa.Column("servers_failed",  sa.Integer(),   nullable=False, server_default="0"),
        sa.Column("packages_synced", sa.Integer(),   nullable=False, server_default="0"),
        sa.Column("error_message",   sa.Text(),       nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ansible_sync_jobs")
    op.drop_table("ansible_repositories")
    op.drop_table("ansible_server_services")
    op.drop_table("ansible_filesystems")

    with op.batch_alter_table("ansible_config") as batch_op:
        for col in ("last_fact_sync_failed", "last_fact_sync_ok",
                    "last_fact_sync_status", "last_fact_sync_at",
                    "sync_schedule", "sync_enabled"):
            batch_op.drop_column(col)

    with op.batch_alter_table("linux_servers") as batch_op:
        for col in ("virtualization_type", "mac_address", "primary_interface",
                    "dns_servers", "default_gateway", "boot_time",
                    "uptime_seconds", "selinux_status", "timezone",
                    "swap_gb", "architecture"):
            batch_op.drop_column(col)

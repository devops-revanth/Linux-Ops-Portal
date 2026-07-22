"""Multi-vCenter support — vmware_connections table.

Creates vmware_connections (one row per vCenter), adds connection_id FK
to vmware_sync_logs and vmware_server_meta, adds vcenter_name column to
vmware_server_meta, and data-migrates the existing single-vCenter
vmware_config row so existing installations require no manual steps.

Revision ID: j0k1l2m3n4o5
Revises:     i9j0k1l2m3n4
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision    = "j0k1l2m3n4o5"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── 1. Create vmware_connections ──────────────────────────────────────── #
    op.create_table(
        "vmware_connections",
        sa.Column("id",           sa.Integer,       primary_key=True),
        sa.Column("name",         sa.String(255),   nullable=False),
        sa.Column("vcenter_host", sa.String(255),   nullable=False),
        sa.Column("port",         sa.Integer,       nullable=False, server_default="443"),
        sa.Column("username",     sa.String(255),   nullable=True),
        sa.Column("password_enc", sa.Text,          nullable=True),
        sa.Column("ignore_ssl",   sa.Boolean,       nullable=False, server_default="0"),
        # Location is mandatory at the application level; nullable here for
        # backward-compat migration (existing config may have no location set).
        sa.Column("location_id",            sa.Integer, sa.ForeignKey("locations.id"),    nullable=True),
        sa.Column("default_environment_id", sa.Integer, sa.ForeignKey("environments.id"), nullable=True),
        sa.Column("enabled",          sa.Boolean,   nullable=False, server_default="1"),
        sa.Column("connection_status", sa.String(50), nullable=False, server_default="Not Tested"),
        sa.Column("last_test_at",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_ok_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_fail_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_vms",      sa.Integer, nullable=True),
        sa.Column("last_sync_duration_s", sa.Float, nullable=True),
        sa.Column("sync_schedule", sa.String(20), nullable=False, server_default="disabled"),
        sa.Column("updated_at",    sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        # Prevent duplicate location + host combinations
        sa.UniqueConstraint("location_id", "vcenter_host", name="uq_vmware_conn_loc_host"),
    )

    # ── 2. Add connection_id FK to vmware_sync_logs ───────────────────────── #
    op.add_column(
        "vmware_sync_logs",
        sa.Column("connection_id", sa.Integer,
                  sa.ForeignKey("vmware_connections.id", ondelete="SET NULL"),
                  nullable=True, index=True),
    )

    # ── 3. Add connection_id + vcenter_name to vmware_server_meta ────────── #
    op.add_column(
        "vmware_server_meta",
        sa.Column("connection_id", sa.Integer,
                  sa.ForeignKey("vmware_connections.id", ondelete="SET NULL"),
                  nullable=True, index=True),
    )
    op.add_column(
        "vmware_server_meta",
        sa.Column("vcenter_name", sa.String(255), nullable=True),
    )

    # ── 4. Data migration: copy existing vmware_config row ────────────────── #
    conn = op.get_bind()

    # Check if vmware_config has a meaningful configuration
    cfg_row = conn.execute(
        sa.text(
            "SELECT id, vcenter_host, port, username, password_enc, ignore_ssl, "
            "default_location_id, default_environment_id, enabled, "
            "connection_status, last_test_at, last_sync_at, last_sync_ok_at, "
            "last_sync_fail_at, last_sync_vms, last_sync_duration_s, sync_schedule "
            "FROM vmware_config LIMIT 1"
        )
    ).fetchone()

    if cfg_row and cfg_row[1]:  # vcenter_host is set
        host = cfg_row[1]

        # Determine location_id: use configured default or first available
        loc_id = cfg_row[6]  # default_location_id
        if not loc_id:
            first_loc = conn.execute(
                sa.text("SELECT id FROM locations ORDER BY id LIMIT 1")
            ).fetchone()
            if first_loc:
                loc_id = first_loc[0]

        now = datetime.now(timezone.utc)
        result = conn.execute(
            sa.text(
                "INSERT INTO vmware_connections "
                "(name, vcenter_host, port, username, password_enc, ignore_ssl, "
                "location_id, default_environment_id, enabled, connection_status, "
                "last_test_at, last_sync_at, last_sync_ok_at, last_sync_fail_at, "
                "last_sync_vms, last_sync_duration_s, sync_schedule, updated_at) "
                "VALUES (:name, :host, :port, :user, :pwd, :ssl, "
                ":loc, :env, :enabled, :cs, "
                ":lt, :lsa, :lsoa, :lsfa, "
                ":vms, :dur, :sched, :now) "
                "RETURNING id"
            ),
            {
                "name":    host,          # Use host as initial name
                "host":    host,
                "port":    cfg_row[2] or 443,
                "user":    cfg_row[3],
                "pwd":     cfg_row[4],
                "ssl":     bool(cfg_row[5]),
                "loc":     loc_id,
                "env":     cfg_row[7],
                "enabled": bool(cfg_row[8]),
                "cs":      cfg_row[9] or "Not Tested",
                "lt":      cfg_row[10],
                "lsa":     cfg_row[11],
                "lsoa":    cfg_row[12],
                "lsfa":    cfg_row[13],
                "vms":     cfg_row[14],
                "dur":     cfg_row[15],
                "sched":   cfg_row[16] or "disabled",
                "now":     now,
            },
        )
        new_conn_id = result.fetchone()[0]

        # Back-fill connection_id on existing sync logs (all logs belong to this connection)
        conn.execute(
            sa.text("UPDATE vmware_sync_logs SET connection_id = :cid"),
            {"cid": new_conn_id},
        )

        # Back-fill connection_id and vcenter_name on server meta rows
        conn.execute(
            sa.text(
                "UPDATE vmware_server_meta SET connection_id = :cid, vcenter_name = :name"
            ),
            {"cid": new_conn_id, "name": host},
        )


def downgrade() -> None:
    op.drop_column("vmware_server_meta", "vcenter_name")
    op.drop_column("vmware_server_meta", "connection_id")
    op.drop_column("vmware_sync_logs",   "connection_id")
    op.drop_table("vmware_connections")

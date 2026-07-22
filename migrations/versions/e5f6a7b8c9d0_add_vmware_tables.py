"""Add VMware vCenter integration tables and server source column

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    # ── Add source + vmware_vm_uuid to linux_servers ──────────────────────── #
    op.add_column(
        "linux_servers",
        sa.Column(
            "source",
            sa.String(20),
            nullable=False,
            server_default="manual",
            comment="Origin of the record: manual | vmware | ansible",
        ),
    )
    op.add_column(
        "linux_servers",
        sa.Column(
            "vmware_vm_uuid",
            sa.String(36),
            nullable=True,
            comment="VMware VM config.uuid — used for deduplication",
        ),
    )
    op.create_index(
        "ix_linux_servers_vmware_vm_uuid",
        "linux_servers",
        ["vmware_vm_uuid"],
        unique=False,
    )

    # ── vmware_config (singleton) ────────────────────────────────────────── #
    op.create_table(
        "vmware_config",
        sa.Column("id",                    sa.Integer(),     primary_key=True),
        sa.Column("enabled",               sa.Boolean(),     nullable=False, server_default="false"),
        sa.Column("vcenter_host",          sa.String(255),   nullable=True),
        sa.Column("port",                  sa.Integer(),     nullable=False, server_default="443"),
        sa.Column("username",              sa.String(255),   nullable=True),
        sa.Column("password_enc",          sa.Text(),        nullable=True),
        sa.Column("ignore_ssl",            sa.Boolean(),     nullable=False, server_default="false"),
        sa.Column("default_location_id",   sa.Integer(),
                  sa.ForeignKey("locations.id"),    nullable=True),
        sa.Column("default_environment_id",sa.Integer(),
                  sa.ForeignKey("environments.id"), nullable=True),
        sa.Column("connection_status",     sa.String(50),    nullable=False, server_default="Not Tested"),
        sa.Column("last_test_at",          sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at",          sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_ok_at",       sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_fail_at",     sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_vms",         sa.Integer(),     nullable=True),
        sa.Column("last_sync_duration_s",  sa.Float(),       nullable=True),
        sa.Column("sync_schedule",         sa.String(20),    nullable=False, server_default="disabled"),
        sa.Column("updated_at",            sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )

    # ── vmware_server_meta (1:1 with linux_servers) ──────────────────────── #
    op.create_table(
        "vmware_server_meta",
        sa.Column("id",            sa.Integer(), primary_key=True),
        sa.Column("server_id",     sa.Integer(),
                  sa.ForeignKey("linux_servers.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("vcenter_host",  sa.String(255), nullable=True),
        sa.Column("datacenter",    sa.String(255), nullable=True),
        sa.Column("cluster",       sa.String(255), nullable=True),
        sa.Column("esxi_host",     sa.String(255), nullable=True),
        sa.Column("datastore",     sa.String(255), nullable=True),
        sa.Column("folder",        sa.String(500), nullable=True),
        sa.Column("vm_name",       sa.String(255), nullable=True),
        sa.Column("vm_uuid",       sa.String(36),  nullable=True),
        sa.Column("bios_uuid",     sa.String(36),  nullable=True),
        sa.Column("power_state",   sa.String(50),  nullable=True),
        sa.Column("tools_status",  sa.String(100), nullable=True),
        sa.Column("tools_version", sa.String(50),  nullable=True),
        sa.Column("mac_address",   sa.String(255), nullable=True),
        sa.Column("network_name",  sa.String(255), nullable=True),
        sa.Column("last_synced_at",sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_vmware_server_meta_vm_uuid",
        "vmware_server_meta",
        ["vm_uuid"],
    )

    # ── vmware_sync_logs ─────────────────────────────────────────────────── #
    op.create_table(
        "vmware_sync_logs",
        sa.Column("id",           sa.Integer(), primary_key=True),
        sa.Column("status",       sa.String(20),  nullable=False, server_default="running"),
        sa.Column("started_at",   sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("finished_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("vms_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vms_updated",  sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vms_skipped",  sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message",sa.Text(),    nullable=True),
        sa.Column("triggered_by", sa.String(20), nullable=False, server_default="manual"),
    )


def downgrade():
    op.drop_table("vmware_sync_logs")
    op.drop_table("vmware_server_meta")
    op.drop_table("vmware_config")
    op.drop_index("ix_linux_servers_vmware_vm_uuid", "linux_servers")
    op.drop_column("linux_servers", "vmware_vm_uuid")
    op.drop_column("linux_servers", "source")

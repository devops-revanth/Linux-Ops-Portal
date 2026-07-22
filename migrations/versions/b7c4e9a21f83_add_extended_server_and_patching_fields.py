"""add extended server and patching fields

Revision ID: b7c4e9a21f83
Revises: f3a2c1d8e049
Create Date: 2026-07-22 00:00:00.000000

Adds columns required for the enterprise Ansible integration:

linux_servers:
  architecture, disk_total_gb, disk_used_gb, disk_used_pct,
  swap_total_gb, swap_used_gb, uptime_seconds, last_boot,
  package_manager, python_version, ansible_version,
  selinux_status, timezone_name,
  parsed_site, parsed_app_code, parsed_os_name, parsed_env_name

patching:
  security_updates, kernel_update_available, installed_kernel
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c4e9a21f83'
down_revision = 'f3a2c1d8e049'
branch_labels = None
depends_on = None


def upgrade():
    # ── linux_servers: extended system info ─────────────────────────── #
    with op.batch_alter_table('linux_servers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('architecture', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('disk_total_gb', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('disk_used_gb', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('disk_used_pct', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('swap_total_gb', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('swap_used_gb', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('uptime_seconds', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('last_boot', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('package_manager', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('python_version', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('ansible_version', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('selinux_status', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('timezone_name', sa.String(length=100), nullable=True))
        # Hostname parsing results (populated by Ansible)
        batch_op.add_column(sa.Column('parsed_site', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('parsed_app_code', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('parsed_os_name', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('parsed_env_name', sa.String(length=50), nullable=True))

    # ── patching: extended patch tracking ───────────────────────────── #
    with op.batch_alter_table('patching', schema=None) as batch_op:
        batch_op.add_column(sa.Column('security_updates', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('kernel_update_available', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('installed_kernel', sa.String(length=150), nullable=True))


def downgrade():
    with op.batch_alter_table('patching', schema=None) as batch_op:
        batch_op.drop_column('installed_kernel')
        batch_op.drop_column('kernel_update_available')
        batch_op.drop_column('security_updates')

    with op.batch_alter_table('linux_servers', schema=None) as batch_op:
        batch_op.drop_column('parsed_env_name')
        batch_op.drop_column('parsed_os_name')
        batch_op.drop_column('parsed_app_code')
        batch_op.drop_column('parsed_site')
        batch_op.drop_column('timezone_name')
        batch_op.drop_column('selinux_status')
        batch_op.drop_column('ansible_version')
        batch_op.drop_column('python_version')
        batch_op.drop_column('package_manager')
        batch_op.drop_column('last_boot')
        batch_op.drop_column('uptime_seconds')
        batch_op.drop_column('swap_used_gb')
        batch_op.drop_column('swap_total_gb')
        batch_op.drop_column('disk_used_pct')
        batch_op.drop_column('disk_used_gb')
        batch_op.drop_column('disk_total_gb')
        batch_op.drop_column('architecture')

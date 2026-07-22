"""Add compliance_config table and update columns to server_packages.

Revision ID: b2c3d4e5f6a7
Revises: f3a2c1d8e049
Create Date: 2026-07-22

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'f3a2c1d8e049'
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. Create compliance_config table ─────────────────────────────────
    op.create_table(
        'compliance_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('compliance_window_days', sa.Integer(), nullable=False, server_default='90'),
        sa.Column('due_soon_days', sa.Integer(), nullable=False, server_default='15'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── 2. Add update-metadata columns to server_packages ─────────────────
    op.add_column('server_packages',
        sa.Column('update_available', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('server_packages',
        sa.Column('available_version', sa.String(length=100), nullable=True))
    op.add_column('server_packages',
        sa.Column('update_type', sa.String(length=50), nullable=True))
    op.add_column('server_packages',
        sa.Column('repository', sa.String(length=150), nullable=True))

    # Index for fast "show updates for this server" queries
    op.create_index(
        'ix_server_packages_update_available',
        'server_packages',
        ['update_available'],
    )


def downgrade():
    op.drop_index('ix_server_packages_update_available', table_name='server_packages')
    op.drop_column('server_packages', 'repository')
    op.drop_column('server_packages', 'update_type')
    op.drop_column('server_packages', 'available_version')
    op.drop_column('server_packages', 'update_available')
    op.drop_table('compliance_config')

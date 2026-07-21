"""Add last_connected_at to directory_config.

Revision ID: f3a2c1d8e049
Revises: e1f4b8c92a3d
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3a2c1d8e049'
down_revision = 'e1f4b8c92a3d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('directory_config',
        sa.Column('last_connected_at', sa.DateTime, nullable=True)
    )


def downgrade() -> None:
    op.drop_column('directory_config', 'last_connected_at')

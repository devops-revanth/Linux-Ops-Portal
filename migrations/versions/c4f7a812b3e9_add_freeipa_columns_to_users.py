"""Add FreeIPA columns to users table.

Adds:
  display_name  – human-friendly name from LDAP cn attribute
  role          – portal role (administrator | operator | readonly)
  auth_source   – "local" or "ldap"
  last_login    – timestamp of most recent successful login

Revision ID: c4f7a812b3e9
Revises: 811d76d3ea4d
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c4f7a812b3e9'
down_revision = '811d76d3ea4d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('display_name', sa.String(128), nullable=True),
    )
    op.add_column(
        'users',
        sa.Column(
            'role',
            sa.String(32),
            nullable=False,
            server_default='operator',
        ),
    )
    op.add_column(
        'users',
        sa.Column(
            'auth_source',
            sa.String(32),
            nullable=False,
            server_default='local',
        ),
    )
    op.add_column(
        'users',
        sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('users', 'last_login')
    op.drop_column('users', 'auth_source')
    op.drop_column('users', 'role')
    op.drop_column('users', 'display_name')

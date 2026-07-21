"""Add extended columns to audit_logs table.

Adds:
  module       – first segment of action string (indexed for filtering)
  ip_address   – client IP at time of action
  auth_source  – "local" or "ldap" (mirrors User.auth_source)
  result       – "success" or "failed" (default success)
  user_agent   – HTTP User-Agent header
  session_id   – Flask session ID if available
  before_values– JSON snapshot of object before change
  after_values – JSON snapshot of object after change

Revision ID: d8e3f921a047
Revises: c4f7a812b3e9
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'd8e3f921a047'
down_revision = 'c4f7a812b3e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('audit_logs', sa.Column('module', sa.String(50), nullable=True))
    op.add_column('audit_logs', sa.Column('ip_address', sa.String(45), nullable=True))
    op.add_column('audit_logs', sa.Column('auth_source', sa.String(32), nullable=True))
    op.add_column('audit_logs', sa.Column('result', sa.String(20), nullable=False, server_default='success'))
    op.add_column('audit_logs', sa.Column('user_agent', sa.String(500), nullable=True))
    op.add_column('audit_logs', sa.Column('session_id', sa.String(128), nullable=True))
    op.add_column('audit_logs', sa.Column('before_values', sa.Text, nullable=True))
    op.add_column('audit_logs', sa.Column('after_values', sa.Text, nullable=True))

    # Index module for filter queries
    op.create_index('ix_audit_logs_module', 'audit_logs', ['module'])
    op.create_index('ix_audit_logs_result', 'audit_logs', ['result'])

    # Back-fill module from the first segment of action for existing rows
    op.execute("""
        UPDATE audit_logs
        SET module = split_part(action, '.', 1)
        WHERE module IS NULL
    """)


def downgrade() -> None:
    op.drop_index('ix_audit_logs_result', 'audit_logs')
    op.drop_index('ix_audit_logs_module', 'audit_logs')
    op.drop_column('audit_logs', 'after_values')
    op.drop_column('audit_logs', 'before_values')
    op.drop_column('audit_logs', 'session_id')
    op.drop_column('audit_logs', 'user_agent')
    op.drop_column('audit_logs', 'result')
    op.drop_column('audit_logs', 'auth_source')
    op.drop_column('audit_logs', 'ip_address')
    op.drop_column('audit_logs', 'module')

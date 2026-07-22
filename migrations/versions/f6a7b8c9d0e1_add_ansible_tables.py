"""Add Ansible integration tables

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-22

"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    # ── ansible_config (singleton) ────────────────────────────────────────── #
    op.create_table(
        'ansible_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='false'),
        # Connection
        sa.Column('control_node', sa.String(255), nullable=True),
        sa.Column('port', sa.Integer(), nullable=False, server_default='22'),
        sa.Column('username', sa.String(100), nullable=True),
        # Auth
        sa.Column('auth_method', sa.String(20), nullable=False, server_default='key'),
        sa.Column('ssh_password_enc', sa.Text(), nullable=True),
        sa.Column('ssh_private_key_enc', sa.Text(), nullable=True),
        # Vault
        sa.Column('vault_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('vault_password_enc', sa.Text(), nullable=True),
        # Paths
        sa.Column('inventory_source', sa.String(20), nullable=False, server_default='static'),
        sa.Column('inventory_path', sa.Text(), nullable=False, server_default='/etc/ansible/hosts'),
        sa.Column('playbook_dir', sa.Text(), nullable=False, server_default='/etc/ansible/playbooks'),
        sa.Column('collections_dir', sa.Text(), nullable=True),
        # Options
        sa.Column('host_key_checking', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('connection_timeout', sa.Integer(), nullable=False, server_default='30'),
        # Status
        sa.Column('connection_status', sa.String(50), nullable=False, server_default='Not Tested'),
        sa.Column('last_test_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_connected_at', sa.DateTime(timezone=True), nullable=True),
        # Discovered info
        sa.Column('ansible_version', sa.String(50), nullable=True),
        sa.Column('python_version', sa.String(50), nullable=True),
        sa.Column('last_inventory_hosts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_playbooks_found', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_validation_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── ansible_inventory_hosts ───────────────────────────────────────────── #
    op.create_table(
        'ansible_inventory_hosts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hostname', sa.String(255), nullable=False),
        sa.Column('groups', sa.Text(), nullable=True),
        sa.Column('discovered_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hostname', name='uq_ansible_inventory_hostname'),
    )
    op.create_index('ix_ansible_inventory_hosts_hostname',
                    'ansible_inventory_hosts', ['hostname'])


def downgrade():
    op.drop_index('ix_ansible_inventory_hosts_hostname',
                  table_name='ansible_inventory_hosts')
    op.drop_table('ansible_inventory_hosts')
    op.drop_table('ansible_config')

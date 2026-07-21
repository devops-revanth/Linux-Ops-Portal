"""Add directory_config and ldap_group_mappings tables.

directory_config  – singleton row storing LDAP/AD/FreeIPA/OpenLDAP settings
                    (bind password is stored Fernet-encrypted)
ldap_group_mappings – configurable LDAP group DN → portal role mapping

Revision ID: e1f4b8c92a3d
Revises: d8e3f921a047
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1f4b8c92a3d'
down_revision = 'd8e3f921a047'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'directory_config',
        sa.Column('id',                 sa.Integer,     primary_key=True),
        sa.Column('directory_type',     sa.String(20),  nullable=False, server_default='freeipa'),
        sa.Column('uri',                sa.String(255), nullable=False, server_default=''),
        sa.Column('port',               sa.Integer,     nullable=True),
        sa.Column('base_dn',            sa.String(255), nullable=False, server_default=''),
        sa.Column('bind_dn',            sa.String(255), nullable=False, server_default=''),
        sa.Column('bind_password_enc',  sa.Text,        nullable=True),
        sa.Column('user_search_base',   sa.String(255), nullable=True),
        sa.Column('group_search_base',  sa.String(255), nullable=True),
        sa.Column('user_search_filter', sa.String(255), nullable=False, server_default='(uid={username})'),
        sa.Column('group_search_filter',sa.String(255), nullable=False, server_default='(objectClass=groupOfNames)'),
        sa.Column('ssl_enabled',        sa.Boolean,     nullable=False, server_default=sa.true()),
        sa.Column('verify_cert',        sa.Boolean,     nullable=False, server_default=sa.true()),
        sa.Column('ca_cert_path',       sa.String(500), nullable=True),
        sa.Column('timeout',            sa.Integer,     nullable=False, server_default='10'),
        sa.Column('default_role',       sa.String(32),  nullable=False, server_default='operator'),
        sa.Column('is_enabled',         sa.Boolean,     nullable=False, server_default=sa.false()),
        sa.Column('created_at',         sa.DateTime,    nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at',         sa.DateTime,    nullable=False, server_default=sa.text('NOW()')),
    )

    op.create_table(
        'ldap_group_mappings',
        sa.Column('id',         sa.Integer,     primary_key=True),
        sa.Column('group_dn',   sa.String(500), nullable=False, unique=True, index=True),
        sa.Column('role',       sa.String(32),  nullable=False, server_default='operator'),
        sa.Column('created_at', sa.DateTime,    nullable=False, server_default=sa.text('NOW()')),
    )


def downgrade() -> None:
    op.drop_table('ldap_group_mappings')
    op.drop_table('directory_config')

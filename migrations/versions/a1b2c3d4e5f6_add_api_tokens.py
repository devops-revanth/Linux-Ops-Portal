"""add api_tokens table

Revision ID: a1b2c3d4e5f6
Revises: f199ced7abac
Create Date: 2026-07-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f199ced7abac'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'api_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
    )
    with op.batch_alter_table('api_tokens', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_api_tokens_token'), ['token'], unique=True
        )


def downgrade():
    with op.batch_alter_table('api_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_api_tokens_token'))
    op.drop_table('api_tokens')

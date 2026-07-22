"""Add date_format and time_format to localization_config

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "localization_config",
        sa.Column(
            "date_format",
            sa.String(20),
            nullable=False,
            server_default="MMM_DD_YYYY",
            comment="Date display format key",
        ),
    )
    op.add_column(
        "localization_config",
        sa.Column(
            "time_format",
            sa.String(2),
            nullable=False,
            server_default="12",
            comment="Time display format key (12 | 24)",
        ),
    )


def downgrade():
    op.drop_column("localization_config", "time_format")
    op.drop_column("localization_config", "date_format")

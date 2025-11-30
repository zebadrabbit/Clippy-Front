"""Remove scheduling fields from tiers table

Revision ID: 1ca9d4fcb507
Revises: 8d275967a8cb
Create Date: 2025-11-29 06:20:34.119372

"""
import os

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "1ca9d4fcb507"
down_revision = "8d275967a8cb"
branch_labels = None
depends_on = None


def upgrade():
    # Get table prefix from environment
    table_prefix = os.environ.get("TABLE_PREFIX", "")
    tiers_table = f"{table_prefix}tiers"

    # Drop scheduling-related columns from tiers table
    with op.batch_alter_table(tiers_table, schema=None) as batch_op:
        batch_op.drop_column("max_schedules_per_user")
        batch_op.drop_column("can_schedule_tasks")


def downgrade():
    # Get table prefix from environment
    table_prefix = os.environ.get("TABLE_PREFIX", "")
    tiers_table = f"{table_prefix}tiers"

    # Restore scheduling columns if needed
    with op.batch_alter_table(tiers_table, schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "can_schedule_tasks", sa.Boolean(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column(
                "max_schedules_per_user",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )

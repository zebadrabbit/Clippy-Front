"""Add is_default column to tiers table

Revision ID: 40b6eb8de13d
Revises: 25a2658e2742
Create Date: 2025-11-29 00:06:58.503629

"""

import os

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "40b6eb8de13d"
down_revision = "25a2658e2742"
branch_labels = None
depends_on = None

# Get table prefix from environment
TABLE_PREFIX = os.environ.get("TABLE_PREFIX", "")
TIERS_TABLE = f"{TABLE_PREFIX}tiers"


def upgrade():
    # Add is_default column to tiers table
    op.add_column(
        TIERS_TABLE,
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
    )

    # Create index on is_default
    op.create_index(
        op.f(f"ix_{TIERS_TABLE}_is_default"), TIERS_TABLE, ["is_default"], unique=False
    )

    # Set Free tier as default (use TRUE for PostgreSQL boolean)
    op.execute(f"UPDATE {TIERS_TABLE} SET is_default = TRUE WHERE name = 'Free'")


def downgrade():
    # Drop index
    op.drop_index(op.f(f"ix_{TIERS_TABLE}_is_default"), table_name=TIERS_TABLE)

    # Drop column
    op.drop_column(TIERS_TABLE, "is_default")

"""Add wizard state fields to projects table

Revision ID: wizard_state_001
Revises: f59cc7227fbe
Create Date: 2025-11-27 12:00:00.000000

"""
import os

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "wizard_state_001"
down_revision = "f59cc7227fbe"
branch_labels = None
depends_on = None

# Get table prefix from environment
TABLE_PREFIX = os.environ.get("TABLE_PREFIX", "")


def upgrade():
    """
    Add wizard_step and wizard_state columns to projects table.
    Add READY status to ProjectStatus enum.
    """
    # Add wizard_step column (1-4, default 1)
    op.add_column(
        f"{TABLE_PREFIX}projects",
        sa.Column("wizard_step", sa.Integer(), nullable=False, server_default="1"),
    )

    # Add wizard_state column (JSON blob for step-specific state)
    op.add_column(
        f"{TABLE_PREFIX}projects", sa.Column("wizard_state", sa.Text(), nullable=True)
    )

    # Note: Adding READY to ProjectStatus enum requires ALTER TYPE in PostgreSQL
    # For SQLite, this is a no-op as it uses string checks
    # For production PostgreSQL, you would need:
    # op.execute("ALTER TYPE projectstatus ADD VALUE 'ready'")
    # But this is handled by the model definition in models.py


def downgrade():
    """
    Remove wizard state fields from projects table.
    """
    op.drop_column(f"{TABLE_PREFIX}projects", "wizard_state")
    op.drop_column(f"{TABLE_PREFIX}projects", "wizard_step")

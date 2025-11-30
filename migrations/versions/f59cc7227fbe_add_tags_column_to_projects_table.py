"""Add tags column to projects table

Revision ID: f59cc7227fbe
Revises: 643de2b99af0
Create Date: 2025-11-26 00:51:49.579142

"""
import os

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f59cc7227fbe"
down_revision = "643de2b99af0"
branch_labels = None
depends_on = None


def upgrade():
    # Add tags column to projects table
    table_prefix = os.environ.get("TABLE_PREFIX", "")
    projects_table = f"{table_prefix}projects"
    op.add_column(projects_table, sa.Column("tags", sa.Text(), nullable=True))


def downgrade():
    # Remove tags column from projects table
    table_prefix = os.environ.get("TABLE_PREFIX", "")
    projects_table = f"{table_prefix}projects"
    op.drop_column(projects_table, "tags")

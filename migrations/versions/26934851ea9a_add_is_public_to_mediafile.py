"""Add is_public to MediaFile

Revision ID: 26934851ea9a
Revises: f59cc7227fbe
Create Date: 2025-11-26 05:48:03.826228

"""
import os

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "26934851ea9a"
down_revision = "f59cc7227fbe"
branch_labels = None
depends_on = None


def upgrade():
    # Get table prefix from environment
    table_prefix = os.environ.get("TABLE_PREFIX", "")
    media_files_table = f"{table_prefix}media_files"

    # Add is_public column to media_files
    with op.batch_alter_table(media_files_table, schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_public", sa.Boolean(), nullable=False, server_default="false")
        )
        batch_op.create_index(
            f"ix_{media_files_table}_is_public", ["is_public"], unique=False
        )


def downgrade():
    # Get table prefix from environment
    table_prefix = os.environ.get("TABLE_PREFIX", "")
    media_files_table = f"{table_prefix}media_files"

    # Remove is_public column from media_files
    with op.batch_alter_table(media_files_table, schema=None) as batch_op:
        batch_op.drop_index(f"ix_{media_files_table}_is_public")
        batch_op.drop_column("is_public")

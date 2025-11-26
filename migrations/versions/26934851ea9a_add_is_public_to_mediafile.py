"""Add is_public to MediaFile

Revision ID: 26934851ea9a
Revises: f59cc7227fbe
Create Date: 2025-11-26 05:48:03.826228

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "26934851ea9a"
down_revision = "f59cc7227fbe"
branch_labels = None
depends_on = None


def upgrade():
    # Add is_public column to dev_media_files
    with op.batch_alter_table("dev_media_files", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_public", sa.Boolean(), nullable=False, server_default="false")
        )
        batch_op.create_index(
            batch_op.f("ix_dev_media_files_is_public"), ["is_public"], unique=False
        )


def downgrade():
    # Remove is_public column from dev_media_files
    with op.batch_alter_table("dev_media_files", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_dev_media_files_is_public"))
        batch_op.drop_column("is_public")

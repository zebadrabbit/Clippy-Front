"""Add preview fields to projects table

Revision ID: 4180cd624069
Revises: 658ecf23832f
Create Date: 2025-11-19 20:15:05.228120

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "4180cd624069"
down_revision = "658ecf23832f"
branch_labels = None
depends_on = None


def upgrade():
    # Add preview fields to projects table
    op.add_column(
        "projects", sa.Column("preview_filename", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "projects", sa.Column("preview_file_size", sa.BigInteger(), nullable=True)
    )


def downgrade():
    # Remove preview fields from projects table
    op.drop_column("projects", "preview_file_size")
    op.drop_column("projects", "preview_filename")

"""add user timezone

Revision ID: 8f21c3a7b9a1
Revises: df12ab34add6
Create Date: 2025-10-26 00:00:00.000000
"""
# ruff: noqa: I001
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "8f21c3a7b9a1"
down_revision = "df12ab34add6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("timezone", sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("timezone")

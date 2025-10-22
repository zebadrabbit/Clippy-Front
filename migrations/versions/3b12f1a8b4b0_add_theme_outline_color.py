"""add theme.outline_color

Revision ID: 3b12f1a8b4b0
Revises: 084c3bc02dc5
Create Date: 2025-10-21 12:10:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "3b12f1a8b4b0"
down_revision = "084c3bc02dc5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("themes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("outline_color", sa.String(length=20), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("themes", schema=None) as batch_op:
        batch_op.drop_column("outline_color")

"""add theme.media_color_compilation

Revision ID: 6c8fe9b7c8a1
Revises: 3b12f1a8b4b0
Create Date: 2025-10-21 14:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "6c8fe9b7c8a1"
down_revision = "3b12f1a8b4b0"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col["name"] for col in inspector.get_columns("themes")}

    if "media_color_compilation" not in existing_cols:
        with op.batch_alter_table("themes", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "media_color_compilation", sa.String(length=20), nullable=True
                )
            )
    else:
        # No-op if the column already exists
        pass


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col["name"] for col in inspector.get_columns("themes")}

    if "media_color_compilation" in existing_cols:
        with op.batch_alter_table("themes", schema=None) as batch_op:
            batch_op.drop_column("media_color_compilation")
    else:
        # No-op
        pass

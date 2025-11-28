"""Remove is_template from CompilationTask

Revision ID: 71c2f4043df4
Revises: 90d0c642098a
Create Date: 2025-11-27 21:32:45.022117

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "71c2f4043df4"
down_revision = "90d0c642098a"
branch_labels = None
depends_on = None


def upgrade():
    # Drop is_template column from compilation_tasks table
    with op.batch_alter_table("compilation_tasks", schema=None) as batch_op:
        batch_op.drop_column("is_template")


def downgrade():
    # Re-add is_template column to compilation_tasks table
    with op.batch_alter_table("compilation_tasks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_template", sa.Boolean(), nullable=False, server_default="false"
            )
        )
        # Remove server default after column creation
        batch_op.alter_column("is_template", server_default=None)

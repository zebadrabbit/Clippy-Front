"""Add is_template to CompilationTask

Revision ID: 9d86f89dd601
Revises: 8f21c3a7b9a1
Create Date: 2025-11-19 19:21:03.909887

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "9d86f89dd601"
down_revision = "8f21c3a7b9a1"
branch_labels = None
depends_on = None


def upgrade():
    # Add is_template column to compilation_tasks table
    with op.batch_alter_table("compilation_tasks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_template", sa.Boolean(), nullable=False, server_default="false"
            )
        )

    # Remove server default after adding the column
    with op.batch_alter_table("compilation_tasks", schema=None) as batch_op:
        batch_op.alter_column("is_template", server_default=None)


def downgrade():
    # Remove is_template column from compilation_tasks table
    with op.batch_alter_table("compilation_tasks", schema=None) as batch_op:
        batch_op.drop_column("is_template")

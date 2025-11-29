"""remove_compilation_tasks_and_schedules

Revision ID: 8d275967a8cb
Revises: 62197abac220
Create Date: 2025-11-29 04:02:08.510812

"""
import os

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "8d275967a8cb"
down_revision = "62197abac220"
branch_labels = None
depends_on = None

# Get table prefix from environment
_TABLE_PREFIX = os.environ.get("TABLE_PREFIX", "")


def upgrade():
    # Drop tables if they exist (they may not exist in all environments)
    connection = op.get_bind()

    # Drop scheduled_tasks first (has foreign key to compilation_tasks)
    if connection.dialect.has_table(connection, f"{_TABLE_PREFIX}scheduled_tasks"):
        op.drop_table(f"{_TABLE_PREFIX}scheduled_tasks")

    # Drop compilation_schedules (alternative table name)
    if connection.dialect.has_table(
        connection, f"{_TABLE_PREFIX}compilation_schedules"
    ):
        op.drop_table(f"{_TABLE_PREFIX}compilation_schedules")

    # Drop compilation_tasks
    if connection.dialect.has_table(connection, f"{_TABLE_PREFIX}compilation_tasks"):
        op.drop_table(f"{_TABLE_PREFIX}compilation_tasks")


def downgrade():
    # Recreate compilation_tasks
    op.create_table(
        f"{_TABLE_PREFIX}compilation_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_project_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{_TABLE_PREFIX}users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["last_project_id"], [f"{_TABLE_PREFIX}projects.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Recreate compilation_schedules
    op.create_table(
        f"{_TABLE_PREFIX}compilation_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("schedule_type", sa.String(length=50), nullable=False),
        sa.Column("run_at", sa.DateTime(), nullable=True),
        sa.Column("time_of_day", sa.Time(), nullable=True),
        sa.Column("day_of_week", sa.Integer(), nullable=True),
        sa.Column("day_of_month", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(length=100), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run", sa.DateTime(), nullable=True),
        sa.Column("last_run", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"], [f"{_TABLE_PREFIX}compilation_tasks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

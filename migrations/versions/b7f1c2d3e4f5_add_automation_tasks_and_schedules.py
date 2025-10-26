"""add automation tasks and schedules

Revision ID: b7f1c2d3e4f5
Revises: 9f3a1b2c4d5e_add_tiers_and_render_usage
Create Date: 2025-10-25
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

# revision identifiers, used by Alembic.
revision = "b7f1c2d3e4f5"
down_revision = "9f3a1b2c4d5e"
branch_labels = None
depends_on = None


def upgrade():
    # Ensure enum for schedule type exists (idempotent on PostgreSQL)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Create type if not exists using DO block to avoid duplicate errors
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'scheduletype') THEN
                    CREATE TYPE scheduletype AS ENUM ('once', 'daily', 'weekly');
                END IF;
            END$$;
            """
        )
        scheduletype = pg.ENUM(
            "once", "daily", "weekly", name="scheduletype", create_type=False
        )
    else:
        # Fallback for non-PG (should not be used in production)
        scheduletype = sa.Enum("once", "daily", "weekly", name="scheduletype")

    # compilation_tasks table
    op.create_table(
        "compilation_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "params",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb")
            if op.get_bind().dialect.name == "postgresql"
            else sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
    )

    # scheduled_tasks table
    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("compilation_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("schedule_type", scheduletype, nullable=False, server_default="once"),
        sa.Column("run_at", sa.DateTime(), nullable=True),
        sa.Column("daily_time", sa.String(length=5), nullable=True),
        sa.Column("weekly_day", sa.Integer(), nullable=True),
        sa.Column(
            "timezone", sa.String(length=64), nullable=True, server_default="UTC"
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # Tier flags
    op.add_column(
        "tiers",
        sa.Column(
            "can_schedule_tasks",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tiers",
        sa.Column(
            "max_schedules_per_user", sa.Integer(), nullable=False, server_default="1"
        ),
    )

    # Optional: clear server defaults for app-level control
    try:
        op.alter_column("tiers", "can_schedule_tasks", server_default=None)
        op.alter_column("tiers", "max_schedules_per_user", server_default=None)
        op.alter_column("scheduled_tasks", "enabled", server_default=None)
    except Exception:
        pass


def downgrade():
    # Drop tier columns
    try:
        op.drop_column("tiers", "max_schedules_per_user")
        op.drop_column("tiers", "can_schedule_tasks")
    except Exception:
        pass

    # Drop tables
    op.drop_table("scheduled_tasks")
    op.drop_table("compilation_tasks")

    # Drop enum
    try:
        scheduletype = sa.Enum("once", "daily", "weekly", name="scheduletype")
        scheduletype.drop(op.get_bind(), checkfirst=True)
    except Exception:
        pass

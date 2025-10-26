"""add monthly schedule and fix enum storage

Revision ID: df12ab34add6
Revises: b7f1c2d3e4f5_add_automation_tasks_and_schedules
Create Date: 2025-10-26
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "df12ab34add6"
down_revision = "b7f1c2d3e4f5_add_automation_tasks_and_schedules"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # Ensure the enum stores lowercase values and add 'monthly'
    if bind.dialect.name == "postgresql":
        # Add 'monthly' to existing enum if not already present
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_enum e
                    JOIN pg_type t ON e.enumtypid = t.oid
                    WHERE t.typname = 'scheduletype' AND e.enumlabel = 'monthly'
                ) THEN
                    ALTER TYPE scheduletype ADD VALUE 'monthly';
                END IF;
            END$$;
            """
        )
    # Add monthly_day column
    op.add_column(
        "scheduled_tasks", sa.Column("monthly_day", sa.Integer(), nullable=True)
    )


def downgrade():
    # Remove monthly_day column (note: enum values can't be easily removed in PG)
    try:
        op.drop_column("scheduled_tasks", "monthly_day")
    except Exception:
        pass

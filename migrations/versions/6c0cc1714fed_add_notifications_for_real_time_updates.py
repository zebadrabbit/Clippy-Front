"""add notifications for real-time updates

Revision ID: 6c0cc1714fed
Revises: cef649e306cd
Create Date: 2025-11-19 22:48:12.867766

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "6c0cc1714fed"
down_revision = "cef649e306cd"
branch_labels = None
depends_on = None


def upgrade():
    # Create notifications table (reuses existing activitytype enum)
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "notification_type",
            postgresql.ENUM(
                "team_created",
                "team_updated",
                "team_deleted",
                "member_added",
                "member_removed",
                "member_left",
                "member_role_changed",
                "project_created",
                "project_shared",
                "project_unshared",
                "project_updated",
                "project_deleted",
                "preview_generated",
                "compilation_started",
                "compilation_completed",
                "compilation_failed",
                name="activitytype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for efficient queries
    op.create_index(
        "ix_notifications_user_created",
        "notifications",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_notifications_user_read", "notifications", ["user_id", "is_read"]
    )


def downgrade():
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")

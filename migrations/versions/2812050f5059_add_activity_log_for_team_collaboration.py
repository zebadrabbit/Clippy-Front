"""add activity log for team collaboration

Revision ID: 2812050f5059
Revises: b944d5591ef1
Create Date: 2025-11-19 22:17:58.505715

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "2812050f5059"
down_revision = "b944d5591ef1"
branch_labels = None
depends_on = None


def upgrade():
    # Create ActivityType enum
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE activitytype AS ENUM (
                'team_created', 'team_updated', 'team_deleted',
                'member_added', 'member_removed', 'member_left', 'member_role_changed',
                'project_created', 'project_shared', 'project_unshared', 'project_updated', 'project_deleted',
                'preview_generated', 'compilation_started', 'compilation_completed', 'compilation_failed'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """
    )

    # Create activity_logs table
    op.create_table(
        "activity_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "activity_type",
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
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for efficient querying
    op.create_index(
        "idx_activity_team_created", "activity_logs", ["team_id", "created_at"]
    )
    op.create_index(
        "idx_activity_project_created", "activity_logs", ["project_id", "created_at"]
    )
    op.create_index(
        "idx_activity_user_created", "activity_logs", ["user_id", "created_at"]
    )


def downgrade():
    # Drop indexes
    op.drop_index("idx_activity_user_created", table_name="activity_logs")
    op.drop_index("idx_activity_project_created", table_name="activity_logs")
    op.drop_index("idx_activity_team_created", table_name="activity_logs")

    # Drop table
    op.drop_table("activity_logs")

    # Drop enum (will fail if other tables use it, which is fine for safety)
    op.execute("DROP TYPE IF EXISTS activitytype")

"""add team invitations

Revision ID: e851aa63174f
Revises: 2812050f5059
Create Date: 2025-11-19 22:28:01.170295

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e851aa63174f"
down_revision = "2812050f5059"
branch_labels = None
depends_on = None


def upgrade():
    # Create team_invitations table
    op.create_table(
        "team_invitations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("invited_by_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column(
            "role",
            postgresql.ENUM(
                "owner",
                "admin",
                "editor",
                "viewer",
                name="teamrole",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )

    # Create indexes
    op.create_index(
        "ix_team_invitations_email", "team_invitations", ["email"], unique=False
    )
    op.create_index(
        "ix_team_invitations_token", "team_invitations", ["token"], unique=True
    )


def downgrade():
    # Drop indexes
    op.drop_index("ix_team_invitations_token", table_name="team_invitations")
    op.drop_index("ix_team_invitations_email", table_name="team_invitations")

    # Drop table
    op.drop_table("team_invitations")

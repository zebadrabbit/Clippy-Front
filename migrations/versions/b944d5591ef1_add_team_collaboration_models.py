"""add_team_collaboration_models

Revision ID: b944d5591ef1
Revises: 4180cd624069
Create Date: 2025-11-19 21:45:01.008609

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b944d5591ef1"
down_revision = "4180cd624069"
branch_labels = None
depends_on = None


def upgrade():
    # Create TeamRole enum
    teamrole_enum = postgresql.ENUM(
        "owner", "admin", "editor", "viewer", name="teamrole", create_type=True
    )
    teamrole_enum.create(op.get_bind(), checkfirst=True)

    # Create teams table
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create team_memberships table
    op.create_table(
        "team_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "owner", "admin", "editor", "viewer", name="teamrole", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "user_id", name="unique_team_member"),
    )

    # Add team_id to projects table
    op.add_column("projects", sa.Column("team_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_projects_team_id", "projects", "teams", ["team_id"], ["id"]
    )


def downgrade():
    # Remove team_id from projects
    op.drop_constraint("fk_projects_team_id", "projects", type_="foreignkey")
    op.drop_column("projects", "team_id")

    # Drop tables
    op.drop_table("team_memberships")
    op.drop_table("teams")

    # Drop enum
    op.execute("DROP TYPE teamrole")

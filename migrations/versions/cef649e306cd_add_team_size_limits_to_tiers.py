"""add team size limits to tiers

Revision ID: cef649e306cd
Revises: e851aa63174f
Create Date: 2025-11-19 22:45:09.147333

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "cef649e306cd"
down_revision = "e851aa63174f"
branch_labels = None
depends_on = None


def upgrade():
    # Add team collaboration limit columns to tiers table
    op.add_column("tiers", sa.Column("max_teams_owned", sa.Integer(), nullable=True))
    op.add_column("tiers", sa.Column("max_team_members", sa.Integer(), nullable=True))

    # Update existing tiers with default values
    # Free tier: 1 team, 3 members
    op.execute(
        """
        UPDATE tiers
        SET max_teams_owned = 1, max_team_members = 3
        WHERE name = 'Free'
    """
    )

    # Pro tier: 5 teams, 15 members
    op.execute(
        """
        UPDATE tiers
        SET max_teams_owned = 5, max_team_members = 15
        WHERE name = 'Pro'
    """
    )

    # Unlimited tier: NULL (unlimited)
    op.execute(
        """
        UPDATE tiers
        SET max_teams_owned = NULL, max_team_members = NULL
        WHERE name = 'Unlimited' OR is_unlimited = true
    """
    )


def downgrade():
    op.drop_column("tiers", "max_team_members")
    op.drop_column("tiers", "max_teams_owned")

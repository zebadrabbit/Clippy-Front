"""Add platform presets and project export settings

Revision ID: 658ecf23832f
Revises: bd703e60dd61
Create Date: 2025-11-19 19:55:48.101339

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "658ecf23832f"
down_revision = "bd703e60dd61"
branch_labels = None
depends_on = None


def upgrade():
    # Create platform preset enum
    op.execute(
        """
        CREATE TYPE platformpreset AS ENUM (
            'youtube', 'youtube_shorts', 'tiktok',
            'instagram_feed', 'instagram_reel', 'instagram_story',
            'twitter', 'facebook', 'twitch', 'custom'
        )
        """
    )

    # Add new columns to projects table
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "platform_preset",
                sa.Enum(
                    "youtube",
                    "youtube_shorts",
                    "tiktok",
                    "instagram_feed",
                    "instagram_reel",
                    "instagram_story",
                    "twitter",
                    "facebook",
                    "twitch",
                    "custom",
                    name="platformpreset",
                ),
                nullable=True,
                server_default="custom",
            )
        )
        batch_op.add_column(
            sa.Column(
                "quality", sa.String(length=20), nullable=True, server_default="high"
            )
        )
        batch_op.add_column(
            sa.Column("fps", sa.Integer(), nullable=True, server_default="30")
        )
        batch_op.add_column(
            sa.Column(
                "transitions_enabled",
                sa.Boolean(),
                nullable=True,
                server_default="true",
            )
        )
        batch_op.add_column(
            sa.Column(
                "watermark_enabled", sa.Boolean(), nullable=True, server_default="false"
            )
        )
        batch_op.add_column(sa.Column("intro_media_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("outro_media_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_projects_intro_media", "media_files", ["intro_media_id"], ["id"]
        )
        batch_op.create_foreign_key(
            "fk_projects_outro_media", "media_files", ["outro_media_id"], ["id"]
        )


def downgrade():
    # Remove foreign keys and columns
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.drop_constraint("fk_projects_outro_media", type_="foreignkey")
        batch_op.drop_constraint("fk_projects_intro_media", type_="foreignkey")
        batch_op.drop_column("outro_media_id")
        batch_op.drop_column("intro_media_id")
        batch_op.drop_column("watermark_enabled")
        batch_op.drop_column("transitions_enabled")
        batch_op.drop_column("fps")
        batch_op.drop_column("quality")
        batch_op.drop_column("platform_preset")

    # Drop enum type
    op.execute("DROP TYPE platformpreset")

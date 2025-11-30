"""Add analytics models for clip creators games and engagement tracking

Revision ID: 75f559145b10
Revises: 87869c82a866
Create Date: 2025-11-30 03:31:55.947039

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "75f559145b11"
down_revision = "87869c82a866"
branch_labels = None
depends_on = None


def upgrade():
    # Create ClipAnalytics table
    op.create_table(
        "dev_clip_analytics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("clip_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("creator_name", sa.String(length=120), nullable=True),
        sa.Column("creator_id", sa.String(length=64), nullable=True),
        sa.Column("creator_platform", sa.String(length=20), nullable=True),
        sa.Column("game_name", sa.String(length=120), nullable=True),
        sa.Column("game_id", sa.String(length=64), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("discord_shares", sa.Integer(), nullable=True),
        sa.Column("discord_reactions", sa.Integer(), nullable=True),
        sa.Column("discord_reaction_types", sa.Text(), nullable=True),
        sa.Column("clip_created_at", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["clip_id"],
            ["dev_clips.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["dev_users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "dev_ix_analytics_created",
        "dev_clip_analytics",
        ["user_id", "clip_created_at"],
        unique=False,
    )
    op.create_index(
        "dev_ix_analytics_creator",
        "dev_clip_analytics",
        ["user_id", "creator_name"],
        unique=False,
    )
    op.create_index(
        "dev_ix_analytics_user_game",
        "dev_clip_analytics",
        ["user_id", "game_name"],
        unique=False,
    )
    op.create_index(
        "ix_dev_clip_analytics_clip_created_at",
        "dev_clip_analytics",
        ["clip_created_at"],
        unique=False,
    )
    op.create_index(
        "ix_dev_clip_analytics_clip_id", "dev_clip_analytics", ["clip_id"], unique=False
    )
    op.create_index(
        "ix_dev_clip_analytics_creator_id",
        "dev_clip_analytics",
        ["creator_id"],
        unique=False,
    )
    op.create_index(
        "ix_dev_clip_analytics_creator_name",
        "dev_clip_analytics",
        ["creator_name"],
        unique=False,
    )
    op.create_index(
        "ix_dev_clip_analytics_game_name",
        "dev_clip_analytics",
        ["game_name"],
        unique=False,
    )
    op.create_index(
        "ix_dev_clip_analytics_user_id", "dev_clip_analytics", ["user_id"], unique=False
    )

    # Create CreatorAnalytics table
    op.create_table(
        "dev_creator_analytics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("creator_name", sa.String(length=120), nullable=False),
        sa.Column("creator_id", sa.String(length=64), nullable=True),
        sa.Column("creator_platform", sa.String(length=20), nullable=True),
        sa.Column("creator_avatar_url", sa.String(length=500), nullable=True),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("period_type", sa.String(length=20), nullable=True),
        sa.Column("clip_count", sa.Integer(), nullable=True),
        sa.Column("total_views", sa.Integer(), nullable=True),
        sa.Column("avg_view_count", sa.Float(), nullable=True),
        sa.Column("discord_shares", sa.Integer(), nullable=True),
        sa.Column("discord_reactions", sa.Integer(), nullable=True),
        sa.Column("unique_games", sa.Integer(), nullable=True),
        sa.Column("top_game", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["dev_users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "creator_name",
            "period_type",
            "period_start",
            name="dev_uq_creator_analytics_period",
        ),
    )
    op.create_index(
        "dev_ix_creator_analytics_period",
        "dev_creator_analytics",
        ["user_id", "period_type", "period_start"],
        unique=False,
    )
    op.create_index(
        "ix_dev_creator_analytics_creator_id",
        "dev_creator_analytics",
        ["creator_id"],
        unique=False,
    )
    op.create_index(
        "ix_dev_creator_analytics_creator_name",
        "dev_creator_analytics",
        ["creator_name"],
        unique=False,
    )
    op.create_index(
        "ix_dev_creator_analytics_period_start",
        "dev_creator_analytics",
        ["period_start"],
        unique=False,
    )
    op.create_index(
        "ix_dev_creator_analytics_user_id",
        "dev_creator_analytics",
        ["user_id"],
        unique=False,
    )

    # Create GameAnalytics table
    op.create_table(
        "dev_game_analytics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("game_name", sa.String(length=120), nullable=False),
        sa.Column("game_id", sa.String(length=64), nullable=True),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("period_type", sa.String(length=20), nullable=True),
        sa.Column("clip_count", sa.Integer(), nullable=True),
        sa.Column("total_views", sa.Integer(), nullable=True),
        sa.Column("total_duration", sa.Float(), nullable=True),
        sa.Column("avg_view_count", sa.Float(), nullable=True),
        sa.Column("discord_shares", sa.Integer(), nullable=True),
        sa.Column("discord_reactions", sa.Integer(), nullable=True),
        sa.Column("top_clip_id", sa.Integer(), nullable=True),
        sa.Column("top_clip_views", sa.Integer(), nullable=True),
        sa.Column("unique_creators", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["dev_users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "game_name",
            "period_type",
            "period_start",
            name="dev_uq_game_analytics_period",
        ),
    )
    op.create_index(
        "dev_ix_game_analytics_period",
        "dev_game_analytics",
        ["user_id", "period_type", "period_start"],
        unique=False,
    )
    op.create_index(
        "ix_dev_game_analytics_game_name",
        "dev_game_analytics",
        ["game_name"],
        unique=False,
    )
    op.create_index(
        "ix_dev_game_analytics_period_start",
        "dev_game_analytics",
        ["period_start"],
        unique=False,
    )
    op.create_index(
        "ix_dev_game_analytics_user_id", "dev_game_analytics", ["user_id"], unique=False
    )

    # Create PushSubscription table
    op.create_table(
        "dev_push_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh_key", sa.Text(), nullable=False),
        sa.Column("auth_key", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["dev_users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "dev_ix_push_endpoint", "dev_push_subscriptions", ["endpoint"], unique=True
    )
    op.create_index(
        "ix_dev_push_subscriptions_user_id",
        "dev_push_subscriptions",
        ["user_id"],
        unique=False,
    )


def downgrade():
    # Drop tables in reverse order
    op.drop_index(
        "ix_dev_push_subscriptions_user_id", table_name="dev_push_subscriptions"
    )
    op.drop_index("dev_ix_push_endpoint", table_name="dev_push_subscriptions")
    op.drop_table("dev_push_subscriptions")

    op.drop_index("ix_dev_game_analytics_user_id", table_name="dev_game_analytics")
    op.drop_index("ix_dev_game_analytics_period_start", table_name="dev_game_analytics")
    op.drop_index("ix_dev_game_analytics_game_name", table_name="dev_game_analytics")
    op.drop_index("dev_ix_game_analytics_period", table_name="dev_game_analytics")
    op.drop_table("dev_game_analytics")

    op.drop_index(
        "ix_dev_creator_analytics_user_id", table_name="dev_creator_analytics"
    )
    op.drop_index(
        "ix_dev_creator_analytics_period_start", table_name="dev_creator_analytics"
    )
    op.drop_index(
        "ix_dev_creator_analytics_creator_name", table_name="dev_creator_analytics"
    )
    op.drop_index(
        "ix_dev_creator_analytics_creator_id", table_name="dev_creator_analytics"
    )
    op.drop_index("dev_ix_creator_analytics_period", table_name="dev_creator_analytics")
    op.drop_table("dev_creator_analytics")

    op.drop_index("ix_dev_clip_analytics_user_id", table_name="dev_clip_analytics")
    op.drop_index("ix_dev_clip_analytics_game_name", table_name="dev_clip_analytics")
    op.drop_index("ix_dev_clip_analytics_creator_name", table_name="dev_clip_analytics")
    op.drop_index("ix_dev_clip_analytics_creator_id", table_name="dev_clip_analytics")
    op.drop_index("ix_dev_clip_analytics_clip_id", table_name="dev_clip_analytics")
    op.drop_index(
        "ix_dev_clip_analytics_clip_created_at", table_name="dev_clip_analytics"
    )
    op.drop_index("dev_ix_analytics_user_game", table_name="dev_clip_analytics")
    op.drop_index("dev_ix_analytics_creator", table_name="dev_clip_analytics")
    op.drop_index("dev_ix_analytics_created", table_name="dev_clip_analytics")
    op.drop_table("dev_clip_analytics")

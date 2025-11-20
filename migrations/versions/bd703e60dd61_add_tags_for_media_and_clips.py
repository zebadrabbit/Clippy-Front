"""Add tags for media and clips

Revision ID: bd703e60dd61
Revises: 9d86f89dd601
Create Date: 2025-11-19 19:50:44.288359

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "bd703e60dd61"
down_revision = "9d86f89dd601"
branch_labels = None
depends_on = None


def upgrade():
    # Create tags table
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "color", sa.String(length=7), nullable=True, server_default="#6c757d"
        ),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("is_global", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=True, server_default="0"),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["tags.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "slug", name="uix_user_tag_slug"),
    )
    op.create_index("ix_tags_name", "tags", ["name"])
    op.create_index("ix_tags_slug", "tags", ["slug"])
    op.create_index("ix_tags_user_name", "tags", ["user_id", "name"])

    # Create media_tags association table
    op.create_table(
        "media_tags",
        sa.Column("media_file_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(
            ["media_file_id"],
            ["media_files.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.id"],
        ),
        sa.PrimaryKeyConstraint("media_file_id", "tag_id"),
    )

    # Create clip_tags association table
    op.create_table(
        "clip_tags",
        sa.Column("clip_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(
            ["clip_id"],
            ["clips.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.id"],
        ),
        sa.PrimaryKeyConstraint("clip_id", "tag_id"),
    )


def downgrade():
    op.drop_table("clip_tags")
    op.drop_table("media_tags")
    op.drop_index("ix_tags_user_name", "tags")
    op.drop_index("ix_tags_slug", "tags")
    op.drop_index("ix_tags_name", "tags")
    op.drop_table("tags")

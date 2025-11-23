"""add_music_to_mediatype_enum

Revision ID: deb9cecee237
Revises: 6bc4412d51c7
Create Date: 2025-11-23 03:19:18.966262

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "deb9cecee237"
down_revision = "6bc4412d51c7"
branch_labels = None
depends_on = None


def upgrade():
    # Add 'MUSIC' to the mediatype enum
    op.execute("ALTER TYPE mediatype ADD VALUE IF NOT EXISTS 'MUSIC'")


def downgrade():
    # PostgreSQL doesn't support removing enum values directly
    # Would require recreating the enum type, which is complex
    # Leave as no-op since removing enum values is destructive
    pass

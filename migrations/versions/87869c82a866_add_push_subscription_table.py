"""add_push_subscription_table

Revision ID: 87869c82a866
Revises: 1ca9d4fcb507
Create Date: 2025-11-29 18:45:42.511052

"""
import os

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "87869c82a866"
down_revision = "1ca9d4fcb507"
branch_labels = None
depends_on = None


def upgrade():
    # Get table prefix from environment
    table_prefix = os.environ.get("TABLE_PREFIX", "")

    # Table names with prefix
    user_table = f"{table_prefix}users"
    push_subscription_table = f"{table_prefix}push_subscriptions"

    # Create push_subscription table
    op.create_table(
        push_subscription_table,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.String(length=512), nullable=False),
        sa.Column("p256dh_key", sa.String(length=128), nullable=False),
        sa.Column("auth_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], [f"{user_table}.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create unique index on endpoint
    op.create_index(
        f"ix_{push_subscription_table}_endpoint",
        push_subscription_table,
        ["endpoint"],
        unique=True,
    )

    # Create index on user_id for faster lookups
    op.create_index(
        f"ix_{push_subscription_table}_user_id",
        push_subscription_table,
        ["user_id"],
        unique=False,
    )


def downgrade():
    # Get table prefix from environment
    table_prefix = os.environ.get("TABLE_PREFIX", "")
    push_subscription_table = f"{table_prefix}push_subscription"

    # Drop indexes
    op.drop_index(
        f"ix_{push_subscription_table}_user_id", table_name=push_subscription_table
    )
    op.drop_index(
        f"ix_{push_subscription_table}_endpoint", table_name=push_subscription_table
    )

    # Drop table
    op.drop_table(push_subscription_table)

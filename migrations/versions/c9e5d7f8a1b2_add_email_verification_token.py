"""add email verification token

Revision ID: c9e5d7f8a1b2
Revises: 6c0cc1714fed
Create Date: 2025-11-22 03:06:30.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c9e5d7f8a1b2"
down_revision = "6c0cc1714fed"
branch_labels = None
depends_on = None


def upgrade():
    # Add email verification token columns
    op.add_column(
        "users", sa.Column("email_verification_token", sa.String(255), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("email_verification_token_created_at", sa.DateTime(), nullable=True),
    )
    op.add_column("users", sa.Column("pending_email", sa.String(120), nullable=True))


def downgrade():
    # Remove email verification token columns
    op.drop_column("users", "pending_email")
    op.drop_column("users", "email_verification_token_created_at")
    op.drop_column("users", "email_verification_token")

"""add tiers and render_usage tables, users.tier_id

Revision ID: 9f3a1b2c4d5e
Revises: 6c8fe9b7c8a1
Create Date: 2025-10-23 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "9f3a1b2c4d5e"
down_revision = "6c8fe9b7c8a1"
branch_labels = None
depends_on = None


def _table_exists(bind, name: str) -> bool:
    insp = sa.inspect(bind)
    try:
        return name in insp.get_table_names()
    except Exception:
        return False


def _column_exists(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    try:
        cols = {c["name"] for c in insp.get_columns(table)}
        return column in cols
    except Exception:
        return False


def upgrade():
    bind = op.get_bind()

    # Create tiers table if it doesn't exist
    if not _table_exists(bind, "tiers"):
        op.create_table(
            "tiers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "name", sa.String(length=100), nullable=False, index=True, unique=True
            ),
            sa.Column("description", sa.Text()),
            sa.Column("storage_limit_bytes", sa.BigInteger(), nullable=True),
            sa.Column("render_time_limit_seconds", sa.BigInteger(), nullable=True),
            sa.Column(
                "apply_watermark",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("TRUE"),
            ),
            sa.Column(
                "is_unlimited",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("FALSE"),
            ),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("TRUE"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        # Create index for name if server didn't apply from arg (SQLite compatibility)
        try:
            op.create_index("ix_tiers_name", "tiers", ["name"], unique=True)
        except Exception:
            pass

    # Add users.tier_id if missing
    if _table_exists(bind, "users") and not _column_exists(bind, "users", "tier_id"):
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(sa.Column("tier_id", sa.Integer(), nullable=True))
            try:
                batch_op.create_foreign_key(
                    "fk_users_tier_id_tiers",
                    "tiers",
                    ["tier_id"],
                    ["id"],
                    ondelete=None,
                )
            except Exception:
                # If FK creation fails (e.g., backend limitations), continue with nullable column
                pass

    # Create render_usage table if it doesn't exist
    if not _table_exists(bind, "render_usage"):
        op.create_table(
            "render_usage",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("seconds_used", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"], name="fk_render_usage_user_id_users"
            ),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["projects.id"],
                name="fk_render_usage_project_id_projects",
            ),
        )


def downgrade():
    bind = op.get_bind()

    # Drop users.tier_id (FK first) if exists
    if _table_exists(bind, "users") and _column_exists(bind, "users", "tier_id"):
        try:
            with op.batch_alter_table("users", schema=None) as batch_op:
                try:
                    batch_op.drop_constraint(
                        "fk_users_tier_id_tiers", type_="foreignkey"
                    )
                except Exception:
                    pass
                batch_op.drop_column("tier_id")
        except Exception:
            pass

    # Drop render_usage table if exists
    if _table_exists(bind, "render_usage"):
        try:
            op.drop_table("render_usage")
        except Exception:
            pass

    # Drop tiers table if exists
    if _table_exists(bind, "tiers"):
        try:
            # Best-effort: drop index if we created it
            try:
                op.drop_index("ix_tiers_name", table_name="tiers")
            except Exception:
                pass
            op.drop_table("tiers")
        except Exception:
            pass

"""diary entries and day targets

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-19 10:01:19.183512
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "diary_day_targets",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("calories_kcal", sa.Integer(), nullable=False),
        sa.Column("protein_g", sa.Integer(), nullable=False),
        sa.Column("carbohydrate_g", sa.Integer(), nullable=False),
        sa.Column("fat_g", sa.Integer(), nullable=False),
        sa.Column("fiber_g", sa.Integer(), nullable=False),
        sa.Column("macro_split", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_diary_day_targets_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "day", name=op.f("pk_diary_day_targets")),
    )
    op.create_table(
        "diary_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("meal", sa.String(length=16), nullable=False),
        sa.Column("servings", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("food_id", sa.String(length=64), nullable=False),
        sa.Column("food_name", sa.String(length=255), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("serving_id", sa.String(length=64), nullable=False),
        sa.Column("serving_description", sa.String(length=255), nullable=False),
        sa.Column("calories_kcal", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("protein_g", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("carbohydrate_g", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("fat_g", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("fiber_g", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("sugar_g", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("saturated_fat_g", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("sodium_mg", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "servings > 0 AND servings <= 100", name=op.f("ck_diary_entries_servings_range")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_diary_entries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diary_entries")),
    )
    op.create_index(
        "ix_diary_entries_user_id_day", "diary_entries", ["user_id", "day"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_diary_entries_user_id_day", table_name="diary_entries")
    op.drop_table("diary_entries")
    op.drop_table("diary_day_targets")

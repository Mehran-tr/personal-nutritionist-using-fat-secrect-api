import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from nutritionist.core.db import Base, TimestampMixin

_NUTRIENT = Numeric(10, 3)


class DiaryEntryRecord(TimestampMixin, Base):
    __tablename__ = "diary_entries"
    __table_args__ = (
        CheckConstraint("servings > 0 AND servings <= 100", name="servings_range"),
        # The hot query: one user's day.
        Index("ix_diary_entries_user_id_day", "user_id", "day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    meal: Mapped[str] = mapped_column(String(16), nullable=False)
    servings: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Snapshot of the food at logging time.
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    food_id: Mapped[str] = mapped_column(String(64), nullable=False)
    food_name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(255))
    serving_id: Mapped[str] = mapped_column(String(64), nullable=False)
    serving_description: Mapped[str] = mapped_column(String(255), nullable=False)

    # Per-serving nutrients at logging time.
    calories_kcal: Mapped[Decimal] = mapped_column(_NUTRIENT, nullable=False)
    protein_g: Mapped[Decimal] = mapped_column(_NUTRIENT, nullable=False)
    carbohydrate_g: Mapped[Decimal] = mapped_column(_NUTRIENT, nullable=False)
    fat_g: Mapped[Decimal] = mapped_column(_NUTRIENT, nullable=False)
    fiber_g: Mapped[Decimal | None] = mapped_column(_NUTRIENT)
    sugar_g: Mapped[Decimal | None] = mapped_column(_NUTRIENT)
    saturated_fat_g: Mapped[Decimal | None] = mapped_column(_NUTRIENT)
    sodium_mg: Mapped[Decimal | None] = mapped_column(_NUTRIENT)


class DayTargetsRecord(Base):
    __tablename__ = "diary_day_targets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    calories_kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    protein_g: Mapped[int] = mapped_column(Integer, nullable=False)
    carbohydrate_g: Mapped[int] = mapped_column(Integer, nullable=False)
    fat_g: Mapped[int] = mapped_column(Integer, nullable=False)
    fiber_g: Mapped[int] = mapped_column(Integer, nullable=False)
    macro_split: Mapped[str] = mapped_column(String(32), nullable=False)

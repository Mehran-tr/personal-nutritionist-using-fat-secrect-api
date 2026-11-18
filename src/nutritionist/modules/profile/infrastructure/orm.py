import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from nutritionist.core.db import Base, TimestampMixin


class ProfileRecord(TimestampMixin, Base):
    __tablename__ = "profiles"
    # Last line of defence; the domain validates the same ranges with friendly messages.
    __table_args__ = (
        CheckConstraint("height_cm BETWEEN 100 AND 250", name="height_range"),
        CheckConstraint("weight_kg BETWEEN 30 AND 300", name="weight_range"),
    )

    # The only cross-module link is this FK, by id. No ORM relationship to UserRecord.
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Enums stored as text: adding a value never needs an ALTER TYPE migration.
    sex: Mapped[str] = mapped_column(String(16), nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    height_cm: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    activity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    goal: Mapped[str] = mapped_column(String(32), nullable=False)
    dietary_preferences: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, server_default="{}"
    )

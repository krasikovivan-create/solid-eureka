from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class StylistSession(TimestampMixin, Base):
    __tablename__ = "stylist_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class StylistMessage(TimestampMixin, Base):
    __tablename__ = "stylist_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("stylist_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)


class StylistRequest(TimestampMixin, Base):
    """Учёт каждого обращения к Claude API: токены, стоимость, итог."""

    __tablename__ = "stylist_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    model: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16), default="chat")
    api_calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="ok", index=True)
    error: Mapped[str | None] = mapped_column(String(512))


class StylistLook(TimestampMixin, Base):
    __tablename__ = "stylist_looks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[int | None] = mapped_column(
        ForeignKey("stylist_requests.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(256))
    explanation: Mapped[str] = mapped_column(Text, default="")
    # [{"product_id": 1, "variant_id": 5 | null, "title": "...", "price": 2990, "size": "M"}]
    items: Mapped[list] = mapped_column(JSON, default=list)
    total: Mapped[int] = mapped_column(Integer, default=0)
    added_to_cart_at: Mapped[datetime | None] = mapped_column(DateTime)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))

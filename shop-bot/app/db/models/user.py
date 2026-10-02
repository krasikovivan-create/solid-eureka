from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, utcnow


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(256), default="")
    phone: Mapped[str | None] = mapped_column(String(20))
    utm_source: Mapped[str | None] = mapped_column(String(64), index=True)
    referrer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    referral_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)
    bonus_balance: Mapped[int] = mapped_column(Integer, default=0)
    pd_consent_at: Mapped[datetime | None] = mapped_column(DateTime)
    cart_promo_code: Mapped[str | None] = mapped_column(String(32))
    cart_reminded_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserEventLog(TimestampMixin, Base):
    """Воронка: старт, добавление в корзину, начало оформления, заказ, оплата."""

    __tablename__ = "user_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(32), index=True)


class Admin(TimestampMixin, Base):
    """Админы, добавленные через бота (в дополнение к ADMIN_IDS из окружения)."""

    __tablename__ = "admins"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    added_by: Mapped[int | None] = mapped_column(BigInteger)


class ShopSetting(Base):
    """Настройки магазина, которые админ меняет прямо в боте (название, баннер и т.п.)."""

    __tablename__ = "shop_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")

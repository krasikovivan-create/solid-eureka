from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow
from app.db.models.catalog import ProductVariant


class CartItem(TimestampMixin, Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("user_id", "variant_id", name="uq_cart_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("product_variants.id", ondelete="CASCADE"), index=True
    )
    qty: Mapped[int] = mapped_column(Integer, default=1)
    stylist_look_id: Mapped[int | None] = mapped_column(
        ForeignKey("stylist_looks.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    variant: Mapped[ProductVariant] = relationship()


class PromoCode(TimestampMixin, Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    kind: Mapped[str] = mapped_column(String(16))  # percent | fixed
    value: Mapped[int] = mapped_column(Integer)
    min_total: Mapped[int] = mapped_column(Integer, default=0)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime)
    max_uses: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PromoUsage(TimestampMixin, Base):
    __tablename__ = "promo_usages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    promo_id: Mapped[int] = mapped_column(
        ForeignKey("promo_codes.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))


class DeliveryZone(Base):
    __tablename__ = "delivery_zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    # Города зоны через запятую, в нижнем регистре: «москва, зеленоград».
    cities: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    tariffs: Mapped[list[DeliveryTariff]] = relationship(
        back_populates="zone", cascade="all, delete-orphan", order_by="DeliveryTariff.id"
    )

    @property
    def city_list(self) -> list[str]:
        return [c.strip().lower() for c in self.cities.split(",") if c.strip()]


class DeliveryTariff(Base):
    __tablename__ = "delivery_tariffs"
    __table_args__ = (UniqueConstraint("zone_id", "method", name="uq_tariff"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zone_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_zones.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[str] = mapped_column(String(16))
    price: Mapped[int] = mapped_column(Integer, default=0)
    free_from: Mapped[int | None] = mapped_column(Integer)
    days_min: Mapped[int] = mapped_column(Integer, default=1)
    days_max: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    zone: Mapped[DeliveryZone] = relationship(back_populates="tariffs")


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    customer_name: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str] = mapped_column(String(20))
    delivery_method: Mapped[str] = mapped_column(String(16))
    city: Mapped[str] = mapped_column(String(128), default="")
    address: Mapped[str] = mapped_column(String(512), default="")
    delivery_price: Mapped[int] = mapped_column(Integer, default=0)
    delivery_days_min: Mapped[int] = mapped_column(Integer, default=0)
    delivery_days_max: Mapped[int] = mapped_column(Integer, default=0)
    items_total: Mapped[int] = mapped_column(Integer)
    discount: Mapped[int] = mapped_column(Integer, default=0)
    bonus_used: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer)
    promo_id: Mapped[int | None] = mapped_column(ForeignKey("promo_codes.id", ondelete="SET NULL"))
    payment_method: Mapped[str] = mapped_column(String(16))
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    telegram_charge_id: Mapped[str | None] = mapped_column(String(256))
    provider_charge_id: Mapped[str | None] = mapped_column(String(256))
    stock_deducted: Mapped[bool] = mapped_column(Boolean, default=False)
    track_number: Mapped[str | None] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(String(512))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )
    history: Mapped[list[OrderStatusHistory]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderStatusHistory.id",
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="SET NULL")
    )
    # Снимок товара на момент заказа — история не ломается при правке каталога.
    title: Mapped[str] = mapped_column(String(256))
    size: Mapped[str] = mapped_column(String(16))
    color: Mapped[str] = mapped_column(String(32))
    price: Mapped[int] = mapped_column(Integer)
    qty: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")

    @property
    def subtotal(self) -> int:
        return self.price * self.qty


class OrderStatusHistory(TimestampMixin, Base):
    __tablename__ = "order_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16))
    changed_by: Mapped[int | None] = mapped_column(BigInteger)
    comment: Mapped[str | None] = mapped_column(String(512))

    order: Mapped[Order] = relationship(back_populates="history")

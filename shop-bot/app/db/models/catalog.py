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


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(128))
    emoji: Mapped[str] = mapped_column(String(8), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    products: Mapped[list[Product]] = relationship(back_populates="category")

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.title}".strip()


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    composition: Mapped[str] = mapped_column(String(512), default="")
    gender: Mapped[str] = mapped_column(String(16), default="unisex", index=True)
    style: Mapped[str] = mapped_column(String(16), default="casual", index=True)
    price: Mapped[int] = mapped_column(Integer, index=True)
    old_price: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # Нижний регистр названия, цветов и категории: регистронезависимый поиск по кириллице
    # одинаково работает в SQLite и PostgreSQL.
    search_text: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    category: Mapped[Category] = relationship(back_populates="products")
    photos: Mapped[list[ProductPhoto]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductPhoto.sort",
    )
    variants: Mapped[list[ProductVariant]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductVariant.id",
    )

    @property
    def total_stock(self) -> int:
        return sum(v.stock for v in self.variants)

    @property
    def discount_percent(self) -> int:
        if self.old_price and self.old_price > self.price:
            return round((self.old_price - self.price) * 100 / self.old_price)
        return 0

    @property
    def colors(self) -> list[str]:
        seen: list[str] = []
        for v in self.variants:
            if v.color not in seen:
                seen.append(v.color)
        return seen

    def rebuild_search_text(self, category_title: str = "") -> None:
        parts = [self.title, *self.colors, category_title, self.composition]
        self.search_text = " ".join(p for p in parts if p).lower()


class ProductPhoto(Base):
    __tablename__ = "product_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str | None] = mapped_column(String(1024))
    # file_id Telegram: заполняется после первой отправки по URL или при загрузке админом.
    file_id: Mapped[str | None] = mapped_column(String(256))
    sort: Mapped[int] = mapped_column(Integer, default=0)

    product: Mapped[Product] = relationship(back_populates="photos")

    @property
    def media(self) -> str:
        return self.file_id or self.url or ""


class ProductVariant(Base):
    __tablename__ = "product_variants"
    __table_args__ = (UniqueConstraint("product_id", "size", "color", name="uq_variant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    size: Mapped[str] = mapped_column(String(16))
    color: Mapped[str] = mapped_column(String(32))
    stock: Mapped[int] = mapped_column(Integer, default=0)

    product: Mapped[Product] = relationship(back_populates="variants")

    @property
    def label(self) -> str:
        return f"{self.size} · {self.color}"


class ProductView(TimestampMixin, Base):
    __tablename__ = "product_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )


class Favorite(TimestampMixin, Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_favorite"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    # Последняя цена и наличие, о которых пользователь знает, — для уведомлений.
    last_price: Mapped[int] = mapped_column(Integer)
    was_in_stock: Mapped[bool] = mapped_column(Boolean, default=True)

    product: Mapped[Product] = relationship()

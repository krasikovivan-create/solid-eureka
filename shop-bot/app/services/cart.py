"""Корзина: добавление, изменение количества, итог с промокодом."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import UserEvent
from app.db.models import CartItem, ProductVariant, PromoCode, User
from app.repositories.users import UserRepository
from app.services.promo import PromoError, PromoService, calc_discount


class CartError(Exception):
    pass


class VariantUnavailable(CartError):
    pass


class NotEnoughStock(CartError):
    def __init__(self, available: int) -> None:
        self.available = available
        super().__init__(f"available={available}")


@dataclass(slots=True)
class CartLine:
    item_id: int
    product_id: int
    variant_id: int
    title: str
    size: str
    color: str
    price: int
    qty: int
    stock: int
    look_id: int | None = None

    @property
    def subtotal(self) -> int:
        return self.price * self.qty

    @property
    def ok(self) -> bool:
        return self.stock >= self.qty


@dataclass(slots=True)
class CartSummary:
    lines: list[CartLine] = field(default_factory=list)
    items_total: int = 0
    promo: PromoCode | None = None
    discount: int = 0
    promo_error: PromoError | None = None
    promo_code: str | None = None

    @property
    def total(self) -> int:
        return self.items_total - self.discount

    @property
    def is_empty(self) -> bool:
        return not self.lines

    @property
    def has_problems(self) -> bool:
        return any(not line.ok for line in self.lines)

    @property
    def count(self) -> int:
        return sum(line.qty for line in self.lines)


class CartService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _items(self, user_id: int) -> list[CartItem]:
        stmt = (
            select(CartItem)
            .where(CartItem.user_id == user_id)
            .options(selectinload(CartItem.variant).selectinload(ProductVariant.product))
            .order_by(CartItem.id)
        )
        return list((await self.session.scalars(stmt)).all())

    async def count(self, user_id: int) -> int:
        stmt = select(func.coalesce(func.sum(CartItem.qty), 0)).where(CartItem.user_id == user_id)
        return int(await self.session.scalar(stmt) or 0)

    async def add(
        self, user_id: int, variant_id: int, qty: int = 1, look_id: int | None = None
    ) -> CartItem:
        variant = await self.session.get(
            ProductVariant, variant_id, options=[selectinload(ProductVariant.product)]
        )
        if variant is None or not variant.product.is_active:
            raise VariantUnavailable
        item = await self.session.scalar(
            select(CartItem).where(CartItem.user_id == user_id, CartItem.variant_id == variant_id)
        )
        current = item.qty if item else 0
        if current + qty > variant.stock:
            raise NotEnoughStock(max(variant.stock - current, 0))
        if item is None:
            item = CartItem(
                user_id=user_id, variant_id=variant_id, qty=qty, stylist_look_id=look_id
            )
            self.session.add(item)
        else:
            item.qty = current + qty
            if look_id:
                item.stylist_look_id = look_id
        await UserRepository(self.session).log_event(user_id, UserEvent.CART_ADD)
        await self.session.flush()
        return item

    async def change_qty(self, user_id: int, item_id: int, delta: int) -> int:
        """Меняет количество на delta. Возвращает новое количество (0 — позиция удалена)."""
        item = await self.session.scalar(
            select(CartItem)
            .where(CartItem.id == item_id, CartItem.user_id == user_id)
            .options(selectinload(CartItem.variant))
        )
        if item is None:
            raise VariantUnavailable
        new_qty = item.qty + delta
        if new_qty <= 0:
            await self.session.delete(item)
            await self.session.flush()
            return 0
        if delta > 0 and new_qty > item.variant.stock:
            raise NotEnoughStock(item.variant.stock)
        item.qty = new_qty
        await self.session.flush()
        return new_qty

    async def remove(self, user_id: int, item_id: int) -> None:
        await self.session.execute(
            delete(CartItem).where(CartItem.id == item_id, CartItem.user_id == user_id)
        )

    async def clear(self, user_id: int) -> None:
        await self.session.execute(delete(CartItem).where(CartItem.user_id == user_id))

    async def summary(self, user: User) -> CartSummary:
        summary = CartSummary()
        for item in await self._items(user.id):
            variant = item.variant
            product = variant.product
            if not product.is_active:
                continue
            summary.lines.append(
                CartLine(
                    item_id=item.id,
                    product_id=product.id,
                    variant_id=variant.id,
                    title=product.title,
                    size=variant.size,
                    color=variant.color,
                    price=product.price,
                    qty=item.qty,
                    stock=variant.stock,
                    look_id=item.stylist_look_id,
                )
            )
        summary.items_total = sum(line.subtotal for line in summary.lines)
        if user.cart_promo_code and summary.lines:
            summary.promo_code = user.cart_promo_code
            try:
                promo = await PromoService(self.session).validate(
                    user.cart_promo_code, user.id, summary.items_total
                )
            except PromoError as exc:
                summary.promo_error = exc
            else:
                summary.promo = promo
                summary.discount = calc_discount(promo, summary.items_total)
        return summary

    async def apply_promo(self, user: User, code: str) -> CartSummary:
        """Проверяет промокод на текущей корзине и запоминает его. PromoError — если не подходит."""
        user.cart_promo_code = None
        summary = await self.summary(user)
        promo = await PromoService(self.session).validate(code, user.id, summary.items_total)
        user.cart_promo_code = promo.code
        summary.promo = promo
        summary.promo_code = promo.code
        summary.discount = calc_discount(promo, summary.items_total)
        return summary

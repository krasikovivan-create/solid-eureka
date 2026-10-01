"""Избранное и уведомления о скидке / поступлении товара."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Favorite, Product


@dataclass(slots=True)
class FavoriteAlert:
    user_id: int
    product_id: int
    title: str
    kind: str  # price_drop | back_in_stock
    old_price: int
    new_price: int


class FavoriteService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def is_favorite(self, user_id: int, product_id: int) -> bool:
        stmt = select(Favorite.id).where(
            Favorite.user_id == user_id, Favorite.product_id == product_id
        )
        return await self.session.scalar(stmt) is not None

    async def toggle(self, user_id: int, product: Product) -> bool:
        """Добавляет или убирает товар. Возвращает True, если теперь он в избранном."""
        if await self.is_favorite(user_id, product.id):
            await self.session.execute(
                delete(Favorite).where(
                    Favorite.user_id == user_id, Favorite.product_id == product.id
                )
            )
            return False
        self.session.add(
            Favorite(
                user_id=user_id,
                product_id=product.id,
                last_price=product.price,
                was_in_stock=product.total_stock > 0,
            )
        )
        await self.session.flush()
        return True

    async def list(self, user_id: int) -> list[Product]:
        stmt = (
            select(Product)
            .join(Favorite, Favorite.product_id == Product.id)
            .where(Favorite.user_id == user_id, Product.is_active.is_(True))
            .options(selectinload(Product.variants))
            .order_by(Favorite.id.desc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def collect_alerts(self, product_ids: list[int] | None = None) -> list[FavoriteAlert]:
        """Находит подешевевшие и вернувшиеся в продажу товары и обновляет «известное» состояние."""
        stmt = (
            select(Favorite)
            .join(Product, Product.id == Favorite.product_id)
            .where(Product.is_active.is_(True))
            .options(selectinload(Favorite.product).selectinload(Product.variants))
        )
        if product_ids:
            stmt = stmt.where(Favorite.product_id.in_(product_ids))
        alerts: list[FavoriteAlert] = []
        for fav in (await self.session.scalars(stmt)).all():
            product = fav.product
            in_stock = product.total_stock > 0
            if in_stock and product.price < fav.last_price:
                alerts.append(
                    FavoriteAlert(
                        fav.user_id,
                        product.id,
                        product.title,
                        "price_drop",
                        fav.last_price,
                        product.price,
                    )
                )
            elif in_stock and not fav.was_in_stock:
                alerts.append(
                    FavoriteAlert(
                        fav.user_id,
                        product.id,
                        product.title,
                        "back_in_stock",
                        fav.last_price,
                        product.price,
                    )
                )
            fav.last_price = product.price
            fav.was_in_stock = in_stock
        return alerts

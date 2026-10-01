"""Рекомендации: похожие товары, «с этим покупают», персональная подборка."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import SUCCESSFUL_STATUSES, Gender
from app.db.models import Favorite, Order, OrderItem, Product, ProductView
from app.repositories.catalog import CatalogRepository, ProductFilter


def similarity(base: Product, other: Product) -> float:
    score = 0.0
    if other.category_id == base.category_id:
        score += 3
    if other.style == base.style:
        score += 2
    if other.gender == base.gender or Gender.UNISEX in (other.gender, base.gender):
        score += 1
    if base.price:
        diff = abs(other.price - base.price) / base.price
        score += max(0.0, 1.5 - diff * 3)  # до +1.5 при близкой цене
    if set(other.colors) & set(base.colors):
        score += 0.5
    return score


class RecommendationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.catalog = CatalogRepository(session)

    async def _candidates(self, exclude: list[int], limit: int = 200) -> list[Product]:
        return await self.catalog.list_products(
            ProductFilter(exclude_ids=exclude, sort="new"), limit=limit
        )

    async def similar(self, product: Product, limit: int = 6) -> list[Product]:
        candidates = await self._candidates([product.id])
        candidates.sort(key=lambda p: (-similarity(product, p), abs(p.price - product.price)))
        return [p for p in candidates if similarity(product, p) >= 3][:limit]

    async def bought_with(self, product_id: int, limit: int = 6) -> list[Product]:
        orders_with_product = (
            select(OrderItem.order_id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(OrderItem.product_id == product_id, Order.status.in_(SUCCESSFUL_STATUSES))
        )
        stmt = (
            select(OrderItem.product_id, func.count(OrderItem.id).label("cnt"))
            .where(
                OrderItem.order_id.in_(orders_with_product),
                OrderItem.product_id.is_not(None),
                OrderItem.product_id != product_id,
            )
            .group_by(OrderItem.product_id)
            .order_by(func.count(OrderItem.id).desc())
            .limit(limit * 3)
        )
        ids = [row[0] for row in (await self.session.execute(stmt)).all()]
        products = [
            p for p in await self.catalog.get_products(ids) if p.is_active and p.total_stock
        ]
        if len(products) < limit:
            base = await self.catalog.get_product(product_id)
            if base is not None:
                seen = {p.id for p in products}
                for p in await self.similar(base, limit):
                    if p.id not in seen and p.category_id != base.category_id:
                        products.append(p)
        return products[:limit]

    async def popular(self, limit: int = 6, exclude: list[int] | None = None) -> list[Product]:
        stmt = (
            select(OrderItem.product_id, func.sum(OrderItem.qty))
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.status.in_(SUCCESSFUL_STATUSES), OrderItem.product_id.is_not(None))
            .group_by(OrderItem.product_id)
            .order_by(func.sum(OrderItem.qty).desc())
            .limit(limit * 3)
        )
        ids = [row[0] for row in (await self.session.execute(stmt)).all()]
        exclude_set = set(exclude or [])
        products = [
            p
            for p in await self.catalog.get_products(ids)
            if p.is_active and p.total_stock and p.id not in exclude_set
        ]
        if len(products) < limit:
            seen = {p.id for p in products} | exclude_set
            for p in await self._candidates(list(seen), limit=limit):
                products.append(p)
        return products[:limit]

    async def personal(self, user_id: int, limit: int = 8) -> tuple[list[Product], bool]:
        """Подборка по просмотрам, избранному и покупкам.

        Второй элемент — True, если подборка персональная (а не просто популярное).
        """
        viewed = list(
            (
                await self.session.scalars(
                    select(ProductView.product_id)
                    .where(ProductView.user_id == user_id)
                    .order_by(ProductView.id.desc())
                    .limit(50)
                )
            ).all()
        )
        favorites = list(
            (
                await self.session.scalars(
                    select(Favorite.product_id).where(Favorite.user_id == user_id)
                )
            ).all()
        )
        purchased = list(
            (
                await self.session.scalars(
                    select(OrderItem.product_id)
                    .join(Order, Order.id == OrderItem.order_id)
                    .where(Order.user_id == user_id, OrderItem.product_id.is_not(None))
                )
            ).all()
        )
        weights: Counter[int] = Counter()
        for pid in viewed:
            weights[pid] += 1
        for pid in favorites:
            weights[pid] += 3
        for pid in purchased:
            weights[pid] += 4
        if not weights:
            return await self.popular(limit), False

        signals = await self.catalog.get_products(list(weights))
        category_w: Counter[int] = Counter()
        style_w: Counter[str] = Counter()
        gender_w: Counter[str] = Counter()
        prices: list[int] = []
        for product in signals:
            w = weights[product.id]
            category_w[product.category_id] += w
            style_w[product.style] += w
            gender_w[product.gender] += w
            prices.append(product.price)
        avg_price = sum(prices) / len(prices) if prices else 0
        top_gender = gender_w.most_common(1)[0][0] if gender_w else None

        # Купленное не предлагаем повторно; просмотренное — можно, но с меньшим весом.
        candidates = await self._candidates(list(set(purchased)))

        def score(p: Product) -> float:
            s = category_w[p.category_id] * 1.0 + style_w[p.style] * 0.7
            if top_gender and (p.gender == top_gender or p.gender == Gender.UNISEX):
                s += 2
            if avg_price:
                s += max(0.0, 2 - abs(p.price - avg_price) / avg_price * 2)
            if p.discount_percent:
                s += 0.5
            if p.id in weights:
                s *= 0.5
            return s

        candidates.sort(key=score, reverse=True)
        return candidates[:limit], True

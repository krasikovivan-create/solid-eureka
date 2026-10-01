"""Складские остатки: списание при оплате/подтверждении и возврат при отмене."""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order, ProductVariant

logger = logging.getLogger(__name__)


class OutOfStock(Exception):
    def __init__(self, shortages: dict[int, int]) -> None:
        # variant_id -> сколько не хватает
        self.shortages = shortages
        super().__init__(f"shortages={shortages}")


class StockService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _lock_variants(self, ids: list[int]) -> dict[int, ProductVariant]:
        if not ids:
            return {}
        stmt = (
            select(ProductVariant)
            .where(ProductVariant.id.in_(ids))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return {v.id: v for v in (await self.session.scalars(stmt)).all()}

    @staticmethod
    def _needs(order: Order) -> dict[int, int]:
        needs: dict[int, int] = defaultdict(int)
        for item in order.items:
            if item.variant_id is not None:
                needs[item.variant_id] += item.qty
        return needs

    async def check(self, order: Order) -> dict[int, int]:
        """Возвращает нехватку по вариантам (пусто — всё в наличии)."""
        return await self.check_needs(self._needs(order))

    async def check_needs(self, needs: dict[int, int]) -> dict[int, int]:
        """Проверяет потребность {variant_id: qty}.

        Строки вариантов блокируются (SELECT … FOR UPDATE) до конца транзакции.
        """
        variants = await self._lock_variants(list(needs))
        shortages = {}
        for variant_id, qty in needs.items():
            available = variants[variant_id].stock if variant_id in variants else 0
            if available < qty:
                shortages[variant_id] = qty - available
        return shortages

    async def deduct(self, order: Order, allow_partial: bool = False) -> dict[int, int]:
        """Списывает остатки по заказу.

        allow_partial=False — при нехватке ничего не списывает и бросает OutOfStock.
        allow_partial=True — списывает сколько есть (остаток не уходит в минус) и возвращает
        нехватку: так обрабатывается уже прошедшая оплата, когда товар успели купить.
        """
        if order.stock_deducted:
            return {}
        needs = self._needs(order)
        variants = await self._lock_variants(list(needs))
        shortages = {}
        for variant_id, qty in needs.items():
            available = variants[variant_id].stock if variant_id in variants else 0
            if available < qty:
                shortages[variant_id] = qty - available
        if shortages and not allow_partial:
            raise OutOfStock(shortages)
        for variant_id, qty in needs.items():
            variant = variants.get(variant_id)
            if variant is not None:
                variant.stock = max(variant.stock - qty, 0)
        order.stock_deducted = True
        if shortages:
            logger.warning("Заказ %s: нехватка на складе %s", order.id, shortages)
        return shortages

    async def restore(self, order: Order) -> None:
        if not order.stock_deducted:
            return
        needs = self._needs(order)
        variants = await self._lock_variants(list(needs))
        for variant_id, qty in needs.items():
            variant = variants.get(variant_id)
            if variant is not None:
                variant.stock += qty
        order.stock_deducted = False

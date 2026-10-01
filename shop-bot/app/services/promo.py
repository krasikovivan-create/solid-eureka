"""Промокоды: проверка, расчёт скидки, учёт использований."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import PromoKind
from app.db.base import utcnow
from app.db.models import PromoCode, PromoUsage
from app.texts import t
from app.utils.formatting import money


class PromoError(Exception):
    def __init__(self, key: str, **kwargs: object) -> None:
        self.key = key
        self.kwargs = kwargs
        super().__init__(key)

    @property
    def message(self) -> str:
        return t(f"promo.{self.key}", **self.kwargs)


def normalize_code(code: str) -> str:
    return code.strip().upper()


def calc_discount(promo: PromoCode, items_total: int) -> int:
    """Скидка не может обнулить заказ: минимум 1 ₽ за товары остаётся к оплате."""
    if items_total <= 0:
        return 0
    if promo.kind == PromoKind.PERCENT:
        discount = items_total * promo.value // 100
    else:
        discount = promo.value
    return max(0, min(discount, items_total - 1))


class PromoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, code: str) -> PromoCode | None:
        stmt = select(PromoCode).where(PromoCode.code == normalize_code(code))
        return await self.session.scalar(stmt)

    async def user_usages(self, promo_id: int, user_id: int) -> int:
        stmt = select(func.count(PromoUsage.id)).where(
            PromoUsage.promo_id == promo_id, PromoUsage.user_id == user_id
        )
        return int(await self.session.scalar(stmt) or 0)

    async def validate(
        self, code: str, user_id: int, items_total: int, now: datetime | None = None
    ) -> PromoCode:
        now = now or utcnow()
        promo = await self.get(code)
        if promo is None:
            raise PromoError("not_found")
        if not promo.is_active:
            raise PromoError("inactive")
        if promo.valid_from and now < promo.valid_from:
            raise PromoError("not_started")
        if promo.valid_to and now > promo.valid_to:
            raise PromoError("expired")
        if promo.max_uses is not None and promo.used_count >= promo.max_uses:
            raise PromoError("exhausted")
        if promo.per_user_limit and await self.user_usages(promo.id, user_id) >= (
            promo.per_user_limit
        ):
            raise PromoError("user_limit")
        if items_total < promo.min_total:
            raise PromoError("min_total", min_total=money(promo.min_total))
        return promo

    async def register_usage(self, promo: PromoCode, user_id: int, order_id: int) -> None:
        promo.used_count += 1
        self.session.add(PromoUsage(promo_id=promo.id, user_id=user_id, order_id=order_id))

    async def release_usage(self, promo_id: int, order_id: int) -> None:
        result = await self.session.execute(
            delete(PromoUsage).where(
                PromoUsage.promo_id == promo_id, PromoUsage.order_id == order_id
            )
        )
        if result.rowcount:
            promo = await self.session.get(PromoCode, promo_id)
            if promo and promo.used_count > 0:
                promo.used_count -= 1

    async def create(
        self,
        code: str,
        kind: str,
        value: int,
        min_total: int = 0,
        valid_to: datetime | None = None,
        max_uses: int | None = None,
        per_user_limit: int = 1,
        valid_from: datetime | None = None,
    ) -> PromoCode:
        promo = PromoCode(
            code=normalize_code(code),
            kind=kind,
            value=value,
            min_total=min_total,
            valid_from=valid_from,
            valid_to=valid_to,
            max_uses=max_uses,
            per_user_limit=per_user_limit,
        )
        self.session.add(promo)
        await self.session.flush()
        return promo

    async def list_all(self) -> list[PromoCode]:
        return list(
            (await self.session.scalars(select(PromoCode).order_by(PromoCode.id.desc()))).all()
        )

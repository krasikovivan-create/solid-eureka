"""Статистика для админ-панели."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import OrderStatus, PaymentMethod, UserEvent
from app.db.base import utcnow
from app.db.models import Order, OrderItem, StylistLook, StylistRequest, User, UserEventLog

PERIODS = {"day": timedelta(days=1), "week": timedelta(days=7), "month": timedelta(days=30)}


@dataclass(slots=True)
class ShopStats:
    new_users: int = 0
    orders: int = 0
    success: int = 0
    revenue: int = 0
    carted_users: int = 0
    ordered_users: int = 0
    top: list[tuple[str, int, int]] = field(default_factory=list)  # title, qty, revenue
    sources: list[tuple[str, int, int, int]] = field(default_factory=list)  # src, users, orders, ₽
    referred: int = 0
    referred_buyers: int = 0

    @property
    def avg_check(self) -> int:
        return self.revenue // self.success if self.success else 0

    @property
    def conversion(self) -> float:
        return round(self.ordered_users * 100 / self.carted_users, 1) if self.carted_users else 0.0


@dataclass(slots=True)
class StylistStats:
    day_requests: int = 0
    day_cost: float = 0.0
    month_requests: int = 0
    month_cost: float = 0.0
    month_errors: int = 0
    in_tokens: int = 0
    out_tokens: int = 0
    cache_tokens: int = 0
    looks: int = 0
    looks_carted: int = 0
    looks_ordered: int = 0


def _successful_order():
    """Заказ «состоялся»: не отменён и не возвращён, оплачен или с оплатой при получении."""
    return and_(
        Order.status.not_in([OrderStatus.CANCELLED, OrderStatus.RETURNED]),
        or_(Order.is_paid.is_(True), Order.payment_method == PaymentMethod.COD),
    )


class StatsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _scalar(self, stmt) -> int:
        return int(await self.session.scalar(stmt) or 0)

    async def shop(self, period: str, now: datetime | None = None) -> ShopStats:
        since = (now or utcnow()) - PERIODS[period]
        s = ShopStats()
        s.new_users = await self._scalar(
            select(func.count(User.id)).where(User.created_at >= since)
        )
        s.orders = await self._scalar(select(func.count(Order.id)).where(Order.created_at >= since))
        ok = and_(Order.created_at >= since, _successful_order())
        s.success = await self._scalar(select(func.count(Order.id)).where(ok))
        s.revenue = await self._scalar(select(func.coalesce(func.sum(Order.total), 0)).where(ok))

        carted = (
            select(UserEventLog.user_id)
            .distinct()
            .where(UserEventLog.event == UserEvent.CART_ADD, UserEventLog.created_at >= since)
        )
        s.carted_users = await self._scalar(select(func.count()).select_from(carted.subquery()))
        ordered = (
            select(UserEventLog.user_id)
            .distinct()
            .where(
                UserEventLog.event == UserEvent.ORDER_CREATED,
                UserEventLog.created_at >= since,
                UserEventLog.user_id.in_(carted),
            )
        )
        s.ordered_users = await self._scalar(select(func.count()).select_from(ordered.subquery()))

        top_stmt = (
            select(
                OrderItem.title,
                func.sum(OrderItem.qty),
                func.sum(OrderItem.qty * OrderItem.price),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(ok)
            .group_by(OrderItem.title)
            .order_by(func.sum(OrderItem.qty).desc())
            .limit(5)
        )
        s.top = [(row[0], int(row[1]), int(row[2])) for row in await self.session.execute(top_stmt)]

        source = func.coalesce(User.utm_source, "organic")
        orders_sub = (
            select(
                Order.user_id.label("uid"),
                func.count(Order.id).label("cnt"),
                func.sum(Order.total).label("rev"),
            )
            .where(_successful_order())
            .group_by(Order.user_id)
            .subquery()
        )
        src_stmt = (
            select(
                source,
                func.count(User.id),
                func.coalesce(func.sum(orders_sub.c.cnt), 0),
                func.coalesce(func.sum(orders_sub.c.rev), 0),
            )
            .outerjoin(orders_sub, orders_sub.c.uid == User.id)
            .where(User.created_at >= since)
            .group_by(source)
            .order_by(func.count(User.id).desc())
            .limit(10)
        )
        s.sources = [
            (row[0], int(row[1]), int(row[2]), int(row[3]))
            for row in await self.session.execute(src_stmt)
        ]
        s.referred = await self._scalar(
            select(func.count(User.id)).where(
                User.created_at >= since, User.referrer_id.is_not(None)
            )
        )
        s.referred_buyers = await self._scalar(
            select(func.count(User.id)).where(
                User.created_at >= since, User.referral_rewarded.is_(True)
            )
        )
        return s

    async def stylist(self, now: datetime | None = None) -> StylistStats:
        now = now or utcnow()
        day, month = now - PERIODS["day"], now - PERIODS["month"]
        st = StylistStats()

        async def requests(since: datetime) -> tuple[int, float]:
            row = (
                await self.session.execute(
                    select(
                        func.count(StylistRequest.id),
                        func.coalesce(func.sum(StylistRequest.cost_usd), 0.0),
                    ).where(StylistRequest.created_at >= since)
                )
            ).one()
            return int(row[0]), float(row[1])

        st.day_requests, st.day_cost = await requests(day)
        st.month_requests, st.month_cost = await requests(month)
        st.month_errors = await self._scalar(
            select(func.count(StylistRequest.id)).where(
                StylistRequest.created_at >= month, StylistRequest.status == "error"
            )
        )
        tokens = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(StylistRequest.input_tokens), 0),
                    func.coalesce(func.sum(StylistRequest.output_tokens), 0),
                    func.coalesce(
                        func.sum(
                            StylistRequest.cache_read_tokens + StylistRequest.cache_creation_tokens
                        ),
                        0,
                    ),
                ).where(StylistRequest.created_at >= month)
            )
        ).one()
        st.in_tokens, st.out_tokens, st.cache_tokens = (int(v) for v in tokens)
        st.looks = await self._scalar(
            select(func.count(StylistLook.id)).where(StylistLook.created_at >= month)
        )
        st.looks_carted = await self._scalar(
            select(func.count(StylistLook.id)).where(
                StylistLook.created_at >= month, StylistLook.added_to_cart_at.is_not(None)
            )
        )
        st.looks_ordered = await self._scalar(
            select(func.count(StylistLook.id)).where(
                StylistLook.created_at >= month, StylistLook.order_id.is_not(None)
            )
        )
        return st

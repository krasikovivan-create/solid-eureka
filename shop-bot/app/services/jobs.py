"""Фоновые задачи: брошенные корзины, избранное, отслеживание, неоплаченные заказы, рассылки."""

from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import Bot
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.constants import ORDER_TRANSITIONS, OrderStatus
from app.db.base import utcnow
from app.db.models import CartItem, Order, ProductVariant, User
from app.keyboards.user import open_cart_kb, open_product_kb
from app.services.broadcast import BroadcastRunner
from app.services.delivery import DeliveryProvider
from app.services.favorites import FavoriteService
from app.services.notifications import Notifier
from app.services.payments import build_order_service
from app.texts import t
from app.utils.formatting import h, money

logger = logging.getLogger(__name__)


class Jobs:
    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        notifier: Notifier,
        providers: dict[str, DeliveryProvider],
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.settings = settings
        self.notifier = notifier
        self.providers = providers

    async def abandoned_carts(self) -> int:
        """Напоминание о корзине, к которой не возвращались abandoned_cart_hours часов."""
        threshold = utcnow() - timedelta(hours=self.settings.abandoned_cart_hours)
        sent = 0
        async with self.session_factory() as session:
            last_change = (
                select(CartItem.user_id, func.max(CartItem.updated_at).label("changed"))
                .group_by(CartItem.user_id)
                .subquery()
            )
            stmt = (
                select(User, last_change.c.changed)
                .join(last_change, last_change.c.user_id == User.id)
                .where(
                    User.is_blocked.is_(False),
                    last_change.c.changed < threshold,
                    (User.cart_reminded_at.is_(None))
                    | (User.cart_reminded_at < last_change.c.changed),
                )
                .limit(500)
            )
            for user, _changed in (await session.execute(stmt)).all():
                items = (
                    await session.scalars(
                        select(CartItem)
                        .where(CartItem.user_id == user.id)
                        .options(
                            selectinload(CartItem.variant).selectinload(ProductVariant.product)
                        )
                        .limit(5)
                    )
                ).all()
                lines = "\n".join(
                    f"• {h(i.variant.product.title)} ({h(i.variant.size)}) — "
                    f"{money(i.variant.product.price)}"
                    for i in items
                )
                if await self.notifier.send(
                    user.id, t("cart.reminder", items=lines), reply_markup=open_cart_kb()
                ):
                    sent += 1
                user.cart_reminded_at = utcnow()
            await session.commit()
        return sent

    async def favorite_alerts(self, product_ids: list[int] | None = None) -> int:
        async with self.session_factory() as session:
            alerts = await FavoriteService(session).collect_alerts(product_ids)
            await session.commit()
        for alert in alerts:
            if alert.kind == "price_drop":
                text = t(
                    "fav.price_drop",
                    title=h(alert.title),
                    old=money(alert.old_price),
                    new=money(alert.new_price),
                )
            else:
                text = t("fav.back_in_stock", title=h(alert.title), price=money(alert.new_price))
            await self.notifier.send(
                alert.user_id, text, reply_markup=open_product_kb(alert.product_id)
            )
        return len(alerts)

    async def sync_tracking(self) -> int:
        """Опрашивает службы доставки и переводит заказы в «в пути» / «доставлен»."""
        changed = 0
        async with self.session_factory() as session:
            orders = (
                await session.scalars(
                    select(Order)
                    .where(
                        Order.status.in_([OrderStatus.SHIPPED, OrderStatus.IN_TRANSIT]),
                        Order.track_number.is_not(None),
                    )
                    .options(selectinload(Order.history))
                )
            ).all()
            service = build_order_service(session, self.notifier, self.providers, self.settings)
            for order in orders:
                provider = self.providers.get(order.delivery_method)
                if provider is None or not provider.supports_tracking:
                    continue
                try:
                    info = await provider.track(order)
                except Exception:
                    logger.exception("Ошибка трекинга заказа %s", order.id)
                    continue
                target = info.order_status if info else None
                if not target or target == order.status:
                    continue
                if OrderStatus(target) in ORDER_TRANSITIONS[OrderStatus(order.status)]:
                    await service.change_status(order.id, target, comment="tracking")
                    changed += 1
        return changed

    async def cancel_unpaid(self) -> int:
        async with self.session_factory() as session:
            service = build_order_service(session, self.notifier, self.providers, self.settings)
            return await service.cancel_stale_unpaid(self.settings.unpaid_order_ttl_hours)

    async def broadcasts(self) -> int:
        runner = BroadcastRunner(
            self.bot, self.session_factory, self.settings.broadcast_rate_per_sec
        )
        return await runner.run_due()

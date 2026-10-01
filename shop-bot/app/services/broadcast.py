"""Рассылки с сегментацией и соблюдением лимитов Telegram."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.constants import SUCCESSFUL_STATUSES, Segment
from app.db.base import utcnow
from app.db.models import (
    Broadcast,
    CartItem,
    Order,
    OrderItem,
    Product,
    ProductView,
    User,
)
from app.keyboards.user import open_product_kb
from app.texts import t

logger = logging.getLogger(__name__)


async def segment_user_ids(
    session: AsyncSession, segment: str, category_id: int | None = None
) -> list[int]:
    active = User.is_blocked.is_(False)
    if segment == Segment.ALL:
        stmt = select(User.id).where(active)
    elif segment == Segment.BUYERS:
        stmt = (
            select(Order.user_id)
            .distinct()
            .join(User, User.id == Order.user_id)
            .where(active, Order.status.in_(SUCCESSFUL_STATUSES))
        )
    elif segment == Segment.ABANDONED:
        stmt = (
            select(CartItem.user_id)
            .distinct()
            .join(User, User.id == CartItem.user_id)
            .where(active)
        )
    elif segment == Segment.CATEGORY and category_id:
        viewed = (
            select(ProductView.user_id)
            .join(Product, Product.id == ProductView.product_id)
            .where(Product.category_id == category_id)
        )
        bought = (
            select(Order.user_id)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .join(Product, Product.id == OrderItem.product_id)
            .where(Product.category_id == category_id)
        )
        stmt = select(User.id).where(active, User.id.in_(viewed.union(bought)))
    else:
        return []
    return sorted(set((await session.scalars(stmt)).all()))


def broadcast_markup(broadcast: Broadcast) -> InlineKeyboardMarkup | None:
    if broadcast.product_id:
        return open_product_kb(broadcast.product_id, t("adm.bc_view_product"))
    return None


async def send_broadcast_message(bot: Bot, chat_id: int, broadcast: Broadcast) -> None:
    markup = broadcast_markup(broadcast)
    if broadcast.photo:
        await bot.send_photo(chat_id, broadcast.photo, caption=broadcast.text, reply_markup=markup)
    else:
        await bot.send_message(chat_id, broadcast.text, reply_markup=markup)


class BroadcastService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        created_by: int,
        segment: str,
        text: str,
        photo: str | None = None,
        product_id: int | None = None,
        category_id: int | None = None,
        scheduled_at: datetime | None = None,
    ) -> Broadcast:
        broadcast = Broadcast(
            created_by=created_by,
            segment=segment,
            category_id=category_id,
            text=text,
            photo=photo,
            product_id=product_id,
            status="scheduled",
            scheduled_at=scheduled_at or utcnow(),
        )
        self.session.add(broadcast)
        await self.session.flush()
        return broadcast


class BroadcastRunner:
    """Отправляет рассылку: не больше rate сообщений в секунду (лимит Telegram — ~30/с),
    ждёт при RetryAfter, помечает заблокировавших бота пользователей."""

    def __init__(
        self, bot: Bot, session_factory: async_sessionmaker[AsyncSession], rate: int = 25
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.delay = 1 / max(rate, 1)

    async def _deliver(self, chat_id: int, broadcast: Broadcast) -> str:
        for _ in range(3):
            try:
                await send_broadcast_message(self.bot, chat_id, broadcast)
                return "sent"
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
            except TelegramForbiddenError:
                return "blocked"
            except TelegramBadRequest:
                return "failed"
            except TelegramAPIError:
                logger.warning("Ошибка рассылки пользователю %s", chat_id, exc_info=True)
                await asyncio.sleep(1)
        return "failed"

    async def run(self, broadcast_id: int) -> Broadcast | None:
        async with self.session_factory() as session:
            claimed = await session.execute(
                update(Broadcast)
                .where(Broadcast.id == broadcast_id, Broadcast.status == "scheduled")
                .values(status="running")
            )
            await session.commit()
            if not claimed.rowcount:
                return None  # уже запущена другим процессом
            broadcast = await session.get(Broadcast, broadcast_id)
            recipients = await segment_user_ids(session, broadcast.segment, broadcast.category_id)
            broadcast.total = len(recipients)
            await session.commit()

            sent = failed = 0
            blocked: list[int] = []
            for index, chat_id in enumerate(recipients, start=1):
                result = await self._deliver(chat_id, broadcast)
                if result == "sent":
                    sent += 1
                else:
                    failed += 1
                    if result == "blocked":
                        blocked.append(chat_id)
                if index % 100 == 0:
                    broadcast.sent, broadcast.failed = sent, failed
                    await session.commit()
                await asyncio.sleep(self.delay)

            if blocked:
                await session.execute(
                    update(User).where(User.id.in_(blocked)).values(is_blocked=True)
                )
            broadcast.sent, broadcast.failed = sent, failed
            broadcast.status = "done"
            broadcast.finished_at = utcnow()
            await session.commit()
        try:
            await self.bot.send_message(
                broadcast.created_by,
                t("adm.bc_finished", id=broadcast.id, sent=sent, failed=failed),
            )
        except TelegramAPIError:
            logger.warning("Не удалось сообщить о завершении рассылки %s", broadcast.id)
        return broadcast

    async def run_due(self) -> int:
        async with self.session_factory() as session:
            ids = list(
                (
                    await session.scalars(
                        select(Broadcast.id).where(
                            Broadcast.status == "scheduled", Broadcast.scheduled_at <= utcnow()
                        )
                    )
                ).all()
            )
        for broadcast_id in ids:
            await self.run(broadcast_id)
        return len(ids)

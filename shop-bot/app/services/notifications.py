"""Уведомления покупателям и админам. Ошибки доставки не роняют бизнес-логику."""

from __future__ import annotations

import logging
from typing import Protocol

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup

from app.db.models import Order
from app.texts import t
from app.utils.formatting import (
    delivery_label,
    h,
    money,
    payment_label,
    status_label,
)

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    async def order_status_changed(self, order: Order) -> None: ...
    async def new_order(self, order: Order) -> None: ...
    async def order_paid(self, order: Order) -> None: ...
    async def refund_needed(self, order: Order) -> None: ...
    async def referral_rewarded(self, user_id: int, bonus: int) -> None: ...
    async def send(
        self, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None
    ) -> bool: ...


def order_items_text(order: Order) -> str:
    return "\n".join(
        f"• {h(i.title)} ({h(i.size)} · {h(i.color)}) × {i.qty} = {money(i.subtotal)}"
        for i in order.items
    )


def order_address(order: Order, pickup_address: str = "") -> str:
    if order.address:
        return h(f"{order.city}, {order.address}" if order.city else order.address)
    return h(pickup_address or order.city)


class BotNotifier:
    def __init__(self, bot: Bot, admin_ids: list[int], pickup_address: str = "") -> None:
        self.bot = bot
        self.admin_ids = admin_ids
        self.pickup_address = pickup_address

    async def send(
        self, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None
    ) -> bool:
        try:
            await self.bot.send_message(chat_id, text, reply_markup=reply_markup)
            return True
        except TelegramForbiddenError:
            logger.info("Пользователь %s заблокировал бота", chat_id)
        except TelegramAPIError:
            logger.exception("Не удалось отправить сообщение в %s", chat_id)
        return False

    async def _to_admins(self, text: str) -> None:
        for admin_id in self.admin_ids:
            await self.send(admin_id, text)

    async def order_status_changed(self, order: Order) -> None:
        extra = ""
        if order.track_number:
            extra = t("orders.status_track_extra", track=h(order.track_number))
        await self.send(
            order.user_id,
            t("orders.status_changed", id=order.id, status=status_label(order.status), extra=extra),
        )

    async def new_order(self, order: Order) -> None:
        await self._to_admins(
            t(
                "admin.new_order",
                id=order.id,
                customer=h(order.customer_name),
                phone=h(order.phone),
                user_id=order.user_id,
                method=delivery_label(order.delivery_method),
                address=order_address(order, self.pickup_address),
                payment=payment_label(order.payment_method),
                items=order_items_text(order),
                total=money(order.total),
            )
        )

    async def order_paid(self, order: Order) -> None:
        await self._to_admins(t("admin.order_paid", id=order.id, total=money(order.total)))

    async def refund_needed(self, order: Order) -> None:
        await self._to_admins(t("admin.refund_needed", id=order.id, total=money(order.total)))

    async def referral_rewarded(self, user_id: int, bonus: int) -> None:
        await self.send(user_id, t("ref.rewarded", bonus=money(bonus)))

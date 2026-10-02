"""Оплата через Telegram Payments (провайдер ЮKassa) и тестовый режим без договора."""

from __future__ import annotations

import json

from aiogram import Bot
from aiogram.types import LabeledPrice

from app.config import Settings
from app.db.models import Order
from app.services.notifications import Notifier
from app.services.orders import OrderService
from app.texts import t

PAYLOAD_PREFIX = "order:"


def make_payload(order_id: int) -> str:
    return f"{PAYLOAD_PREFIX}{order_id}"


def parse_payload(payload: str) -> int | None:
    if not payload.startswith(PAYLOAD_PREFIX):
        return None
    tail = payload.removeprefix(PAYLOAD_PREFIX)
    return int(tail) if tail.isdigit() else None


def invoice_prices(order: Order) -> list[LabeledPrice]:
    goods = order.items_total - order.discount - order.bonus_used
    prices = [LabeledPrice(label=t("checkout.invoice_items"), amount=goods * 100)]
    if order.delivery_price:
        prices.append(
            LabeledPrice(label=t("checkout.invoice_delivery"), amount=order.delivery_price * 100)
        )
    return prices


def _amount(kopecks: int) -> dict[str, str]:
    return {"value": f"{kopecks // 100}.{kopecks % 100:02d}", "currency": "RUB"}


def build_receipt(order: Order, vat_code: int) -> dict:
    """Чек 54-ФЗ для ЮKassa. Скидка и бонусы распределяются по позициям пропорционально,
    суммы сходятся с итогом заказа до копейки."""
    reduction = (order.discount + order.bonus_used) * 100
    lines = [(item.title, item.size, item.qty, item.price * item.qty * 100) for item in order.items]
    gross = sum(total for *_, total in lines) or 1
    allocated = 0
    receipt_items = []
    for index, (title, size, qty, total) in enumerate(lines):
        if index == len(lines) - 1:
            share = reduction - allocated
        else:
            share = reduction * total // gross
            allocated += share
        net = total - share
        unit, remainder = divmod(net, qty)
        description = f"{title} ({size})"[:128]
        chunks = [(qty, unit)] if remainder == 0 else [(qty - 1, unit), (1, unit + remainder)]
        for count, price in chunks:
            if count <= 0:
                continue
            receipt_items.append(
                {
                    "description": description,
                    "quantity": f"{count}.00",
                    "amount": _amount(price),
                    "vat_code": vat_code,
                    "payment_mode": "full_payment",
                    "payment_subject": "commodity",
                }
            )
    if order.delivery_price:
        receipt_items.append(
            {
                "description": "Доставка",
                "quantity": "1.00",
                "amount": _amount(order.delivery_price * 100),
                "vat_code": vat_code,
                "payment_mode": "full_payment",
                "payment_subject": "service",
            }
        )
    return {"receipt": {"items": receipt_items, "customer": {"phone": order.phone.lstrip("+")}}}


class PaymentService:
    def __init__(self, bot: Bot, settings: Settings) -> None:
        self.bot = bot
        self.settings = settings

    @property
    def test_mode(self) -> bool:
        return self.settings.payments_mode == "fake"

    @property
    def card_enabled(self) -> bool:
        return self.test_mode or bool(self.settings.payment_provider_token.get_secret_value())

    async def send_invoice(self, order: Order, shop_name: str) -> None:
        provider_data = None
        if self.settings.send_receipt:
            provider_data = json.dumps(
                build_receipt(order, self.settings.vat_code), ensure_ascii=False
            )
        await self.bot.send_invoice(
            chat_id=order.user_id,
            title=t("checkout.invoice_title", order_id=order.id),
            description=t("checkout.invoice_description", order_id=order.id, shop=shop_name),
            payload=make_payload(order.id),
            provider_token=self.settings.payment_provider_token.get_secret_value(),
            currency=self.settings.currency,
            prices=invoice_prices(order),
            need_name=False,
            need_phone_number=False,
            need_shipping_address=False,
            is_flexible=False,
            provider_data=provider_data,
        )

    async def pay_test(self, orders: OrderService, order_id: int) -> Order:
        """Тестовая «оплата»: только в режиме PAYMENTS_MODE=fake."""
        if not self.test_mode:
            raise PermissionError("Тестовая оплата отключена")
        return await orders.mark_paid(
            order_id, telegram_charge_id="test", provider_charge_id="test"
        )


def build_order_service(session, notifier: Notifier, providers, settings: Settings) -> OrderService:
    return OrderService(
        session,
        notifier,
        providers,
        referral_bonus=settings.referral_bonus,
        bonus_share_percent=settings.max_bonus_share_percent,
    )

"""«Мои заказы» и приём оплаты."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.constants import USER_CANCELLABLE, OrderStatus, PaymentMethod
from app.db.models import Order, User
from app.keyboards.callbacks import MenuCB, OrderCB
from app.keyboards.user import order_cancel_confirm_kb, order_kb, orders_kb
from app.services.delivery import DeliveryProvider
from app.services.notifications import Notifier, order_address, order_items_text
from app.services.orders import InvalidTransition, OrderError
from app.services.payments import PaymentService, build_order_service, parse_payload
from app.services.shop_config import ShopConfig
from app.texts import t
from app.utils.formatting import (
    delivery_label,
    h,
    local_dt,
    money,
    payment_label,
    status_label,
)
from app.utils.telegram import render

logger = logging.getLogger(__name__)
router = Router(name="orders")


def order_text(order: Order, settings: Settings) -> str:
    history = "\n".join(
        f"{local_dt(entry.created_at, settings.timezone)} — {status_label(entry.to_status)}"
        for entry in order.history
    )
    return t(
        "orders.card",
        id=order.id,
        date=local_dt(order.created_at, settings.timezone),
        status=status_label(order.status),
        items=order_items_text(order),
        method=delivery_label(order.delivery_method),
        address=order_address(order),
        payment=payment_label(order.payment_method),
        paid=t("orders.paid_mark") if order.is_paid else t("orders.unpaid_mark"),
        track=t("orders.track", track=h(order.track_number)) if order.track_number else "",
        items_total=money(order.items_total),
        discount_line=t("checkout.discount_line", discount=money(order.discount))
        if order.discount
        else "",
        bonus_line=t("checkout.bonus_line", bonus=money(order.bonus_used))
        if order.bonus_used
        else "",
        delivery=money(order.delivery_price) if order.delivery_price else t("checkout.free"),
        total=money(order.total),
        history=history,
    )


def can_pay(order: Order) -> bool:
    return (
        order.status == OrderStatus.NEW
        and order.payment_method == PaymentMethod.CARD
        and not order.is_paid
    )


@router.callback_query(MenuCB.filter(F.a == "orders"))
@router.callback_query(OrderCB.filter(F.a == "list"))
async def cb_orders(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    notifier: Notifier,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    orders = await build_order_service(session, notifier, providers, settings).list_for_user(
        user.id
    )
    text = t("orders.title") if orders else t("orders.empty")
    await render(callback, text, orders_kb(orders))
    await callback.answer()


async def show_order(
    event: CallbackQuery | Message,
    order: Order,
    settings: Settings,
    providers: dict[str, DeliveryProvider],
) -> None:
    provider = providers.get(order.delivery_method)
    await render(
        event,
        order_text(order, settings),
        order_kb(
            order,
            can_cancel=order.status in USER_CANCELLABLE,
            can_pay=can_pay(order),
            can_track=bool(order.track_number and provider and provider.supports_tracking),
        ),
    )


@router.callback_query(OrderCB.filter(F.a == "view"))
async def cb_order(
    callback: CallbackQuery,
    callback_data: OrderCB,
    session: AsyncSession,
    user: User,
    notifier: Notifier,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    service = build_order_service(session, notifier, providers, settings)
    order = await service.get(callback_data.oid, user.id)
    if order is None:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    await show_order(callback, order, settings, providers)
    await callback.answer()


@router.callback_query(OrderCB.filter(F.a == "repeat"))
async def cb_repeat(
    callback: CallbackQuery,
    callback_data: OrderCB,
    session: AsyncSession,
    user: User,
    notifier: Notifier,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    service = build_order_service(session, notifier, providers, settings)
    try:
        added, missing = await service.repeat(user.id, callback_data.oid)
    except OrderError:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    missing_text = t("orders.repeat_missing", items=", ".join(missing)) if missing else ""
    await callback.answer(
        t("orders.repeat_done", added=added, missing=missing_text), show_alert=True
    )


@router.callback_query(OrderCB.filter(F.a == "cancel"))
async def cb_cancel(callback: CallbackQuery, callback_data: OrderCB) -> None:
    await render(
        callback,
        t("orders.cancel_confirm", id=callback_data.oid),
        order_cancel_confirm_kb(callback_data.oid),
    )
    await callback.answer()


@router.callback_query(OrderCB.filter(F.a == "cancel_yes"))
async def cb_cancel_yes(
    callback: CallbackQuery,
    callback_data: OrderCB,
    session: AsyncSession,
    user: User,
    notifier: Notifier,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    service = build_order_service(session, notifier, providers, settings)
    try:
        order = await service.cancel_by_user(user.id, callback_data.oid)
    except InvalidTransition:
        await callback.answer(t("orders.cannot_cancel"), show_alert=True)
        return
    note = "\n" + t("orders.cancel_refund_note") if order.is_paid else ""
    await callback.answer(t("orders.cancelled_by_user", id=order.id) + note, show_alert=True)
    await show_order(callback, order, settings, providers)


@router.callback_query(OrderCB.filter(F.a == "track"))
async def cb_track(
    callback: CallbackQuery,
    callback_data: OrderCB,
    session: AsyncSession,
    user: User,
    notifier: Notifier,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    service = build_order_service(session, notifier, providers, settings)
    order = await service.get(callback_data.oid, user.id)
    provider = providers.get(order.delivery_method) if order else None
    info = await provider.track(order) if provider and order and order.track_number else None
    if info is None:
        await callback.answer(t("orders.tracking_unavailable"), show_alert=True)
        return
    events = "\n".join(
        f"{local_dt(e.at, settings.timezone)} — {h(e.description)}" for e in info.events
    )
    await callback.message.answer(t("orders.tracking", track=h(info.track_number), events=events))
    await callback.answer()


# ---------- Оплата ----------
@router.callback_query(OrderCB.filter(F.a == "pay"))
async def cb_pay_order(
    callback: CallbackQuery,
    callback_data: OrderCB,
    bot: Bot,
    session: AsyncSession,
    user: User,
    notifier: Notifier,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
    shop: ShopConfig,
) -> None:
    service = build_order_service(session, notifier, providers, settings)
    payments = PaymentService(bot, settings)
    order = await service.get(callback_data.oid, user.id)
    if order is None or not can_pay(order):
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    if payments.test_mode:
        if not await service.validate_for_payment(order.id, user.id, order.total):
            await callback.answer(t("checkout.pre_checkout_error"), show_alert=True)
            return
        await payments.pay_test(service, order.id)
        await render(callback, t("checkout.paid", order_id=order.id), orders_kb([order]))
    elif payments.card_enabled:
        await payments.send_invoice(order, shop.shop_name)
    else:
        await callback.answer(t("checkout.payment_not_available"), show_alert=True)
        return
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout(
    query: PreCheckoutQuery,
    session: AsyncSession,
    notifier: Notifier,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    order_id = parse_payload(query.invoice_payload)
    service = build_order_service(session, notifier, providers, settings)
    ok = (
        order_id is not None
        and query.currency == settings.currency
        and query.total_amount % 100 == 0
        and await service.validate_for_payment(
            order_id, query.from_user.id, query.total_amount // 100
        )
    )
    if ok:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message=t("checkout.pre_checkout_error"))


@router.message(F.successful_payment)
async def successful_payment(
    message: Message,
    session: AsyncSession,
    notifier: Notifier,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    payment = message.successful_payment
    order_id = parse_payload(payment.invoice_payload)
    if order_id is None:
        logger.error("Оплата с неизвестным payload: %s", payment.invoice_payload)
        return
    service = build_order_service(session, notifier, providers, settings)
    await service.mark_paid(
        order_id,
        telegram_charge_id=payment.telegram_payment_charge_id,
        provider_charge_id=payment.provider_payment_charge_id,
    )
    await message.answer(t("checkout.paid", order_id=order_id))

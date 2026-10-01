"""Админка: заказы — фильтр по статусу, смена статуса, трек-номер, отправление."""

from __future__ import annotations

import math

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.constants import OrderStatus
from app.db.models import Order
from app.handlers.user.orders import order_text
from app.keyboards.admin import admin_order_kb, admin_orders_kb, cancel_admin_kb, order_filter_kb
from app.keyboards.callbacks import AdminCB
from app.services.delivery import DeliveryProvider
from app.services.notifications import Notifier
from app.services.orders import InvalidTransition, OrderError
from app.services.payments import build_order_service
from app.states import AdminOrderStates
from app.texts import t
from app.utils.formatting import h, status_label
from app.utils.telegram import render

router = Router(name="admin_orders")
PAGE = 8


async def _show_order(
    event,
    order: Order,
    settings: Settings,
    providers: dict[str, DeliveryProvider],
    back_status: str = "",
) -> None:
    text = order_text(order, settings) + t(
        "adm.order_card_extra",
        customer=h(order.customer_name),
        phone=h(order.phone),
        user_id=order.user_id,
    )
    if order.comment:
        text += f"\n⚠️ {h(order.comment)}"
    provider = providers.get(order.delivery_method)
    can_ship = bool(provider and provider.supports_tracking)
    await render(event, text, admin_order_kb(order, back_status, can_ship))


@router.callback_query(AdminCB.filter((F.s == "order") & (F.a == "")))
async def cb_orders(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    await render(callback, t("adm.orders_title"), order_filter_kb())
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "order") & (F.a == "list")))
async def cb_orders_list(
    callback: CallbackQuery,
    callback_data: AdminCB,
    session: AsyncSession,
    notifier: Notifier,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    status = callback_data.v if callback_data.v in set(OrderStatus) else ""
    service = build_order_service(session, notifier, providers, settings)
    orders, total = await service.list_admin(status or None, callback_data.page * PAGE, PAGE)
    pages = max(1, math.ceil(total / PAGE))
    label = status_label(status) if status else t("adm.orders_all")
    await render(
        callback,
        t("adm.orders_list", filter=label, count=total),
        admin_orders_kb(orders, status, callback_data.page, pages),
    )
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "order") & (F.a == "view")))
async def cb_order(
    callback: CallbackQuery,
    callback_data: AdminCB,
    state: FSMContext,
    session: AsyncSession,
    notifier: Notifier,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    await state.set_state(None)
    order = await build_order_service(session, notifier, providers, settings).get(callback_data.id)
    if order is None:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    await _show_order(callback, order, settings, providers, callback_data.v)
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "order") & (F.a == "set")))
async def cb_set_status(
    callback: CallbackQuery,
    callback_data: AdminCB,
    session: AsyncSession,
    notifier: Notifier,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    service = build_order_service(session, notifier, providers, settings)
    try:
        order = await service.change_status(
            callback_data.id, callback_data.v, changed_by=callback.from_user.id
        )
    except (InvalidTransition, ValueError):
        await callback.answer(t("adm.bad_transition"), show_alert=True)
        return
    except OrderError:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    await callback.answer(t("adm.status_changed", status=status_label(order.status)))
    await _show_order(callback, order, settings, providers)


@router.callback_query(AdminCB.filter((F.s == "order") & (F.a == "track")))
async def cb_track(callback: CallbackQuery, callback_data: AdminCB, state: FSMContext) -> None:
    await state.update_data(order_id=callback_data.id)
    await state.set_state(AdminOrderStates.track)
    await render(
        callback,
        t("adm.enter_track"),
        cancel_admin_kb(AdminCB(s="order", a="view", id=callback_data.id)),
    )
    await callback.answer()


@router.message(AdminOrderStates.track, F.text)
async def msg_track(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    notifier: Notifier,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    track = message.text.strip()
    if not 4 <= len(track) <= 64 or " " in track:
        await message.answer(t("adm.bad_value"))
        return
    order_id = (await state.get_data()).get("order_id", 0)
    service = build_order_service(session, notifier, providers, settings)
    try:
        order = await service.set_track(order_id, track)
    except OrderError:
        await message.answer(t("common.not_found"))
        return
    await state.set_state(None)
    await message.answer(t("adm.track_saved"))
    await _show_order(message, order, settings, providers)


@router.callback_query(AdminCB.filter((F.s == "order") & (F.a == "ship")))
async def cb_ship(
    callback: CallbackQuery,
    callback_data: AdminCB,
    session: AsyncSession,
    notifier: Notifier,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    service = build_order_service(session, notifier, providers, settings)
    try:
        order = await service.create_shipment(callback_data.id)
    except OrderError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer(t("adm.shipment_created", track=order.track_number), show_alert=True)
    await _show_order(callback, order, settings, providers)

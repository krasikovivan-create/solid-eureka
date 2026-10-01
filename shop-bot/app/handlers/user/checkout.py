"""Оформление заказа (FSM): согласие 152-ФЗ → имя → телефон → город → способ доставки
→ адрес → расчёт доставки → подтверждение → оплата."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.constants import PaymentMethod, UserEvent
from app.db.base import utcnow
from app.db.models import User
from app.handlers.user.cart import show_cart
from app.handlers.user.start import menu_markup
from app.keyboards.callbacks import CartCB, CheckoutCB
from app.keyboards.user import (
    city_kb,
    confirm_kb,
    consent_kb,
    methods_kb,
    name_kb,
    payment_kb,
    phone_kb,
    test_pay_kb,
)
from app.repositories.users import UserRepository
from app.services.admins import AdminRegistry
from app.services.cart import CartService
from app.services.delivery import DeliveryCalculator, DeliveryProvider, NoTariff
from app.services.notifications import Notifier
from app.services.orders import CartChanged, CheckoutData, calc_totals, max_bonus
from app.services.payments import PaymentService, build_order_service
from app.services.validation import (
    normalize_phone,
    validate_address,
    validate_city,
    validate_name,
)
from app.states import CheckoutStates
from app.texts import t
from app.utils.formatting import days_range, delivery_label, h, money
from app.utils.telegram import render

logger = logging.getLogger(__name__)
router = Router(name="checkout")

CHECKOUT_KEYS = ("co_name", "co_phone", "co_city", "co_method", "co_address", "co_bonus")


async def _finish(state: FSMContext) -> None:
    await state.set_state(None)
    await state.update_data(**dict.fromkeys(CHECKOUT_KEYS))


async def _ask_name(message: Message, state: FSMContext, user: User) -> None:
    await state.set_state(CheckoutStates.name)
    await message.answer(t("checkout.ask_name"), reply_markup=name_kb(user.full_name or "—"))


# ---------- Старт ----------
@router.callback_query(CartCB.filter(F.a == "checkout"))
async def cb_checkout(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    summary = await CartService(session).summary(user)
    if summary.is_empty or summary.has_problems:
        await show_cart(callback, session, user)
        await callback.answer(t("checkout.cart_changed"), show_alert=True)
        return
    await UserRepository(session).log_event(user.id, UserEvent.CHECKOUT_START)
    if user.pd_consent_at is None:
        await state.set_state(CheckoutStates.consent)
        await render(callback, t("checkout.consent", url=settings.privacy_policy_url), consent_kb())
    else:
        await _ask_name(callback.message, state, user)
    await callback.answer()


@router.callback_query(CheckoutStates.consent, CheckoutCB.filter(F.a == "agree"))
async def cb_consent_yes(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    user.pd_consent_at = utcnow()
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
    await _ask_name(callback.message, state, user)
    await callback.answer()


@router.callback_query(CheckoutCB.filter(F.a.in_({"decline", "cancel"})))
async def cb_checkout_cancel(
    callback: CallbackQuery,
    callback_data: CheckoutCB,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    settings: Settings,
    admins: AdminRegistry,
) -> None:
    await _finish(state)
    key = "checkout.declined" if callback_data.a == "decline" else "common.cancelled"
    await render(callback, t(key), await menu_markup(session, user, settings, admins))
    await callback.answer()


@router.message(CheckoutStates.name, F.text == t("common.cancel"))
@router.message(CheckoutStates.phone, F.text == t("common.cancel"))
@router.message(CheckoutStates.city, F.text == t("common.cancel"))
@router.message(CheckoutStates.address, F.text == t("common.cancel"))
async def msg_cancel(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    settings: Settings,
    admins: AdminRegistry,
) -> None:
    await _finish(state)
    await message.answer(t("common.cancelled"), reply_markup=ReplyKeyboardRemove())
    await message.answer(
        t("menu.title"), reply_markup=await menu_markup(session, user, settings, admins)
    )


# ---------- Имя и телефон ----------
@router.message(CheckoutStates.name, F.text)
async def msg_name(message: Message, state: FSMContext) -> None:
    name = validate_name(message.text)
    if name is None:
        await message.answer(t("checkout.bad_name"))
        return
    await state.update_data(co_name=name)
    await state.set_state(CheckoutStates.phone)
    await message.answer(t("checkout.ask_phone"), reply_markup=phone_kb())


@router.message(CheckoutStates.phone, F.contact)
async def msg_contact(message: Message, state: FSMContext, user: User) -> None:
    if message.contact.user_id != message.from_user.id:
        await message.answer(t("checkout.foreign_contact"))
        return
    await _save_phone(message, state, user, message.contact.phone_number)


@router.message(CheckoutStates.phone, F.text)
async def msg_phone(message: Message, state: FSMContext, user: User) -> None:
    await _save_phone(message, state, user, message.text)


async def _save_phone(message: Message, state: FSMContext, user: User, raw: str) -> None:
    phone = normalize_phone(raw)
    if phone is None:
        await message.answer(t("checkout.bad_phone"))
        return
    user.phone = phone
    await state.update_data(co_phone=phone)
    await state.set_state(CheckoutStates.city)
    data = await state.get_data()
    await message.answer(t("checkout.ask_city"), reply_markup=city_kb(data.get("last_city")))


# ---------- Город и способ доставки ----------
@router.message(CheckoutStates.city, F.text)
async def msg_city(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    providers: dict[str, DeliveryProvider],
) -> None:
    city = validate_city(message.text)
    if city is None:
        await message.answer(t("checkout.bad_city"))
        return
    await state.update_data(co_city=city, last_city=city)
    methods = await DeliveryCalculator(session, providers).available_methods(city)
    await message.answer(f"🏙 {h(city)}", reply_markup=ReplyKeyboardRemove())
    await state.set_state(CheckoutStates.method)
    await message.answer(t("checkout.ask_method"), reply_markup=methods_kb(methods))


@router.callback_query(CheckoutStates.method, CheckoutCB.filter(F.a == "method"))
async def cb_method(
    callback: CallbackQuery,
    callback_data: CheckoutCB,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    provider = providers.get(callback_data.v)
    if provider is None:
        await callback.answer()
        return
    await state.update_data(co_method=callback_data.v)
    if provider.needs_address:
        await state.set_state(CheckoutStates.address)
        await render(callback, t("checkout.ask_address"), None)
    else:
        await state.update_data(co_address="")
        await render(callback, t("checkout.pickup_info", address=h(settings.pickup_address)), None)
        await _show_summary(callback.message, state, session, user, providers, settings)
    await callback.answer()


@router.message(CheckoutStates.address, F.text)
async def msg_address(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    address = validate_address(message.text)
    if address is None:
        await message.answer(t("checkout.bad_address"))
        return
    await state.update_data(co_address=address)
    await _show_summary(message, state, session, user, providers, settings)


# ---------- Сводка и подтверждение ----------
def _checkout_data(data: dict) -> CheckoutData:
    return CheckoutData(
        name=data["co_name"],
        phone=data["co_phone"],
        city=data["co_city"],
        address=data.get("co_address") or "",
        method=data["co_method"],
        use_bonus=bool(data.get("co_bonus")),
    )


async def _show_summary(
    event: Message | CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    data = await state.get_data()
    checkout = _checkout_data(data)
    summary = await CartService(session).summary(user)
    target = event.message if isinstance(event, CallbackQuery) else event
    if summary.is_empty or summary.has_problems or summary.promo_error is not None:
        await _finish(state)
        await target.answer(t("checkout.cart_changed"))
        await show_cart(target, session, user)
        return
    calculator = DeliveryCalculator(session, providers)
    try:
        quote = await calculator.quote(
            checkout.city, checkout.method, summary.items_total - summary.discount
        )
    except NoTariff:
        await state.set_state(CheckoutStates.method)
        methods = await calculator.available_methods(checkout.city)
        await target.answer(
            t("checkout.no_tariff", city=h(checkout.city)), reply_markup=methods_kb(methods)
        )
        return
    totals = calc_totals(summary, quote, user, checkout.use_bonus, settings.max_bonus_share_percent)
    bonus_available = max_bonus(
        user.bonus_balance, summary.items_total, summary.discount, settings.max_bonus_share_percent
    )
    items = "\n".join(
        f"• {h(line.title)} ({h(line.size)} · {h(line.color)}) × {line.qty}"
        f" = {money(line.subtotal)}"
        for line in summary.lines
    )
    address = (
        h(f"{checkout.city}, {checkout.address}")
        if checkout.address
        else h(settings.pickup_address)
    )
    text = t(
        "checkout.summary",
        items=items,
        name=h(checkout.name),
        phone=h(checkout.phone),
        method=delivery_label(checkout.method),
        address=address,
        days=days_range(quote.days_min, quote.days_max),
        items_total=money(totals.items_total),
        discount_line=t("checkout.discount_line", discount=money(totals.discount))
        if totals.discount
        else "",
        bonus_line=t("checkout.bonus_line", bonus=money(totals.bonus)) if totals.bonus else "",
        delivery=money(quote.price) if quote.price else t("checkout.free"),
        total=money(totals.total),
    )
    await state.set_state(CheckoutStates.confirm)
    await render(event, text, confirm_kb(bonus_available, checkout.use_bonus))


@router.callback_query(
    CheckoutStates.confirm, CheckoutCB.filter(F.a.in_({"bonus_on", "bonus_off"}))
)
async def cb_bonus(
    callback: CallbackQuery,
    callback_data: CheckoutCB,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
) -> None:
    await state.update_data(co_bonus=callback_data.a == "bonus_on")
    await _show_summary(callback, state, session, user, providers, settings)
    await callback.answer()


@router.callback_query(CheckoutStates.confirm, CheckoutCB.filter(F.a == "edit"))
async def cb_edit(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await render(callback, t("checkout.btn_edit"), None)
    await _ask_name(callback.message, state, user)
    await callback.answer()


@router.callback_query(CheckoutStates.confirm, CheckoutCB.filter(F.a == "confirm"))
async def cb_confirm(
    callback: CallbackQuery, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    payments = PaymentService(bot, settings)
    await state.set_state(CheckoutStates.payment)
    await render(
        callback,
        t("checkout.ask_payment"),
        payment_kb(payments.card_enabled, settings.cod_enabled, payments.test_mode),
    )
    await callback.answer()


@router.callback_query(CheckoutStates.payment, CheckoutCB.filter(F.a == "pay"))
async def cb_pay(
    callback: CallbackQuery,
    callback_data: CheckoutCB,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    notifier: Notifier,
    providers: dict[str, DeliveryProvider],
    settings: Settings,
    admins: AdminRegistry,
) -> None:
    payments = PaymentService(bot, settings)
    method = PaymentMethod(callback_data.v) if callback_data.v in {"card", "cod"} else None
    if (
        method is None
        or (method == PaymentMethod.CARD and not payments.card_enabled)
        or (method == PaymentMethod.COD and not settings.cod_enabled)
    ):
        await callback.answer(t("checkout.payment_not_available"), show_alert=True)
        return
    checkout = _checkout_data(await state.get_data())
    orders = build_order_service(session, notifier, providers, settings)
    try:
        order = await orders.create_from_cart(user, checkout, method)
    except (CartChanged, NoTariff):
        await _finish(state)
        await render(callback, t("checkout.cart_changed"), None)
        await show_cart(callback.message, session, user)
        await callback.answer()
        return
    await _finish(state)
    if method == PaymentMethod.COD:
        await render(
            callback, t("checkout.created_cod", order_id=order.id, total=money(order.total)), None
        )
        await callback.message.answer(
            t("menu.title"), reply_markup=await menu_markup(session, user, settings, admins)
        )
    elif payments.test_mode:
        await render(
            callback,
            t("checkout.created_card", order_id=order.id) + "\n\n" + t("checkout.test_mode_note"),
            test_pay_kb(order.id),
        )
    else:
        await render(callback, t("checkout.created_card", order_id=order.id), None)
        await payments.send_invoice(order)
    await callback.answer()

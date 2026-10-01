"""Корзина: просмотр, количество, удаление, промокод."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.keyboards.callbacks import CartCB, MenuCB
from app.keyboards.user import cancel_kb, cart_kb, empty_cart_kb
from app.services.cart import CartService, CartSummary, NotEnoughStock, VariantUnavailable
from app.services.promo import PromoError
from app.states import CartStates
from app.texts import t
from app.utils.formatting import h, money
from app.utils.telegram import render

router = Router(name="cart")


def cart_text(summary: CartSummary) -> str:
    lines = [t("cart.title")]
    for n, line in enumerate(summary.lines, start=1):
        if line.ok:
            lines.append(
                t(
                    "cart.line",
                    n=n,
                    title=h(line.title),
                    size=h(line.size),
                    color=h(line.color),
                    qty=line.qty,
                    price=money(line.price),
                    subtotal=money(line.subtotal),
                )
            )
        else:
            lines.append(
                t("cart.line_short", n=n, title=h(line.title), size=h(line.size), stock=line.stock)
            )
    lines.append(t("cart.items_total", total=money(summary.items_total)))
    if summary.promo_error is not None:
        lines.append(
            t("cart.promo_invalid", code=h(summary.promo_code), reason=summary.promo_error.message)
        )
    elif summary.discount:
        lines.append(
            t("cart.discount", code=h(summary.promo_code), discount=money(summary.discount))
        )
    lines.append(t("cart.total", total=money(summary.total)))
    if summary.has_problems:
        lines.append("\n" + t("cart.stock_problem"))
    return "\n".join(lines)


async def show_cart(
    event: CallbackQuery | Message, session: AsyncSession, user: User
) -> CartSummary:
    summary = await CartService(session).summary(user)
    if summary.is_empty:
        await render(event, t("cart.empty"), empty_cart_kb())
    else:
        await render(event, cart_text(summary), cart_kb(summary))
    return summary


@router.callback_query(MenuCB.filter(F.a == "cart"))
@router.callback_query(CartCB.filter(F.a == "show"))
async def cb_cart(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    await state.set_state(None)
    await show_cart(callback, session, user)
    await callback.answer()


@router.callback_query(CartCB.filter(F.a.in_({"inc", "dec"})))
async def cb_change_qty(
    callback: CallbackQuery, callback_data: CartCB, session: AsyncSession, user: User
) -> None:
    delta = 1 if callback_data.a == "inc" else -1
    try:
        await CartService(session).change_qty(user.id, callback_data.item, delta)
    except NotEnoughStock:
        await callback.answer(t("cart.max_reached"), show_alert=True)
        return
    except VariantUnavailable:
        pass
    await show_cart(callback, session, user)
    await callback.answer()


@router.callback_query(CartCB.filter(F.a == "del"))
async def cb_remove(
    callback: CallbackQuery, callback_data: CartCB, session: AsyncSession, user: User
) -> None:
    await CartService(session).remove(user.id, callback_data.item)
    await show_cart(callback, session, user)
    await callback.answer(t("cart.item_removed"))


@router.callback_query(CartCB.filter(F.a == "clear"))
async def cb_clear(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    await CartService(session).clear(user.id)
    user.cart_promo_code = None
    await show_cart(callback, session, user)
    await callback.answer(t("cart.cleared"))


@router.callback_query(CartCB.filter(F.a == "promo"))
async def cb_promo(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CartStates.promo)
    await render(callback, t("cart.enter_promo"), cancel_kb(CartCB(a="show")))
    await callback.answer()


@router.callback_query(CartCB.filter(F.a == "unpromo"))
async def cb_unpromo(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    user.cart_promo_code = None
    await show_cart(callback, session, user)
    await callback.answer(t("cart.promo_removed"))


@router.message(CartStates.promo, F.text)
async def promo_entered(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    code = message.text.strip()[:32]
    try:
        summary = await CartService(session).apply_promo(user, code)
    except PromoError as exc:
        await message.answer(
            t("cart.promo_invalid", code=h(code.upper()), reason=exc.message),
            reply_markup=cancel_kb(CartCB(a="show")),
        )
        return
    await state.set_state(None)
    await message.answer(
        t("cart.promo_applied", code=h(summary.promo_code), discount=money(summary.discount))
    )
    await show_cart(message, session, user)

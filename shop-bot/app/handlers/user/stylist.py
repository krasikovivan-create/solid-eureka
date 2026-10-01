"""ИИ-стилист: диалог, фото, «Что надеть с…», капсульный гардероб, образ в корзину."""

from __future__ import annotations

import io
import logging

import anthropic
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Order, OrderItem, User
from app.keyboards.callbacks import MenuCB, StylistCB
from app.keyboards.user import (
    stylist_fallback_kb,
    stylist_look_kb,
    stylist_menu_kb,
    stylist_pair_kb,
)
from app.repositories.catalog import CatalogRepository
from app.services.cart import CartError, CartService
from app.services.stylist import (
    MAX_IMAGE_BYTES,
    StylistDisabled,
    StylistLimitReached,
    StylistReply,
    StylistService,
    StylistUnavailable,
)
from app.states import StylistStates
from app.texts import t
from app.utils.formatting import h, money
from app.utils.telegram import render

logger = logging.getLogger(__name__)
router = Router(name="stylist")


def _service(
    session: AsyncSession, anthropic_client: anthropic.AsyncAnthropic | None, settings: Settings
) -> StylistService:
    return StylistService(session, anthropic_client, settings)


@router.callback_query(MenuCB.filter(F.a == "stylist"))
@router.callback_query(StylistCB.filter(F.a == "start"))
async def cb_stylist(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    settings: Settings,
    anthropic_client: anthropic.AsyncAnthropic | None,
) -> None:
    service = _service(session, anthropic_client, settings)
    if not service.enabled:
        await render(callback, t("stylist.disabled"), stylist_fallback_kb())
        await callback.answer()
        return
    await state.set_state(StylistStates.chat)
    left = await service.left_today(user.id)
    await render(callback, t("stylist.intro", left=left), stylist_menu_kb())
    await callback.answer()


async def _send_reply(message: Message, reply: StylistReply) -> None:
    if reply.refused:
        await message.answer(t("stylist.refusal"), reply_markup=stylist_menu_kb())
        return
    if not reply.looks:
        await message.answer(
            h(reply.text) if reply.text else t("stylist.empty_answer"),
            reply_markup=stylist_menu_kb(),
        )
        return
    if reply.text:
        await message.answer(h(reply.text))
    for index, look in enumerate(reply.looks):
        items = "\n".join(
            t(
                "stylist.look_item",
                title=h(item.title),
                size=f" ({h(item.size)})" if item.size else "",
                price=money(item.price),
            )
            for item in look.items
        )
        text = t(
            "stylist.look",
            title=h(look.title),
            explanation=h(look.explanation),
            items=items,
            total=money(look.total),
        )
        is_last = index == len(reply.looks) - 1
        await message.answer(
            text,
            reply_markup=stylist_look_kb(
                look.id, [i.as_dict() for i in look.items], with_menu=is_last
            ),
        )


async def _ask(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
    anthropic_client: anthropic.AsyncAnthropic | None,
    text: str,
    image: tuple[bytes, str] | None = None,
    mode: str = "chat",
) -> None:
    service = _service(session, anthropic_client, settings)
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            reply = await service.ask(user, text, image=image, mode=mode)
    except StylistDisabled:
        await message.answer(t("stylist.disabled"), reply_markup=stylist_fallback_kb())
        return
    except StylistLimitReached as exc:
        await message.answer(
            t("stylist.limit", limit=exc.limit), reply_markup=stylist_fallback_kb()
        )
        return
    except StylistUnavailable:
        await message.answer(t("stylist.unavailable"), reply_markup=stylist_fallback_kb())
        return
    await _send_reply(message, reply)


@router.message(StylistStates.chat, F.text)
async def msg_stylist_text(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
    anthropic_client: anthropic.AsyncAnthropic | None,
) -> None:
    await _ask(message, bot, session, user, settings, anthropic_client, message.text[:2000])


@router.message(StylistStates.chat, F.photo)
async def msg_stylist_photo(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
    anthropic_client: anthropic.AsyncAnthropic | None,
) -> None:
    photo = message.photo[-1]
    if photo.file_size and photo.file_size > MAX_IMAGE_BYTES:
        await message.answer(t("stylist.photo_too_big"))
        return
    buffer = io.BytesIO()
    await bot.download(photo, destination=buffer)
    caption = (message.caption or "").strip()[:1000] or t("stylist.photo_caption_default")
    await _ask(
        message,
        bot,
        session,
        user,
        settings,
        anthropic_client,
        caption,
        image=(buffer.getvalue(), "image/jpeg"),
        mode="photo",
    )


@router.callback_query(StylistCB.filter(F.a == "reset"))
async def cb_reset(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    settings: Settings,
    anthropic_client: anthropic.AsyncAnthropic | None,
) -> None:
    await _service(session, anthropic_client, settings).reset(user.id)
    await state.set_state(StylistStates.chat)
    await callback.message.answer(t("stylist.reset_done"), reply_markup=stylist_menu_kb())
    await callback.answer()


@router.callback_query(StylistCB.filter(F.a == "other"))
async def cb_other(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
    anthropic_client: anthropic.AsyncAnthropic | None,
) -> None:
    await callback.answer()
    await state.set_state(StylistStates.chat)
    await _ask(
        callback.message, bot, session, user, settings, anthropic_client, t("stylist.other_request")
    )


# ---------- «Что надеть с…» ----------
@router.callback_query(StylistCB.filter(F.a == "pair"))
async def cb_pair(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    summary = await CartService(session).summary(user)
    product_ids: list[int] = [line.product_id for line in summary.lines]
    stmt = (
        select(OrderItem.product_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.user_id == user.id, OrderItem.product_id.is_not(None))
        .order_by(OrderItem.id.desc())
        .limit(20)
    )
    product_ids += list((await session.scalars(stmt)).all())
    unique_ids = list(dict.fromkeys(product_ids))[:10]
    products = await CatalogRepository(session).get_products(unique_ids)
    if not products:
        await callback.answer(t("stylist.pair_empty"), show_alert=True)
        return
    await render(callback, t("stylist.pair_choose"), stylist_pair_kb(products))
    await callback.answer()


@router.callback_query(StylistCB.filter(F.a == "pair_pick"))
async def cb_pair_pick(
    callback: CallbackQuery,
    callback_data: StylistCB,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
    anthropic_client: anthropic.AsyncAnthropic | None,
) -> None:
    await callback.answer()
    product = await CatalogRepository(session).get_product(callback_data.id, with_inactive=True)
    if product is None:
        return
    await state.set_state(StylistStates.chat)
    request = t("stylist.pair_request", pid=product.id, title=product.title)
    await _ask(
        callback.message, bot, session, user, settings, anthropic_client, request, mode="pair"
    )


# ---------- Капсульный гардероб ----------
@router.callback_query(StylistCB.filter(F.a == "capsule"))
async def cb_capsule(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(StylistStates.capsule)
    await callback.message.answer(t("stylist.capsule_prompt"))
    await callback.answer()


@router.message(StylistStates.capsule, F.text)
async def msg_capsule(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
    anthropic_client: anthropic.AsyncAnthropic | None,
) -> None:
    await state.set_state(StylistStates.chat)
    request = t("stylist.capsule_request", text=message.text[:500])
    await _ask(message, bot, session, user, settings, anthropic_client, request, mode="capsule")


# ---------- Образ в корзину ----------
@router.callback_query(StylistCB.filter(F.a == "look_cart"))
async def cb_look_to_cart(
    callback: CallbackQuery,
    callback_data: StylistCB,
    session: AsyncSession,
    user: User,
    settings: Settings,
    anthropic_client: anthropic.AsyncAnthropic | None,
) -> None:
    service = _service(session, anthropic_client, settings)
    look = await service.get_look(callback_data.id, user.id)
    if look is None:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    cart = CartService(session)
    added, need_size = 0, []
    for item in look.items:
        if not item.get("variant_id"):
            need_size.append(item["title"])
            continue
        try:
            await cart.add(user.id, item["variant_id"], 1, look_id=look.id)
            added += 1
        except CartError:
            need_size.append(item["title"])
    if not added:
        await callback.answer(
            t("stylist.look_partial", items=", ".join(need_size))
            if need_size
            else t("stylist.look_missing"),
            show_alert=True,
        )
        return
    await service.mark_look_added(look)
    text = t("stylist.look_added", count=added)
    if need_size:
        text += t("stylist.look_partial", items=", ".join(need_size))
    await callback.answer(text, show_alert=True)

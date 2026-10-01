"""Старт, главное меню, рефералы, помощь и связь с менеджером."""

from __future__ import annotations

import logging
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.constants import UserEvent
from app.db.models import SupportMessage, User
from app.keyboards.callbacks import HelpCB, MenuCB
from app.keyboards.user import cancel_kb, help_back_kb, help_kb, main_menu, menu_row
from app.repositories.users import UserRepository
from app.services.cart import CartService
from app.states import SupportStates
from app.texts import t
from app.utils.formatting import h, money
from app.utils.telegram import render

logger = logging.getLogger(__name__)
router = Router(name="start")

UTM_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


async def menu_markup(session: AsyncSession, user: User, settings: Settings):
    count = await CartService(session).count(user.id)
    return main_menu(count, settings.stylist_available, settings.is_admin(user.id))


async def show_main_menu(
    event: Message | CallbackQuery, session: AsyncSession, user: User, settings: Settings
) -> None:
    await render(event, t("menu.title"), await menu_markup(session, user, settings))


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    user_created: bool,
    settings: Settings,
) -> None:
    had_state = await state.get_state() is not None
    await state.clear()
    payload = (command.args or "").strip()
    users = UserRepository(session)
    referral_note = ""
    if user_created and payload:
        if payload.startswith("ref_") and payload[4:].isdigit():
            referrer_id = int(payload[4:])
            if referrer_id != user.id and await users.get(referrer_id):
                user.referrer_id = referrer_id
                user.utm_source = "referral"
                referral_note = "\n\n" + t("start.referral_joined")
        elif UTM_RE.match(payload):
            user.utm_source = payload.lower()
    if user_created:
        await users.log_event(user.id, UserEvent.START)

    caption = t("start.welcome", name=h(message.from_user.first_name), shop=h(settings.shop_name))
    markup = await menu_markup(session, user, settings)
    if had_state:
        # Убираем reply-клавиатуру, оставшуюся от прерванного оформления.
        await message.answer(t("common.cancelled"), reply_markup=ReplyKeyboardRemove())
    try:
        await message.answer_photo(
            settings.banner_url, caption=caption + referral_note, reply_markup=markup
        )
    except TelegramAPIError:
        logger.warning("Не удалось отправить баннер %s", settings.banner_url)
        await message.answer(caption + referral_note, reply_markup=markup)


@router.callback_query(MenuCB.filter(F.a == "main"))
async def cb_main(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    await state.set_state(None)
    await show_main_menu(callback, session, user, settings)
    await callback.answer()


@router.callback_query(MenuCB.filter(F.a == "ref"))
async def cb_referral(
    callback: CallbackQuery, bot: Bot, session: AsyncSession, user: User, settings: Settings
) -> None:
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=ref_{user.id}"
    invited = await UserRepository(session).invited_count(user.id)
    text = t(
        "ref.info",
        bonus=money(settings.referral_bonus),
        share=settings.max_bonus_share_percent,
        link=link,
        invited=invited,
        balance=money(user.bonus_balance),
    )
    await render(callback, text, InlineKeyboardMarkup(inline_keyboard=[menu_row()]))
    await callback.answer()


# ---------- Помощь ----------
@router.callback_query(MenuCB.filter(F.a == "help"))
@router.callback_query(HelpCB.filter(F.a == "menu"))
async def cb_help(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    await render(callback, t("help.title"), help_kb())
    await callback.answer()


@router.callback_query(HelpCB.filter(F.a.in_({"delivery", "returns", "sizes", "payment"})))
async def cb_help_topic(callback: CallbackQuery, callback_data: HelpCB) -> None:
    text = t(f"help.{callback_data.a}")
    if callback_data.a == "sizes":
        text += "\n\n" + t("product.size_chart")
    await render(callback, text, help_back_kb())
    await callback.answer()


@router.callback_query(HelpCB.filter(F.a == "manager"))
async def cb_help_manager(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    if not settings.admin_ids:
        await callback.answer(t("help.no_admins"), show_alert=True)
        return
    await state.set_state(SupportStates.message)
    await render(callback, t("help.ask_manager"), cancel_kb(HelpCB(a="menu")))
    await callback.answer()


@router.message(SupportStates.message)
async def support_message(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    header = t(
        "admin.support_message",
        name=h(user.full_name),
        username=h(user.username or "—"),
        user_id=user.id,
    )
    delivered = False
    for admin_id in settings.admin_ids:
        try:
            head = await bot.send_message(admin_id, header)
            copy = await message.copy_to(admin_id)
        except TelegramAPIError:
            logger.warning("Не удалось переслать сообщение админу %s", admin_id)
            continue
        delivered = True
        for message_id in (head.message_id, copy.message_id):
            session.add(
                SupportMessage(user_id=user.id, admin_chat_id=admin_id, admin_message_id=message_id)
            )
    await state.set_state(None)
    text = t("help.sent") if delivered else t("help.no_admins")
    await message.answer(text, reply_markup=await menu_markup(session, user, settings))

"""Вход в админ-панель и ответы покупателям через бота."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SupportMessage
from app.keyboards.admin import admin_menu_kb
from app.keyboards.callbacks import AdminCB, MenuCB
from app.texts import t
from app.utils.formatting import h
from app.utils.telegram import render

logger = logging.getLogger(__name__)
router = Router(name="admin_menu")


class SupportReply(BaseFilter):
    """Сообщение админа — reply на пересланное обращение покупателя."""

    async def __call__(self, message: Message, session: AsyncSession) -> bool | dict:
        reply = message.reply_to_message
        if reply is None:
            return False
        user_id = await session.scalar(
            select(SupportMessage.user_id).where(
                SupportMessage.admin_chat_id == message.chat.id,
                SupportMessage.admin_message_id == reply.message_id,
            )
        )
        return {"support_user_id": user_id} if user_id else False


async def _reply_to_user(message: Message, bot: Bot, user_id: int, text: str | None) -> None:
    try:
        if text is not None:
            await bot.send_message(user_id, t("help.manager_reply", text=h(text)))
        else:
            await bot.send_message(user_id, t("help.manager_reply", text=""))
            await message.copy_to(user_id)
    except TelegramForbiddenError:
        await message.answer(t("admin.reply_failed"))
        return
    except TelegramAPIError:
        logger.exception("Не удалось ответить пользователю %s", user_id)
        await message.answer(t("common.error"))
        return
    await message.answer(t("admin.reply_sent"))


@router.message(SupportReply())
async def support_reply(message: Message, bot: Bot, support_user_id: int) -> None:
    await _reply_to_user(message, bot, support_user_id, message.text)


@router.message(Command("reply"))
async def cmd_reply(message: Message, command: CommandObject, bot: Bot) -> None:
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[0].isdigit():
        await message.answer(t("admin.reply_unknown"))
        return
    await _reply_to_user(message, bot, int(parts[0]), parts[1])


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    await message.answer(t("adm.title"), reply_markup=admin_menu_kb())


@router.callback_query(MenuCB.filter(F.a == "admin"))
@router.callback_query(AdminCB.filter(F.s == "menu"))
async def cb_admin(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    await render(callback, t("adm.title"), admin_menu_kb())
    await callback.answer()

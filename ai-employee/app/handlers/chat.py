"""Свободный диалог: онбординг → активный аудит → агент."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from app.agent.agent import Agent
from app.agent.llm import LLMError
from app.context import AppContext
from app.handlers.audit import handle_audit_answer
from app.handlers.common import deliver_outbox, send_html
from app.handlers.start import save_onboarding_answer
from app.services import audit as audit_service
from app.services.profile import get_profile
from app.services.textutils import esc, md_to_html

log = logging.getLogger(__name__)
router = Router(name="chat")

_background: set[asyncio.Task] = set()


@router.message(F.text)
async def on_text(message: Message, app: AppContext, agent: Agent, bot: Bot) -> None:
    text = message.text.strip()
    chat_id = message.chat.id
    user_id = message.from_user.id
    if text.startswith("/"):
        await message.answer("Не знаю такой команды. Список команд — /help")
        return

    profile = await get_profile(app.sf)
    if not profile.onboarded:
        await save_onboarding_answer(bot, chat_id, app, text)
        return

    audit = await audit_service.get_active_audit(app.sf, user_id)
    if audit is not None:
        await handle_audit_answer(bot, chat_id, app, audit, text, user_id)
        return

    await run_agent(bot, chat_id, app, agent, user_id, text)


async def run_agent(
    bot: Bot, chat_id: int, app: AppContext, agent: Agent, user_id: int, text: str
) -> None:
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=chat_id):
            reply = await agent.handle(user_id, text)
    except LLMError as exc:
        await bot.send_message(chat_id, esc(exc.user_message))
        return
    await send_html(bot, chat_id, md_to_html(reply.text))
    if reply.outbox:
        await deliver_outbox(bot, chat_id, reply.outbox, app)
    task = asyncio.create_task(_after(agent, user_id))
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _after(agent: Agent, user_id: int) -> None:
    try:
        await agent.after_reply(user_id)
    except Exception:
        log.exception("Ошибка фоновой обработки после ответа")


@router.message(F.voice | F.audio | F.video_note)
async def on_voice(message: Message) -> None:
    await message.answer("🎙 Голосовые пока не понимаю — напишите текстом, пожалуйста.")


@router.message(F.photo)
async def on_photo(message: Message) -> None:
    await message.answer(
        "🖼 Картинки пока не разбираю. Для базы знаний пришлите документ PDF, DOCX или TXT."
    )

"""Общие помощники обработчиков: отправка длинных сообщений, результаты агента."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup

from app import keyboards
from app.services.textutils import split_message, strip_html
from app.tools import OutAuditStarted, OutConfirm, OutFile, OutText

log = logging.getLogger(__name__)


async def send_html(
    bot: Bot, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """Отправляет HTML, режет длинные тексты; при ошибке разметки — простым текстом."""
    parts = split_message(text)
    for i, part in enumerate(parts):
        markup = reply_markup if i == len(parts) - 1 else None
        try:
            await bot.send_message(chat_id, part, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "parse" not in str(exc).lower() and "entit" not in str(exc).lower():
                raise
            log.warning("Ошибка HTML-разметки, отправляю без неё: %s", exc)
            await bot.send_message(chat_id, strip_html(part), reply_markup=markup, parse_mode=None)


async def edit_or_send(
    bot: Bot,
    chat_id: int,
    message_id: int | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if message_id is not None and len(text) <= 4000:
        try:
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
            )
            return
        except TelegramBadRequest as exc:
            if "not modified" in str(exc):
                return
    await send_html(bot, chat_id, text, reply_markup)


async def deliver_outbox(bot: Bot, chat_id: int, outbox: list[Any], app: Any) -> None:
    """Отправляет то, что инструменты подготовили для пользователя."""
    from app.handlers.audit import send_audit_question  # избегаем циклического импорта

    for item in outbox:
        if isinstance(item, OutText):
            await send_html(bot, chat_id, item.text)
        elif isinstance(item, OutFile):
            await bot.send_document(
                chat_id,
                BufferedInputFile(item.data, filename=item.filename),
                caption=item.caption[:1000] or None,
                parse_mode=None,
            )
        elif isinstance(item, OutConfirm):
            await bot.send_message(
                chat_id,
                f"🗑 Удалить {item.label}?",
                reply_markup=keyboards.confirm_delete(item.kind, item.object_id),
                parse_mode=None,
            )
        elif isinstance(item, OutAuditStarted):
            await send_audit_question(bot, chat_id, app, item.audit_id, intro=True)

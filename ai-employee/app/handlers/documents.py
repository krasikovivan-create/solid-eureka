"""Загрузка документов в базу знаний."""

from __future__ import annotations

import io
import logging

from aiogram import Bot, F, Router
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from app import keyboards
from app.context import AppContext
from app.services.documents import (
    MAX_FILE_SIZE,
    SUPPORTED_EXTENSIONS,
    UnsupportedDocumentError,
    is_supported,
)
from app.services.textutils import esc

log = logging.getLogger(__name__)
router = Router(name="documents")


@router.message(F.document)
async def on_document(message: Message, app: AppContext, bot: Bot) -> None:
    doc = message.document
    filename = doc.file_name or "document"
    if not is_supported(filename):
        exts = ", ".join(sorted(e.lstrip(".").upper() for e in SUPPORTED_EXTENSIONS))
        await message.answer(f"Этот формат я не читаю. Поддерживаются: {exts}.")
        return
    if doc.file_size and doc.file_size > MAX_FILE_SIZE:
        await message.answer("Файл больше 20 МБ — Telegram не даёт ботам скачивать такие файлы.")
        return
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        buf = io.BytesIO()
        await bot.download(doc, destination=buf)
        try:
            stored = await app.kb.add_document(filename, buf.getvalue())
        except UnsupportedDocumentError as exc:
            await message.answer(f"⚠️ {esc(exc)}")
            return
    docs = await app.kb.list_documents()
    chunks = next((n for d, n in docs if d.id == stored.id), 0)
    await message.answer(
        f"📚 Документ <b>{esc(filename)}</b> добавлен в базу знаний (#{stored.id}, "
        f"{stored.chars:,} символов, {chunks} фрагм.).\n"
        "Теперь можно задавать вопросы по нему.".replace(",", " "),
        reply_markup=keyboards.back_to_menu(),
    )

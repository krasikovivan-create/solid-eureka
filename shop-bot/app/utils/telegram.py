"""Вспомогательные функции для работы с сообщениями Telegram."""

from __future__ import annotations

import contextlib
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from app.db.models import Product
from app.repositories.catalog import CatalogRepository
from app.utils.media import media_input

logger = logging.getLogger(__name__)


async def render(
    event: Message | CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Показывает экран: для callback редактирует текущее сообщение, иначе отправляет новое.

    Если текущее сообщение — фото (баннер), оно удаляется и отправляется текст.
    """
    if isinstance(event, CallbackQuery):
        message = event.message
        if isinstance(message, Message):
            if message.text is not None:
                try:
                    return await message.edit_text(
                        text, reply_markup=reply_markup, disable_web_page_preview=True
                    )
                except TelegramBadRequest as exc:
                    if "message is not modified" in str(exc):
                        return message
            with contextlib.suppress(TelegramAPIError):
                await message.delete()
            return await message.answer(
                text, reply_markup=reply_markup, disable_web_page_preview=True
            )
        if event.from_user and event.bot:
            return await event.bot.send_message(event.from_user.id, text, reply_markup=reply_markup)
        return None
    return await event.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)


async def safe_delete(bot: Bot, chat_id: int, message_ids: list[int]) -> None:
    for message_id in message_ids:
        with contextlib.suppress(TelegramAPIError):
            await bot.delete_message(chat_id, message_id)


async def send_product_photos(
    bot: Bot, chat_id: int, product: Product, repo: CatalogRepository
) -> list[int]:
    """Отправляет фото товара (медиагруппой, если их несколько) и кэширует file_id.

    Возвращает id отправленных сообщений, чтобы потом их удалить при возврате к списку.
    """
    photos = [p for p in product.photos if p.media][:10]
    if not photos:
        return []
    try:
        if len(photos) == 1:
            sent = [await bot.send_photo(chat_id, media_input(photos[0].media))]
        else:
            sent = await bot.send_media_group(
                chat_id, media=[InputMediaPhoto(media=media_input(p.media)) for p in photos]
            )
    except (TelegramAPIError, FileNotFoundError):
        logger.warning("Не удалось отправить фото товара %s", product.id, exc_info=True)
        return []
    for photo, message in zip(photos, sent, strict=False):
        if message.photo and not photo.file_id:
            await repo.save_photo_file_id(photo.id, message.photo[-1].file_id)
    return [m.message_id for m in sent]

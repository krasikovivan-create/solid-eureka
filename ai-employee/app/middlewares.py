"""Middleware: доступ только для разрешённых пользователей, передача контекста."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.context import AppContext
from app.services import profile as profile_service
from app.texts import access_denied

log = logging.getLogger(__name__)


class AppMiddleware(BaseMiddleware):
    """Кладёт в data: app, agent, а также проверяет доступ."""

    def __init__(self, app: AppContext, agent: Any) -> None:
        self.app = app
        self.agent = agent

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return None
        data["app"] = self.app
        data["agent"] = self.agent

        sf = self.app.sf
        allowed_ids = self.app.settings.allowed_user_ids
        allowed = await profile_service.is_allowed(sf, allowed_ids, user.id)
        if not allowed and not allowed_ids and _is_start(event):
            allowed = await profile_service.try_claim_owner(sf, user.id)
            if allowed:
                log.info("Пользователь %s стал владельцем бота", user.id)
        if not allowed:
            log.warning("Отказано в доступе пользователю %s", user.id)
            if isinstance(event, Message) and event.chat.type == "private":
                await event.answer(access_denied(user.id))
            elif isinstance(event, CallbackQuery):
                await event.answer("Нет доступа", show_alert=True)
            return None
        await profile_service.upsert_user(sf, user.id, user.full_name, user.username)
        return await handler(event, data)


def _is_start(event: TelegramObject) -> bool:
    return isinstance(event, Message) and bool(event.text) and event.text.startswith("/start")

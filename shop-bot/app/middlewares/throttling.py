from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from aiogram.types import User as TgUser

from app.texts import t


class ThrottlingMiddleware(BaseMiddleware):
    """Защита от флуда: не чаще одного апдейта в rate секунд на пользователя.

    Медиагруппы (несколько фото одним сообщением) и сообщения об оплате не ограничиваются.
    """

    def __init__(self, rate: float = 0.4, max_entries: int = 50_000) -> None:
        self.rate = rate
        self.max_entries = max_entries
        self._last: dict[int, float] = {}
        self._warned: dict[int, float] = {}

    def _cleanup(self, now: float) -> None:
        if len(self._last) > self.max_entries:
            threshold = now - 60
            self._last = {k: v for k, v in self._last.items() if v > threshold}
            self._warned = {k: v for k, v in self._warned.items() if v > threshold}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None or self.rate <= 0:
            return await handler(event, data)
        # Медиагруппы и платёжные сообщения не ограничиваем: оплату терять нельзя.
        if getattr(event, "media_group_id", None) or getattr(event, "successful_payment", None):
            return await handler(event, data)
        now = time.monotonic()
        last = self._last.get(tg_user.id, 0.0)
        self._last[tg_user.id] = now
        if now - last >= self.rate:
            self._cleanup(now)
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer(t("common.throttled"))
        elif isinstance(event, Message) and now - self._warned.get(tg_user.id, 0.0) > 5:
            self._warned[tg_user.id] = now
            await event.answer(t("common.throttled"))
        return None

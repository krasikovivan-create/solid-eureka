from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.users import UserRepository


class UserMiddleware(BaseMiddleware):
    """Регистрирует пользователя и кладёт его в data["user"]."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        session: AsyncSession | None = data.get("session")
        if tg_user is None or session is None or tg_user.is_bot:
            return await handler(event, data)
        user, created = await UserRepository(session).upsert(
            tg_user.id, tg_user.username, tg_user.full_name
        )
        data["user"] = user
        data["user_created"] = created
        return await handler(event, data)

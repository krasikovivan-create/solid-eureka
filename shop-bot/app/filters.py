from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser

from app.services.admins import AdminRegistry


class IsAdmin(BaseFilter):
    async def __call__(
        self,
        event: TelegramObject,
        admins: AdminRegistry,
        event_from_user: TgUser | None = None,
    ) -> bool:
        return event_from_user is not None and admins.is_admin(event_from_user.id)

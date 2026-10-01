"""Список админов: ADMIN_IDS из окружения + админы, добавленные прямо в боте.

Всё управление доступно с телефона: если админов ещё нет, первый, кто отправит
боту /admin, становится владельцем; дальше админы добавляют друг друга в админ-панели.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Admin

logger = logging.getLogger(__name__)


class AdminRegistry:
    """Кэш админов в памяти процесса; источник истины — окружение и таблица admins."""

    def __init__(self, env_ids: list[int]) -> None:
        self.env_ids: frozenset[int] = frozenset(env_ids)
        self._db_ids: set[int] = set()

    @property
    def ids(self) -> list[int]:
        return sorted(self.env_ids | self._db_ids)

    @property
    def db_ids(self) -> list[int]:
        return sorted(self._db_ids)

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.env_ids or user_id in self._db_ids

    @property
    def empty(self) -> bool:
        return not self.env_ids and not self._db_ids

    async def load(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        async with session_factory() as session:
            self._db_ids = set((await session.scalars(select(Admin.user_id))).all())

    async def add(self, session: AsyncSession, user_id: int, added_by: int | None) -> bool:
        """Добавляет админа. False — он уже был админом."""
        if self.is_admin(user_id):
            return False
        session.add(Admin(user_id=user_id, added_by=added_by))
        await session.commit()
        self._db_ids.add(user_id)
        logger.info("Админ %s добавлен (кем: %s)", user_id, added_by)
        return True

    async def remove(self, session: AsyncSession, user_id: int) -> bool:
        """Удаляет админа, добавленного в боте. Админов из ADMIN_IDS удалить нельзя."""
        if user_id in self.env_ids or user_id not in self._db_ids:
            return False
        if len(self.ids) <= 1:
            return False  # без админов бот останется неуправляемым
        await session.execute(delete(Admin).where(Admin.user_id == user_id))
        await session.commit()
        self._db_ids.discard(user_id)
        logger.info("Админ %s удалён", user_id)
        return True

    async def claim(self, session: AsyncSession, user_id: int) -> bool:
        """Первый вход: если админов нет совсем, пользователь становится владельцем."""
        if not self.empty:
            return False
        # Повторная проверка по БД — на случай, если кэш ещё не загружен.
        if await session.scalar(select(Admin.user_id).limit(1)) is not None:
            await self._reload(session)
            return False
        return await self.add(session, user_id, added_by=None)

    async def _reload(self, session: AsyncSession) -> None:
        self._db_ids = set((await session.scalars(select(Admin.user_id))).all())

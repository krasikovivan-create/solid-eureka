from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.models import User, UserEventLog


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def upsert(self, user_id: int, username: str | None, full_name: str) -> tuple[User, bool]:
        """Возвращает пользователя и признак «создан только что»."""
        user = await self.session.get(User, user_id)
        created = False
        if user is None:
            user = User(id=user_id, username=username, full_name=full_name)
            self.session.add(user)
            await self.session.flush()
            created = True
        else:
            user.username = username
            user.full_name = full_name
            user.last_activity_at = utcnow()
            if user.is_blocked:
                user.is_blocked = False
        return user, created

    async def log_event(self, user_id: int, event: str) -> None:
        self.session.add(UserEventLog(user_id=user_id, event=event))

    async def invited_count(self, user_id: int) -> int:
        stmt = select(func.count(User.id)).where(User.referrer_id == user_id)
        return int(await self.session.scalar(stmt) or 0)

    async def set_blocked(self, user_id: int) -> None:
        user = await self.session.get(User, user_id)
        if user:
            user.is_blocked = True

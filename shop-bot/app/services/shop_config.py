"""Настройки магазина, редактируемые в админ-панели бота.

Значение из БД (если админ его задал) важнее значения из окружения, поэтому магазин
можно настроить с телефона, не заходя в панель хостинга.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import ShopSetting

EDITABLE_KEYS = ("shop_name", "welcome", "banner", "pickup_address", "operator")


class ShopConfig:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._values: dict[str, str] = {}
        # Кэш file_id для локальных картинок: загружаем файл в Telegram один раз.
        self.file_ids: dict[str, str] = {}

    async def load(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        async with session_factory() as session:
            rows = (await session.scalars(select(ShopSetting))).all()
        self._values = {row.key: row.value for row in rows if row.value}

    async def set(self, session: AsyncSession, key: str, value: str) -> None:
        if key not in EDITABLE_KEYS:
            raise KeyError(key)
        row = await session.get(ShopSetting, key)
        if row is None:
            session.add(ShopSetting(key=key, value=value))
        else:
            row.value = value
        await session.commit()
        if value:
            self._values[key] = value
        else:
            self._values.pop(key, None)

    def is_custom(self, key: str) -> bool:
        return key in self._values

    @property
    def shop_name(self) -> str:
        return self._values.get("shop_name", self.settings.shop_name)

    @property
    def welcome(self) -> str:
        """Свой текст приветствия (пусто — стандартный)."""
        return self._values.get("welcome", "")

    @property
    def banner(self) -> str:
        return self._values.get("banner", self.settings.banner_url)

    @property
    def pickup_address(self) -> str:
        return self._values.get("pickup_address", self.settings.pickup_address)

    @property
    def operator(self) -> str:
        """Оператор персональных данных для политики (ИП/ООО, ИНН, e-mail)."""
        return self._values.get("operator", "")

    @property
    def privacy_url(self) -> str:
        return self.settings.privacy_policy_url

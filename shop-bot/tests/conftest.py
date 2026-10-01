from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

os.environ.setdefault("BOT_TOKEN", "123456:TEST")

from app.constants import DeliveryMethod
from app.db.base import Base
from app.db.models import (
    Category,
    DeliveryTariff,
    DeliveryZone,
    Product,
    ProductVariant,
    User,
)
from app.db.session import create_engine
from app.services.delivery import build_providers


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def order_status_changed(self, order) -> None:
        self.calls.append(("status", order.status))

    async def new_order(self, order) -> None:
        self.calls.append(("new_order", order.id))

    async def order_paid(self, order) -> None:
        self.calls.append(("paid", order.id))

    async def refund_needed(self, order) -> None:
        self.calls.append(("refund", order.id))

    async def referral_rewarded(self, user_id: int, bonus: int) -> None:
        self.calls.append(("referral", user_id))

    async def send(self, chat_id: int, text: str, reply_markup=None) -> bool:
        self.calls.append(("send", chat_id))
        return True

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


# По умолчанию тесты идут на SQLite в памяти. Для проверки на PostgreSQL:
# TEST_DATABASE_URL=postgresql://user@host:5432/test_db pytest
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


async def make_test_engine(fallback_url: str = "sqlite+aiosqlite://"):
    # create_engine для SQLite включает PRAGMA foreign_keys — ошибки FK ловятся и без PostgreSQL.
    engine = create_engine(TEST_DATABASE_URL or fallback_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = await make_test_engine()
    yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    await engine.dispose()


@pytest.fixture
async def session(session_factory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


@pytest.fixture
def notifier() -> FakeNotifier:
    return FakeNotifier()


@pytest.fixture
def providers():
    return build_providers()


@pytest.fixture
async def user(session: AsyncSession) -> User:
    u = User(id=1001, username="buyer", full_name="Иван Покупатель")
    session.add(u)
    await session.commit()
    return u


@pytest.fixture
async def catalog(session: AsyncSession) -> dict[str, object]:
    """Две категории, три товара с вариантами."""
    tees = Category(slug="tshirts", title="Футболки", emoji="👕", sort=1)
    hoodies = Category(slug="hoodies", title="Худи", emoji="🧥", sort=2)
    session.add_all([tees, hoodies])
    await session.flush()

    tee = Product(
        category_id=tees.id,
        title="Футболка базовая",
        description="Хлопок",
        composition="100% хлопок",
        gender="unisex",
        style="casual",
        price=1990,
        old_price=2490,
    )
    tee.variants = [
        ProductVariant(size="S", color="чёрный", stock=3),
        ProductVariant(size="M", color="чёрный", stock=5),
        ProductVariant(size="M", color="белый", stock=0),
    ]
    tee2 = Product(
        category_id=tees.id,
        title="Футболка оверсайз",
        description="",
        composition="хлопок",
        gender="female",
        style="street",
        price=2490,
    )
    tee2.variants = [ProductVariant(size="M", color="белый", stock=2)]
    hoodie = Product(
        category_id=hoodies.id,
        title="Худи на молнии",
        description="Тёплое",
        composition="хлопок",
        gender="male",
        style="sport",
        price=5990,
    )
    hoodie.variants = [ProductVariant(size="L", color="серый", stock=1)]
    for p, cat in ((tee, tees), (tee2, tees), (hoodie, hoodies)):
        session.add(p)
        p.rebuild_search_text(cat.title)
    await session.flush()

    moscow = DeliveryZone(name="Москва", cities="москва, зеленоград")
    russia = DeliveryZone(name="Россия", cities="", is_default=True)
    moscow.tariffs = [
        DeliveryTariff(
            method=DeliveryMethod.COURIER, price=390, free_from=5000, days_min=1, days_max=2
        ),
        DeliveryTariff(
            method=DeliveryMethod.CDEK, price=290, free_from=7000, days_min=1, days_max=3
        ),
        DeliveryTariff(method=DeliveryMethod.PICKUP, price=0, days_min=1, days_max=1),
    ]
    russia.tariffs = [
        DeliveryTariff(
            method=DeliveryMethod.CDEK, price=490, free_from=10000, days_min=3, days_max=7
        ),
        DeliveryTariff(method=DeliveryMethod.POST, price=350, days_min=5, days_max=14),
    ]
    session.add_all([moscow, russia])
    await session.commit()
    return {
        "tees": tees,
        "hoodies": hoodies,
        "tee": tee,
        "tee2": tee2,
        "hoodie": hoodie,
        "tee_s_black": tee.variants[0],
        "tee_m_black": tee.variants[1],
        "tee_m_white": tee.variants[2],
        "hoodie_l": hoodie.variants[0],
    }

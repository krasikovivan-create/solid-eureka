from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from sqlalchemy import update

from app.config import Settings
from app.constants import DeliveryMethod, OrderStatus, PaymentMethod, Segment
from app.db.base import utcnow
from app.db.models import Broadcast, CartItem, Order, OrderItem, User
from app.middlewares.throttling import ThrottlingMiddleware
from app.services.broadcast import BroadcastRunner, BroadcastService, segment_user_ids
from app.services.cart import CartService
from app.services.favorites import FavoriteService
from app.services.jobs import Jobs
from app.services.orders import CheckoutData, OrderService
from app.services.payments import build_receipt, invoice_prices, make_payload, parse_payload
from app.services.recommendations import RecommendationService
from app.services.stats import StatsService


async def make_order(session, user, variant, providers, notifier, method=PaymentMethod.COD):
    await CartService(session).add(user.id, variant.id)
    service = OrderService(session, notifier, providers)
    data = CheckoutData(
        "Иван", "+79123456789", "Москва", "ул. Ленина, д. 1", DeliveryMethod.COURIER
    )
    return await service.create_from_cart(user, data, method)


# ---------- Рекомендации ----------
async def test_similar_prefers_same_category(session, catalog):
    recs = RecommendationService(session)
    similar = await recs.similar(catalog["tee"])
    assert similar[0].id == catalog["tee2"].id
    assert catalog["tee"].id not in [p.id for p in similar]


async def test_bought_with_uses_order_history(session, user, catalog, providers, notifier):
    cart = CartService(session)
    await cart.add(user.id, catalog["tee_s_black"].id)
    await cart.add(user.id, catalog["hoodie_l"].id)
    service = OrderService(session, notifier, providers)
    data = CheckoutData(
        "Иван", "+79123456789", "Москва", "ул. Ленина, д. 1", DeliveryMethod.COURIER
    )
    order = await service.create_from_cart(user, data, PaymentMethod.COD)
    await service.change_status(order.id, OrderStatus.ASSEMBLING)
    # Вернём худи на склад, иначе рекомендовать нечего.
    catalog["hoodie_l"].stock = 3
    await session.commit()
    bought = await RecommendationService(session).bought_with(catalog["tee"].id)
    assert bought[0].id == catalog["hoodie"].id


async def test_personal_feed(session, user, catalog):
    recs = RecommendationService(session)
    products, personal = await recs.personal(user.id)
    assert not personal and products  # без истории — популярное/новинки

    from app.repositories.catalog import CatalogRepository

    await CatalogRepository(session).add_view(user.id, catalog["tee2"].id)
    await session.commit()
    products, personal = await recs.personal(user.id)
    assert personal
    assert products[0].category_id == catalog["tees"].id


# ---------- Избранное ----------
async def test_favorite_alerts(session, user, catalog):
    favs = FavoriteService(session)
    assert await favs.toggle(user.id, catalog["tee"]) is True
    assert await favs.toggle(user.id, catalog["hoodie"]) is True
    catalog["hoodie_l"].stock = 0
    await session.commit()
    assert await favs.collect_alerts() == []  # худи закончилось — запомнили

    catalog["tee"].price = 1490
    catalog["hoodie_l"].stock = 2
    await session.commit()
    alerts = {a.kind: a for a in await favs.collect_alerts()}
    assert alerts["price_drop"].new_price == 1490
    assert alerts["price_drop"].old_price == 1990
    assert alerts["back_in_stock"].product_id == catalog["hoodie"].id
    assert await favs.collect_alerts() == []  # повторно не уведомляем

    assert await favs.toggle(user.id, catalog["tee"]) is False
    assert [p.id for p in await favs.list(user.id)] == [catalog["hoodie"].id]


# ---------- Оплата ----------
async def test_invoice_and_receipt_sum_up(session, user, catalog, providers, notifier):
    user.bonus_balance = 333
    await CartService(session).add(user.id, catalog["tee_m_black"].id, 3)
    await CartService(session).add(user.id, catalog["tee2"].variants[0].id, 1)
    service = OrderService(session, notifier, providers)
    data = CheckoutData(
        "Иван", "+79123456789", "Казань", "ул. Баумана, д. 1", DeliveryMethod.CDEK, use_bonus=True
    )
    order = await service.create_from_cart(user, data, PaymentMethod.CARD)
    assert order.bonus_used > 0

    prices = invoice_prices(order)
    assert sum(p.amount for p in prices) == order.total * 100

    receipt = build_receipt(order, vat_code=1)["receipt"]
    total_kop = sum(
        round(float(i["amount"]["value"]) * 100) * int(float(i["quantity"]))
        for i in receipt["items"]
    )
    assert total_kop == order.total * 100
    assert receipt["customer"]["phone"] == "79123456789"
    assert parse_payload(make_payload(order.id)) == order.id
    assert parse_payload("bad") is None


# ---------- Рассылки ----------
class FakeBot:
    def __init__(self, fail: dict[int, Exception] | None = None) -> None:
        self.sent: list[int] = []
        self.fail = dict(fail or {})

    async def send_message(self, chat_id, text, reply_markup=None):
        error = self.fail.pop(chat_id, None)
        if error:
            raise error
        self.sent.append(chat_id)

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
        await self.send_message(chat_id, caption, reply_markup)


async def test_segments(session, user, catalog, providers, notifier):
    other = User(id=2002, full_name="Другой")
    blocked = User(id=3003, full_name="Ушёл", is_blocked=True)
    session.add_all([other, blocked])
    await session.commit()
    await make_order(session, user, catalog["tee_s_black"], providers, notifier)
    await CartService(session).add(other.id, catalog["hoodie_l"].id)
    await session.commit()

    assert await segment_user_ids(session, Segment.ALL) == [user.id, other.id]
    assert await segment_user_ids(session, Segment.ABANDONED) == [other.id]
    # COD-заказ в статусе «новый» ещё не покупка; после сборки — покупка.
    assert await segment_user_ids(session, Segment.BUYERS) == []
    order = (await OrderService(session, notifier, providers).list_for_user(user.id))[0]
    await OrderService(session, notifier, providers).change_status(order.id, OrderStatus.ASSEMBLING)
    assert await segment_user_ids(session, Segment.BUYERS) == [user.id]
    assert await segment_user_ids(session, Segment.CATEGORY, catalog["tees"].id) == [user.id]


async def test_broadcast_runner(session_factory, session, user, catalog):
    session.add_all([User(id=2002, full_name="A"), User(id=3003, full_name="B")])
    await session.commit()
    broadcast = await BroadcastService(session).create(
        created_by=1, segment=Segment.ALL, text="Скидки!", product_id=catalog["tee"].id
    )
    await session.commit()
    retry = TelegramRetryAfter(
        method=SendMessage(chat_id=2002, text="x"), message="flood", retry_after=0
    )
    forbidden = TelegramForbiddenError(
        method=SendMessage(chat_id=3003, text="x"), message="blocked"
    )
    bot = FakeBot(fail={2002: retry, 3003: forbidden})
    runner = BroadcastRunner(bot, session_factory, rate=1000)

    result = await runner.run(broadcast.id)
    assert result.status == "done"
    assert (result.total, result.sent, result.failed) == (3, 2, 1)
    assert sorted(bot.sent) == [1, 1001, 2002]  # 1 — отчёт админу
    async with session_factory() as s:
        assert (await s.get(User, 3003)).is_blocked
        # Повторный запуск той же рассылки ничего не делает.
        assert await runner.run(broadcast.id) is None
        assert (await s.get(Broadcast, broadcast.id)).sent == 2


# ---------- Брошенная корзина ----------
async def test_abandoned_cart_reminder(
    session_factory, session, user, catalog, providers, notifier
):
    await CartService(session).add(user.id, catalog["tee_s_black"].id)
    await session.commit()
    settings = Settings(_env_file=None, bot_token="1:x", abandoned_cart_hours=24)
    jobs = Jobs(FakeBot(), session_factory, settings, notifier, providers)

    assert await jobs.abandoned_carts() == 0  # корзина свежая
    await session.execute(update(CartItem).values(updated_at=utcnow() - timedelta(hours=25)))
    await session.commit()
    assert await jobs.abandoned_carts() == 1
    assert await jobs.abandoned_carts() == 0  # второй раз не напоминаем


# ---------- Статистика ----------
async def test_shop_stats(session, user, catalog, providers, notifier):
    await make_order(session, user, catalog["tee_s_black"], providers, notifier)
    user.utm_source = "vk_ads"
    await session.commit()
    stats = await StatsService(session).shop("week")
    assert stats.orders == 1 and stats.success == 1
    assert stats.revenue == 1990 + 390
    assert stats.carted_users == 1 and stats.ordered_users == 1
    assert stats.conversion == 100.0
    assert stats.top[0][0] == "Футболка базовая"
    assert stats.sources[0][0] == "vk_ads"

    old = Order(
        user_id=user.id,
        customer_name="x",
        phone="x",
        delivery_method="courier",
        items_total=1,
        total=1,
        payment_method="cod",
        created_at=utcnow() - timedelta(days=40),
        items=[OrderItem(title="t", size="s", color="c", price=1, qty=1)],
    )
    session.add(old)
    await session.commit()
    assert (await StatsService(session).shop("month")).orders == 1


# ---------- Антифлуд ----------
async def test_throttling_middleware():
    middleware = ThrottlingMiddleware(rate=10)
    calls = []

    async def handler(event, data):
        calls.append(event)

    user = SimpleNamespace(id=1)

    class FakeMessage:
        media_group_id = None
        successful_payment = None

        async def answer(self, text):
            calls.append(("warn", text))

    await middleware(handler, FakeMessage(), {"event_from_user": user})
    await middleware(handler, FakeMessage(), {"event_from_user": user})
    assert len([c for c in calls if isinstance(c, FakeMessage)]) == 1

    payment = FakeMessage()
    payment.successful_payment = object()
    await middleware(handler, payment, {"event_from_user": user})
    assert calls[-1] is payment  # оплату не режем никогда

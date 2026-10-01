"""Сквозной тест: апдейты Telegram идут через настоящий Dispatcher, а запросы к Bot API
перехватываются фейковой сессией. Проверяем путь покупателя от /start до заказа и админку."""

from __future__ import annotations

import itertools
from datetime import datetime
from typing import Any

import anthropic
import httpx2
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    Contact,
    Message,
    MessageId,
    PhotoSize,
    Update,
)
from aiogram.types import User as TgUser
from sqlalchemy import select

from app.bot import build_app
from app.config import Settings
from app.constants import OrderStatus
from app.db.base import Base
from app.db.models import (
    Broadcast,
    CartItem,
    Category,
    DeliveryTariff,
    Order,
    Product,
    ProductVariant,
    PromoCode,
    StylistLook,
    SupportMessage,
)
from app.keyboards.callbacks import (
    AdminCB,
    CartCB,
    CatCB,
    CheckoutCB,
    MenuCB,
    OrderCB,
    ProdCB,
)
from app.repositories.catalog import CatalogRepository
from scripts.seed import seed
from tests.conftest import TEST_DATABASE_URL
from tests.test_stylist import FakeClient, response, tool_use

USER_ID = 777
ADMIN_ID = 1


class FakeSession(BaseSession):
    """Отвечает на любой метод Bot API правдоподобным объектом и запоминает вызовы."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []
        self._ids = itertools.count(1000)

    async def close(self) -> None:
        return None

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - не используется
        yield b""

    def _message(self, chat_id: int, text: str | None = None, photo: bool = False) -> Message:
        return Message(
            message_id=next(self._ids),
            date=datetime.now(),
            chat=Chat(id=chat_id, type="private"),
            text=text,
            photo=[PhotoSize(file_id=f"f{next(self._ids)}", file_unique_id="u", width=1, height=1)]
            if photo
            else None,
        )

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod,
        timeout: int | None = None,  # noqa: ASYNC109 — сигнатура задана aiogram
    ):
        self.requests.append(method)
        name = type(method).__name__
        chat_id = getattr(method, "chat_id", USER_ID) or USER_ID
        if name == "GetMe":
            return TgUser(id=42, is_bot=True, first_name="Shop", username="shop_test_bot")
        if name in {"SendMessage", "EditMessageText"}:
            return self._message(chat_id, method.text)
        if name == "SendPhoto":
            return self._message(chat_id, photo=True)
        if name == "SendMediaGroup":
            return [self._message(chat_id, photo=True) for _ in method.media]
        if name == "CopyMessage":
            return MessageId(message_id=next(self._ids))
        return True

    def sent(self, name: str) -> list[Any]:
        return [r for r in self.requests if type(r).__name__ == name]

    def texts(self) -> list[str]:
        return [
            r.text for r in self.requests if type(r).__name__ in {"SendMessage", "EditMessageText"}
        ]

    def last_markup(self):
        for r in reversed(self.requests):
            markup = getattr(r, "reply_markup", None)
            if markup is not None and hasattr(markup, "inline_keyboard"):
                return markup
        return None


class Harness:
    def __init__(self, app, session: FakeSession) -> None:
        self.app = app
        self.session = session
        self.update_ids = itertools.count(1)
        self.msg_ids = itertools.count(1)

    def _user(self, user_id: int) -> TgUser:
        return TgUser(id=user_id, is_bot=False, first_name="Иван", last_name="Петров")

    async def message(self, text: str | None = None, user_id: int = USER_ID, **extra) -> None:
        msg = Message(
            message_id=next(self.msg_ids),
            date=datetime.now(),
            chat=Chat(id=user_id, type="private"),
            from_user=self._user(user_id),
            text=text,
            **extra,
        )
        await self.app.dp.feed_update(
            self.app.bot, Update(update_id=next(self.update_ids), message=msg)
        )

    async def click(self, data, user_id: int = USER_ID, text: str = "экран") -> None:
        packed = data if isinstance(data, str) else data.pack()
        message = Message(
            message_id=next(self.msg_ids),
            date=datetime.now(),
            chat=Chat(id=user_id, type="private"),
            text=text,
        )
        callback = CallbackQuery(
            id=str(next(self.update_ids)),
            from_user=self._user(user_id),
            chat_instance="ci",
            message=message,
            data=packed,
        )
        await self.app.dp.feed_update(
            self.app.bot, Update(update_id=next(self.update_ids), callback_query=callback)
        )


@pytest.fixture
async def harness(tmp_path):
    settings = Settings(
        _env_file=None,
        bot_token="42:TEST",
        admin_ids=str(ADMIN_ID),
        database_url=TEST_DATABASE_URL or f"sqlite+aiosqlite:///{tmp_path / 'bot.db'}",
        throttle_rate=0,
        stylist_enabled=False,
        payments_mode="fake",
    )
    fake = FakeSession()
    app = build_app(settings, bot_session=fake)
    async with app.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with app.session_factory() as s:
        await seed(s)
    yield Harness(app, fake)
    await app.engine.dispose()


def buttons(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]


async def test_purchase_flow_cod(harness: Harness):
    h, fake = harness, harness.session
    await h.message("/start promo_vk")
    assert fake.sent("SendPhoto"), "баннер с главным меню"

    await h.click(MenuCB(a="catalog"))
    cats = [c for c in buttons(fake.last_markup()) if c.startswith("c:list")]
    assert len(cats) == 6

    await h.click(cats[0])
    products = [c for c in buttons(fake.last_markup()) if c.startswith("p:view")]
    assert products

    async with h.app.session_factory() as s:
        variant = await s.scalar(
            select(ProductVariant).where(ProductVariant.stock >= 2).order_by(ProductVariant.id)
        )
        pid, vid, stock_before = variant.product_id, variant.id, variant.stock

    await h.click(ProdCB(a="view", pid=pid))
    assert fake.sent("SendMediaGroup") or fake.sent("SendPhoto")
    await h.click(ProdCB(a="var", pid=pid, c=0, vid=vid))
    await h.click(ProdCB(a="add", pid=pid, c=0, vid=vid))
    await h.click(ProdCB(a="add", pid=pid, c=0, vid=vid))

    await h.click(CartCB(a="show"))
    assert "Корзина" in fake.texts()[-1]

    await h.click(CartCB(a="checkout"))
    assert "152-ФЗ" in fake.texts()[-1]
    await h.click(CheckoutCB(a="agree"))
    await h.message("Иван Петров")
    await h.message(
        user_id=USER_ID,
        contact=Contact(phone_number="+79123456789", first_name="Иван", user_id=USER_ID),
    )
    await h.message("Москва")
    methods = buttons(fake.last_markup())
    assert "o:method:courier" in methods and "o:method:pickup" in methods
    await h.click(CheckoutCB(a="method", v="courier"))
    await h.message("ул. Тверская, д. 7, кв. 15")
    assert "Проверьте заказ" in fake.texts()[-1]
    await h.click(CheckoutCB(a="confirm"))
    await h.click(CheckoutCB(a="pay", v="cod"))
    assert any("оформлен" in t for t in fake.texts())

    async with h.app.session_factory() as s:
        order = await s.scalar(select(Order))
        assert order.status == OrderStatus.NEW
        assert order.phone == "+79123456789"
        assert order.stock_deducted
        variant = await s.get(ProductVariant, vid)
        assert variant.stock == stock_before - 2
    # Админ получил уведомление о новом заказе.
    assert any(r.chat_id == ADMIN_ID and "Новый заказ" in r.text for r in fake.sent("SendMessage"))

    # Админ ведёт заказ по статусам — покупатель получает уведомления.
    for status in ("assembling", "shipped"):
        await h.click(AdminCB(s="order", a="set", id=order.id, v=status), user_id=ADMIN_ID)
    async with h.app.session_factory() as s:
        order = await s.get(Order, order.id)
        assert order.status == OrderStatus.SHIPPED
    notices = [r.text for r in fake.sent("SendMessage") if r.chat_id == USER_ID]
    assert any("Собирается" in t for t in notices)
    assert any("Передан в доставку" in t for t in notices)

    # «Мои заказы» и повтор заказа.
    await h.click(OrderCB(a="view", oid=order.id))
    assert f"Заказ №{order.id}" in fake.texts()[-1]


async def test_card_payment_in_test_mode(harness: Harness):
    h, fake = harness, harness.session
    await h.message("/start")
    async with h.app.session_factory() as s:
        variant = await s.scalar(select(ProductVariant).where(ProductVariant.stock >= 1))
        pid, vid, stock_before = variant.product_id, variant.id, variant.stock
    await h.click(ProdCB(a="add", pid=pid, vid=vid))
    await h.click(CartCB(a="checkout"))
    await h.click(CheckoutCB(a="agree"))
    await h.message("Мария")
    await h.message("8 912 345 67 89")
    await h.message("Казань")
    assert "o:method:courier" not in buttons(fake.last_markup())
    await h.click(CheckoutCB(a="method", v="cdek"))
    await h.message("ул. Баумана, д. 1")
    await h.click(CheckoutCB(a="confirm"))
    await h.click(CheckoutCB(a="pay", v="card"))
    async with h.app.session_factory() as s:
        order = await s.scalar(select(Order))
        assert order.status == OrderStatus.NEW and not order.stock_deducted
    await h.click(OrderCB(a="pay", oid=order.id))
    async with h.app.session_factory() as s:
        order = await s.get(Order, order.id)
        assert order.is_paid and order.status == OrderStatus.PAID
        assert (await s.get(ProductVariant, vid)).stock == stock_before - 1


async def test_validation_errors_in_checkout(harness: Harness):
    h, fake = harness, harness.session
    await h.message("/start")
    async with h.app.session_factory() as s:
        variant = await s.scalar(select(ProductVariant).where(ProductVariant.stock >= 1))
    await h.click(ProdCB(a="add", pid=variant.product_id, vid=variant.id))
    await h.click(CartCB(a="checkout"))
    await h.click(CheckoutCB(a="agree"))
    await h.message("1")
    assert "Имя" in fake.texts()[-1]
    await h.message("Анна")
    await h.message("12345")
    assert "российский номер" in fake.texts()[-1]
    # Чужой контакт не принимаем.
    await h.message(contact=Contact(phone_number="+79990000000", first_name="X", user_id=1))
    assert "свой контакт" in fake.texts()[-1]


async def test_search_filters_and_favorites(harness: Harness):
    h, fake = harness, harness.session
    await h.message("/start")
    await h.click(MenuCB(a="search"))
    await h.message("худи")
    results = [c for c in buttons(fake.last_markup()) if c.startswith("p:view")]
    assert len(results) >= 3

    await h.click(CatCB(a="fv", cat=1, k="price", v="p1"))
    assert "до 2 000" in fake.texts()[-1]

    pid = int(results[0].split(":")[2])
    await h.click(ProdCB(a="view", pid=pid))
    await h.click(ProdCB(a="fav", pid=pid))
    await h.click(MenuCB(a="fav"))
    assert f"p:view:{pid}" in "".join(buttons(fake.last_markup()))


async def test_admin_panel_requires_admin(harness: Harness):
    h, fake = harness, harness.session
    await h.message("/admin")
    assert "Админ-панель" not in (fake.texts()[-1] if fake.texts() else "")
    await h.message("/admin", user_id=ADMIN_ID)
    assert "Админ-панель" in fake.texts()[-1]
    await h.click(AdminCB(s="stats", a="p", v="week"), user_id=ADMIN_ID)
    assert "Статистика" in fake.texts()[-1]
    await h.click(AdminCB(s="sty"), user_id=ADMIN_ID)
    assert "ИИ-стилист" in fake.texts()[-1]


async def test_support_message_and_reply(harness: Harness):
    h, fake = harness, harness.session
    await h.message("/start")
    await h.click("h:manager")
    await h.message("Где мой заказ?")
    header = next(r for r in fake.sent("SendMessage") if r.chat_id == ADMIN_ID)
    assert "Сообщение от покупателя" in header.text
    assert fake.sent("CopyMessage")

    # Админ отвечает реплаем на заголовок — ответ уходит покупателю.
    async with h.app.session_factory() as s:
        link = await s.scalar(select(SupportMessage))
        header_msg_id = link.admin_message_id
    reply_to = Message(
        message_id=header_msg_id,
        date=datetime.now(),
        chat=Chat(id=ADMIN_ID, type="private"),
        text="header",
    )
    await h.message("Заказ уже в пути!", user_id=ADMIN_ID, reply_to_message=reply_to)
    assert any(
        r.chat_id == USER_ID and "Заказ уже в пути" in r.text for r in fake.sent("SendMessage")
    )


async def test_stylist_dialog_through_bot(harness: Harness):
    h, fake = harness, harness.session
    settings = h.app.dp.workflow_data["settings"]
    stylist_settings = settings.model_copy(
        update={"stylist_enabled": True, "anthropic_api_key": "key"}
    )
    async with h.app.session_factory() as s:
        variant = await s.scalar(
            select(ProductVariant).where(ProductVariant.stock >= 1).order_by(ProductVariant.id)
        )
    client = FakeClient(
        [
            response(tool_use("get_product", {"product_id": variant.product_id}, "t1")),
            response(
                tool_use(
                    "present_looks",
                    {
                        "intro": "Держите образ",
                        "looks": [
                            {
                                "title": "Город",
                                "explanation": "Просто и удобно.",
                                "items": [
                                    {
                                        "product_id": variant.product_id,
                                        "size": variant.size,
                                        "color": variant.color,
                                    }
                                ],
                            }
                        ],
                    },
                    "t2",
                )
            ),
        ]
    )
    h.app.dp.workflow_data.update(settings=stylist_settings, anthropic_client=client)

    await h.message("/start")
    await h.click(MenuCB(a="stylist"))
    assert "ИИ-стилист" in fake.texts()[-1]
    await h.message("Образ на прогулку, размер M")
    assert fake.sent("SendChatAction"), "индикатор «печатает…»"
    look_text = fake.texts()[-1]
    assert "Город" in look_text and "Сумма образа" in look_text
    look_button = next(c for c in buttons(fake.last_markup()) if c.startswith("s:look_cart"))
    await h.click(look_button)
    async with h.app.session_factory() as s:
        item = await s.scalar(select(CartItem))
        assert item.variant_id == variant.id and item.stylist_look_id
        look = await s.get(StylistLook, item.stylist_look_id)
        assert look.added_to_cart_at is not None

    # API недоступно → понятное сообщение и кнопка каталога.
    client.messages.responses.append(
        anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    )
    await h.message("ещё образ")
    assert "недоступен" in fake.texts()[-1]
    assert "m:catalog" in buttons(fake.last_markup())


async def test_admin_crud_flows(harness: Harness):
    h, fake = harness, harness.session
    a = {"user_id": ADMIN_ID}

    # Категория
    await h.click(AdminCB(s="cat", a="new"), **a)
    await h.message("🧦 Носки", **a)
    async with h.app.session_factory() as s:
        category = await s.scalar(select(Category).where(Category.title == "Носки"))
        assert category.emoji == "🧦" and category.slug == "noski"

    # Товар: категория → поля → фото → варианты
    await h.click(AdminCB(s="prod", a="newcat", id=category.id), **a)
    await h.message("Носки высокие", **a)
    await h.message("Хлопковые носки", **a)
    await h.message("80% хлопок", **a)
    await h.click(AdminCB(s="prod", a="gender", v="unisex"), **a)
    await h.click(AdminCB(s="prod", a="style", v="casual"), **a)
    await h.message("abc", **a)
    assert "Некорректное" in fake.texts()[-1]
    await h.message("590", **a)
    await h.message("-", **a)
    await h.message(
        photo=[PhotoSize(file_id="photo1", file_unique_id="u1", width=10, height=10)], **a
    )
    await h.click(AdminCB(s="prod", a="photos_done"), **a)
    await h.message("M чёрный 10\nL белый 0", **a)
    async with h.app.session_factory() as s:
        product = await s.scalar(select(Product).where(Product.title == "Носки высокие"))
        assert product.price == 590
    await h.click(AdminCB(s="prod", a="edit", id=product.id, v="price"), **a)
    await h.message("490", **a)
    async with h.app.session_factory() as s:
        product = await CatalogRepository(s).get_product(product.id)
        assert product.price == 490
        assert product.photos[0].file_id == "photo1"
        assert sorted((v.size, v.color, v.stock) for v in product.variants) == [
            ("L", "белый", 0),
            ("M", "чёрный", 10),
        ]
        assert "носки" in product.search_text

    # Промокод
    await h.click(AdminCB(s="promo", a="new"), **a)
    await h.message("autumn25", **a)
    await h.click(AdminCB(s="promo", a="kind", v="percent"), **a)
    await h.message("25", **a)
    await h.message("3000", **a)
    await h.message("31.12.2099", **a)
    await h.message("-", **a)
    async with h.app.session_factory() as s:
        promo = await s.scalar(select(PromoCode).where(PromoCode.code == "AUTUMN25"))
        assert promo.value == 25 and promo.min_total == 3000 and promo.max_uses is None

    # Тариф доставки
    async with h.app.session_factory() as s:
        tariff = await s.scalar(select(DeliveryTariff).where(DeliveryTariff.method == "courier"))
    await h.click(AdminCB(s="zone", a="tariff", id=tariff.zone_id, v="courier"), **a)
    await h.message("500 8000 1 3", **a)
    async with h.app.session_factory() as s:
        tariff = await s.get(DeliveryTariff, tariff.id)
        assert (tariff.price, tariff.free_from, tariff.days_max) == (500, 8000, 3)

    # Рассылка с предпросмотром и отложенной отправкой
    await h.click(AdminCB(s="bc"), **a)
    await h.click(AdminCB(s="bc", a="seg", v="all"), **a)
    await h.message("<b>Скидки</b> недели!", **a)
    await h.message(str(product.id), **a)
    assert "Получателей" in fake.texts()[-1]
    await h.click(AdminCB(s="bc", a="schedule"), **a)
    await h.message("01.01.2099 10:00", **a)
    async with h.app.session_factory() as s:
        broadcast = await s.scalar(select(Broadcast))
        assert broadcast.status == "scheduled" and broadcast.product_id == product.id

    # Удаление товара
    await h.click(AdminCB(s="prod", a="delete_yes", id=product.id), **a)
    async with h.app.session_factory() as s:
        assert await s.get(Product, product.id) is None

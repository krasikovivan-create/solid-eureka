"""ИИ-стилист с замоканным клиентом Anthropic: инструменты, лимиты, ошибки, отказы."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.db.models import (
    Favorite,
    StylistLook,
    StylistMessage,
    StylistRequest,
    User,
)
from app.services.cart import CartService
from app.services.stylist import (
    TOOLS,
    StylistDisabled,
    StylistLimitReached,
    StylistService,
    StylistUnavailable,
    Usage,
    estimate_cost,
    load_system_prompt,
)


# ---------- Заготовки ответов API ----------
def usage(inp=100, out=50, cache_read=0, cache_write=0):
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )


def tool_use(name: str, args: dict[str, Any], block_id: str = "tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=args, id=block_id)


def text(value: str):
    return SimpleNamespace(type="text", text=value)


def response(*blocks, stop_reason: str | None = None, **usage_kwargs):
    if stop_reason is None:
        stop_reason = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(
        content=list(blocks), stop_reason=stop_reason, usage=usage(**usage_kwargs)
    )


class FakeMessages:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs):
        # Копия messages: сервис дописывает в список после вызова.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self.messages = FakeMessages(responses)
        self.beta = SimpleNamespace(messages=self.messages)


def settings(**overrides) -> Settings:
    base = {
        "bot_token": "1:x",
        "anthropic_api_key": "test-key",
        "stylist_model": "claude-haiku-4-5-20251001",
        "stylist_daily_limit": 3,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def service(session, client, **overrides) -> StylistService:
    return StylistService(session, client, settings(**overrides))


def request_obj() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


# ---------- Тесты ----------
async def test_tool_calls_and_looks(session, user, catalog):
    tee, hoodie = catalog["tee"], catalog["hoodie"]
    client = FakeClient(
        [
            response(tool_use("search_products", {"category": "футболки", "size": "M"}, "tu_1")),
            response(tool_use("search_products", {"category": "Худи"}, "tu_2")),
            response(
                tool_use(
                    "present_looks",
                    {
                        "intro": "Вот что я подобрал",
                        "budget": 10000,
                        "looks": [
                            {
                                "title": "Спортивный кэжуал",
                                "explanation": "Базовая футболка под худи.",
                                "items": [
                                    {"product_id": tee.id, "size": "M", "color": "чёрный"},
                                    {"product_id": hoodie.id},
                                ],
                            }
                        ],
                    },
                    "tu_3",
                ),
                cache_read=900,
            ),
        ]
    )
    reply = await service(session, client).ask(user, "Образ на каждый день, размер M")

    assert reply.text == "Вот что я подобрал"
    assert len(reply.looks) == 1
    look = reply.looks[0]
    assert [i.product_id for i in look.items] == [tee.id, hoodie.id]
    # Цены берутся из БД, а не от модели.
    assert look.total == tee.price + hoodie.price
    # Размер M чёрного цвета однозначен → вариант выбран; у худи единственный вариант.
    assert look.items[0].variant_id == catalog["tee_m_black"].id
    assert look.items[1].variant_id == catalog["hoodie_l"].id

    # Результаты инструментов уходят модели как tool_result с JSON.
    second_call = client.messages.calls[1]["messages"]
    tool_result = second_call[-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "tu_1"
    found = json.loads(tool_result["content"])["products"]
    assert {p["product_id"] for p in found} == {tee.id, catalog["tee2"].id}

    # Prompt caching: системный промт и описания инструментов помечены cache_control.
    first = client.messages.calls[0]
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert first["cache_control"] == {"type": "ephemeral"}
    assert first["model"] == "claude-haiku-4-5-20251001"

    request = await session.scalar(select(StylistRequest))
    assert request.status == "ok"
    assert request.api_calls == 3
    assert request.input_tokens == 300 and request.output_tokens == 150
    assert request.cache_read_tokens == 900
    assert request.cost_usd > 0
    assert await session.scalar(select(func.count(StylistLook.id))) == 1
    roles = [m.role for m in (await session.scalars(select(StylistMessage))).all()]
    assert roles == ["user", "assistant"]


async def test_out_of_stock_items_are_not_returned(session, user, catalog):
    client = FakeClient(
        [
            response(tool_use("search_products", {"color": "белый", "size": "M"})),
            response(text("Нашёл варианты")),
        ]
    )
    await service(session, client).ask(user, "белая футболка M")
    result = json.loads(client.messages.calls[1]["messages"][-1]["content"][0]["content"])
    ids = {p["product_id"] for p in result["products"]}
    # У базовой футболки белый M закончился, у оверсайз — в наличии.
    assert ids == {catalog["tee2"].id}


async def test_hallucinated_product_is_rejected_and_model_retries(session, user, catalog):
    tee = catalog["tee"]
    client = FakeClient(
        [
            response(
                tool_use(
                    "present_looks",
                    {
                        "intro": "Образ",
                        "looks": [
                            {"title": "X", "explanation": "y", "items": [{"product_id": 9999}]}
                        ],
                    },
                    "tu_bad",
                )
            ),
            response(tool_use("get_product", {"product_id": tee.id}, "tu_get")),
            response(
                tool_use(
                    "present_looks",
                    {
                        "intro": "Исправил",
                        "looks": [
                            {
                                "title": "База",
                                "explanation": "ok",
                                "items": [{"product_id": tee.id}],
                            }
                        ],
                    },
                    "tu_ok",
                )
            ),
        ]
    )
    reply = await service(session, client).ask(user, "что-нибудь")
    error_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert error_result["is_error"] is True
    assert "9999" in error_result["content"]
    assert reply.text == "Исправил"
    assert reply.looks[0].items[0].product_id == tee.id
    # Размер не указан, вариантов несколько → покупатель выберет размер сам.
    assert reply.looks[0].items[0].variant_id is None


async def test_look_over_budget_is_dropped(session, user, catalog):
    tee, hoodie = catalog["tee"], catalog["hoodie"]
    looks = {
        "intro": "Два образа",
        "budget": 3000,
        "looks": [
            {"title": "Дорогой", "explanation": "", "items": [{"product_id": hoodie.id}]},
            {"title": "В бюджете", "explanation": "", "items": [{"product_id": tee.id}]},
        ],
    }
    client = FakeClient(
        [
            response(tool_use("search_products", {}, "tu_1")),
            response(tool_use("present_looks", looks, "tu_2")),
        ]
    )
    reply = await service(session, client).ask(user, "бюджет 3000")
    assert [look.title for look in reply.looks] == ["В бюджете"]


async def test_clarifying_question_and_offtopic_text(session, user, catalog):
    client = FakeClient([response(text("Подскажите ваш размер?"))])
    reply = await service(session, client).ask(user, "хочу образ")
    assert reply.text == "Подскажите ваш размер?"
    assert reply.looks == []

    client = FakeClient([response(text("Я помогаю только с одеждой и стилем. Подобрать образ?"))])
    reply = await service(session, client).ask(user, "Реши мне задачу по физике")
    assert "одеждой" in reply.text
    assert reply.looks == []


async def test_refusal_stop_reason(session, user, catalog):
    client = FakeClient([response(stop_reason="refusal")])
    reply = await service(session, client).ask(user, "запрещённое")
    assert reply.refused
    request = await session.scalar(select(StylistRequest))
    assert request.status == "refusal"


async def test_daily_limit(session, user, catalog):
    for _ in range(3):
        session.add(StylistRequest(user_id=user.id, model="m", status="ok"))
    session.add(StylistRequest(user_id=user.id, model="m", status="error"))  # ошибки не в счёт
    await session.commit()
    client = FakeClient([])
    stylist = service(session, client)
    assert await stylist.left_today(user.id) == 0
    with pytest.raises(StylistLimitReached):
        await stylist.ask(user, "образ")
    assert client.messages.calls == []


@pytest.mark.parametrize(
    "error",
    [
        anthropic.APIConnectionError(request=request_obj()),
        anthropic.APITimeoutError(request=request_obj()),
        anthropic.InternalServerError(
            "overloaded",
            response=httpx2.Response(529, request=request_obj()),
            body=None,
        ),
    ],
)
async def test_api_errors_become_unavailable(session, user, catalog, error):
    client = FakeClient([error])
    with pytest.raises(StylistUnavailable):
        await service(session, client).ask(user, "образ")
    request = await session.scalar(select(StylistRequest))
    assert request.status == "error"
    assert request.error
    # Ошибки не расходуют дневной лимит покупателя.
    assert await service(session, client).left_today(user.id) == 3


async def test_disabled_without_client(session, user):
    with pytest.raises(StylistDisabled):
        await StylistService(session, None, settings()).ask(user, "образ")
    with pytest.raises(StylistDisabled):
        await service(session, FakeClient([]), stylist_enabled=False).ask(user, "образ")


async def test_user_history_never_leaks_other_users(session, user, catalog):
    stranger = User(id=5555, full_name="Чужой")
    session.add(stranger)
    await session.flush()
    session.add(Favorite(user_id=stranger.id, product_id=catalog["hoodie"].id, last_price=1))
    session.add(Favorite(user_id=user.id, product_id=catalog["tee"].id, last_price=1))
    await session.commit()
    client = FakeClient(
        [
            response(tool_use("get_user_history", {"user_id": stranger.id})),
            response(text("ок")),
        ]
    )
    await service(session, client).ask(user, "что я покупал?")
    result = json.loads(client.messages.calls[1]["messages"][-1]["content"][0]["content"])
    assert [f["product_id"] for f in result["favorites"]] == [catalog["tee"].id]


async def test_history_is_kept_limited_and_reset(session, user, catalog):
    stylist = service(session, FakeClient([]), stylist_daily_limit=100, stylist_history_size=4)
    for i in range(4):
        stylist.client = FakeClient([response(text(f"ответ {i}"))])
        await stylist.ask(user, f"вопрос {i}")
    stylist.client = FakeClient([response(text("финал"))])
    await stylist.ask(user, "последний")
    sent = stylist.client.messages.calls[0]["messages"]
    assert len(sent) == 5  # 4 сообщения истории + новый вопрос
    assert sent[0] == {"role": "user", "content": "вопрос 2"}
    assert sent[-1]["content"] == "последний"

    await stylist.reset(user.id)
    stylist.client = FakeClient([response(text("заново"))])
    await stylist.ask(user, "новая тема")
    assert len(stylist.client.messages.calls[0]["messages"]) == 1


async def test_photo_is_sent_as_image_block(session, user, catalog):
    client = FakeClient([response(text("Похоже на худи"))])
    await service(session, client).ask(user, "найди похожее", image=(b"\xff\xd8jpeg", "image/jpeg"))
    content = client.messages.calls[0]["messages"][-1]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert content[1] == {"type": "text", "text": "найди похожее"}
    stored = await session.scalar(select(StylistMessage).where(StylistMessage.role == "user"))
    assert stored.content.startswith("[Покупатель прислал фото]")


async def test_sonnet_uses_server_side_fallback(session, user, catalog):
    client = FakeClient([response(text("ok"))])
    await service(session, client, stylist_model="claude-sonnet-5-5").ask(user, "образ")
    call = client.messages.calls[0]
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]


async def test_look_can_be_added_to_cart_and_tracked(session, user, catalog):
    tee = catalog["tee"]
    client = FakeClient(
        [
            response(tool_use("get_product", {"product_id": tee.id}, "tu_1")),
            response(
                tool_use(
                    "present_looks",
                    {
                        "intro": "",
                        "looks": [
                            {
                                "title": "База",
                                "explanation": "",
                                "items": [{"product_id": tee.id, "size": "S"}],
                            }
                        ],
                    },
                    "tu_2",
                )
            ),
        ]
    )
    stylist = service(session, client)
    reply = await stylist.ask(user, "образ")
    look = await stylist.get_look(reply.looks[0].id, user.id)
    assert await stylist.get_look(look.id, 999) is None
    item = look.items[0]
    await CartService(session).add(user.id, item["variant_id"], 1, look_id=look.id)
    await stylist.mark_look_added(look)
    summary = await CartService(session).summary(user)
    assert summary.lines[0].look_id == look.id
    assert look.added_to_cart_at is not None


def test_cost_estimate_and_prompt():
    u = Usage(calls=1, input_tokens=1_000_000, output_tokens=1_000_000, cache_read=1_000_000)
    # Haiku 4.5: $1 вход + $5 выход + $0.1 чтение кэша.
    assert estimate_cost("claude-haiku-4-5-20251001", u) == pytest.approx(6.1)
    assert estimate_cost("claude-sonnet-5-5", Usage(output_tokens=1_000_000)) == pytest.approx(10)
    prompt = load_system_prompt()
    assert "ТОЛЬКО" in prompt.upper() and "инструмент" in prompt
    assert [tool["name"] for tool in TOOLS] == [
        "search_products",
        "get_product",
        "get_user_history",
        "present_looks",
    ]

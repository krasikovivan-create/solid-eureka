"""ИИ-стилист на Claude API: подбор образов только из товаров каталога через tool use.

Весь код стилиста — в этом модуле. Отключается флагом STYLIST_ENABLED=false
(или отсутствием ANTHROPIC_API_KEY): кнопка пропадает из меню, сервис не вызывается.
"""

from __future__ import annotations

import base64
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import anthropic
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.constants import Gender, Style, size_sort_key
from app.db.base import utcnow
from app.db.models import (
    Category,
    Favorite,
    Order,
    OrderItem,
    Product,
    StylistLook,
    StylistMessage,
    StylistRequest,
    StylistSession,
    User,
)
from app.repositories.catalog import CatalogRepository, ProductFilter

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "stylist.md"
MAX_TOOL_ITERATIONS = 8
MAX_LOOKS = 3
MAX_ITEMS_PER_LOOK = 8
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Цены моделей, $ за 1M токенов (вход, выход). Запись в кэш — ×1.25 входа, чтение — ×0.1.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
}
# Модели, для которых включаем серверный фолбэк при отказе классификатора безопасности.
FALLBACK_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5")


class StylistError(Exception):
    pass


class StylistDisabled(StylistError):
    pass


class StylistLimitReached(StylistError):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"limit={limit}")


class StylistUnavailable(StylistError):
    """API недоступно (таймаут, сеть, перегрузка, ошибка ответа)."""


@dataclass(slots=True)
class LookItem:
    product_id: int
    title: str
    price: int
    size: str | None = None
    color: str | None = None
    variant_id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "title": self.title,
            "price": self.price,
            "size": self.size,
            "color": self.color,
            "variant_id": self.variant_id,
        }


@dataclass(slots=True)
class Look:
    id: int
    title: str
    explanation: str
    items: list[LookItem]

    @property
    def total(self) -> int:
        return sum(item.price for item in self.items)


@dataclass(slots=True)
class StylistReply:
    text: str
    looks: list[Look] = field(default_factory=list)
    refused: bool = False


@dataclass(slots=True)
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation: int = 0
    cache_read: int = 0

    def add(self, usage: Any) -> None:
        self.calls += 1
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_creation += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0


def model_prices(model: str) -> tuple[float, float]:
    for prefix in sorted(MODEL_PRICES, key=len, reverse=True):
        if model.startswith(prefix):
            return MODEL_PRICES[prefix]
    return MODEL_PRICES["claude-sonnet-5-5"]


def estimate_cost(model: str, usage: Usage) -> float:
    price_in, price_out = model_prices(model)
    return (
        usage.input_tokens * price_in
        + usage.cache_creation * price_in * 1.25
        + usage.cache_read * price_in * 0.1
        + usage.output_tokens * price_out
    ) / 1_000_000


@lru_cache
def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def _norm(value: str) -> str:
    return value.lower().replace("ё", "е").strip()


# Описания инструментов неизменны между запросами — это важно для prompt caching.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_products",
        "description": (
            "Поиск товаров магазина, которые есть в наличии. Возвращает до limit товаров с id, "
            "названием, категорией, полом, стилем, ценой, цветами и размерами в наличии. "
            "Все параметры необязательны; чем меньше фильтров, тем шире выдача. Категории "
            "магазина: футболки, худи, штаны, куртки, обувь, аксессуары."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "Категория: футболки, худи, штаны, куртки, обувь или аксессуары."
                    ),
                },
                "gender": {
                    "type": "string",
                    "enum": [g.value for g in Gender],
                    "description": "Пол. male и female включают унисекс-товары.",
                },
                "size": {
                    "type": "string",
                    "description": "Размер одежды (XS, S, M, L, XL, XXL) или обуви (36–45).",
                },
                "color": {
                    "type": "string",
                    "description": "Цвет по-русски, например «чёрный», «белый», «синий».",
                },
                "style": {
                    "type": "string",
                    "enum": [s.value for s in Style],
                    "description": "Стиль: casual, street, sport или classic.",
                },
                "max_price": {"type": "integer", "description": "Максимальная цена в рублях."},
                "min_price": {"type": "integer", "description": "Минимальная цена в рублях."},
                "query": {
                    "type": "string",
                    "description": "Ключевые слова из названия, например «джинсы» или «кожаная».",
                },
                "limit": {
                    "type": "integer",
                    "description": "Сколько товаров вернуть (1–15, по умолчанию 8).",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_product",
        "description": (
            "Подробности о товаре по id: описание, состав, цена, размеры и цвета в наличии "
            "с остатками."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "integer", "description": "id товара."}},
            "required": ["product_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_user_history",
        "description": (
            "Прошлые покупки и избранное текущего покупателя, а также его обычный размер. "
            "Всегда возвращает данные покупателя, с которым идёт диалог; user_id передавать "
            "не нужно."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "Необязателен и игнорируется: используется текущий покупатель.",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "present_looks",
        "description": (
            "Показать покупателю готовые образы — это финальный ответ. Используй только "
            "product_id из результатов search_products и get_product. Для капсульного "
            "гардероба передай один образ с 5–8 вещами."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intro": {
                    "type": "string",
                    "description": "Короткая вводная фраза для покупателя (1–2 предложения).",
                },
                "budget": {
                    "type": "integer",
                    "description": "Бюджет покупателя на один образ в рублях, если он его назвал.",
                },
                "looks": {
                    "type": "array",
                    "maxItems": MAX_LOOKS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Название образа."},
                            "explanation": {
                                "type": "string",
                                "description": "Почему вещи сочетаются, 1–2 предложения.",
                            },
                            "items": {
                                "type": "array",
                                "maxItems": MAX_ITEMS_PER_LOOK,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "product_id": {"type": "integer"},
                                        "size": {"type": "string"},
                                        "color": {"type": "string"},
                                    },
                                    "required": ["product_id"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["title", "explanation", "items"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["intro", "looks"],
            "additionalProperties": False,
        },
        # Точка кэширования: описания всех инструментов кэшируются вместе с системным промтом.
        "cache_control": {"type": "ephemeral"},
    },
]


def build_client(settings: Settings) -> anthropic.AsyncAnthropic | None:
    if not settings.stylist_available:
        return None
    return anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        timeout=settings.stylist_timeout,
        max_retries=settings.stylist_max_retries,
    )


class StylistService:
    def __init__(
        self,
        session: AsyncSession,
        client: anthropic.AsyncAnthropic | None,
        settings: Settings,
        system_prompt: str | None = None,
    ) -> None:
        self.session = session
        self.client = client
        self.settings = settings
        self.system_prompt = system_prompt or load_system_prompt()
        self.catalog = CatalogRepository(session)

    @property
    def enabled(self) -> bool:
        return self.client is not None and self.settings.stylist_enabled

    # ---------- Лимиты ----------
    def _day_start_utc(self) -> datetime:
        tz = ZoneInfo(self.settings.timezone)
        local_midnight = datetime.combine(datetime.now(tz).date(), time.min, tzinfo=tz)
        return local_midnight.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    async def used_today(self, user_id: int) -> int:
        stmt = select(func.count(StylistRequest.id)).where(
            StylistRequest.user_id == user_id,
            StylistRequest.created_at >= self._day_start_utc(),
            StylistRequest.status.in_(("ok", "refusal")),
        )
        return int(await self.session.scalar(stmt) or 0)

    async def left_today(self, user_id: int) -> int:
        return max(0, self.settings.stylist_daily_limit - await self.used_today(user_id))

    # ---------- Сессия диалога ----------
    async def _active_session(self, user_id: int) -> StylistSession:
        stmt = (
            select(StylistSession)
            .where(StylistSession.user_id == user_id, StylistSession.is_active.is_(True))
            .order_by(StylistSession.id.desc())
        )
        current = await self.session.scalar(stmt)
        if current is None:
            current = StylistSession(user_id=user_id)
            self.session.add(current)
            await self.session.flush()
        return current

    async def reset(self, user_id: int) -> None:
        await self.session.execute(
            update(StylistSession)
            .where(StylistSession.user_id == user_id, StylistSession.is_active.is_(True))
            .values(is_active=False)
        )

    async def _history(self, session_id: int) -> list[dict[str, Any]]:
        stmt = (
            select(StylistMessage)
            .where(StylistMessage.session_id == session_id)
            .order_by(StylistMessage.id.desc())
            .limit(self.settings.stylist_history_size)
        )
        rows = list(reversed((await self.session.scalars(stmt)).all()))
        while rows and rows[0].role != "user":
            rows.pop(0)
        return [{"role": row.role, "content": row.content} for row in rows]

    # ---------- Инструменты ----------
    async def _resolve_category(self, value: str | None) -> Category | None:
        if not value:
            return None
        needle = _norm(value)
        for category in await self.catalog.categories():
            if needle in (_norm(category.slug), _norm(category.title)) or needle in _norm(
                category.title
            ):
                return category
        return None

    @staticmethod
    def _variants_in_stock(product: Product, size: str | None = None, color: str | None = None):
        variants = [v for v in product.variants if v.stock > 0]
        if size:
            variants = [v for v in variants if _norm(v.size) == _norm(size)]
        if color:
            variants = [v for v in variants if _norm(color) in _norm(v.color)]
        return variants

    async def tool_search_products(self, args: dict[str, Any], seen: set[int]) -> dict[str, Any]:
        category = await self._resolve_category(args.get("category"))
        if args.get("category") and category is None:
            titles = [c.title for c in await self.catalog.categories()]
            return {"products": [], "note": f"Категория не найдена. Доступные: {', '.join(titles)}"}
        limit = min(max(int(args.get("limit") or 8), 1), 15)
        flt = ProductFilter(
            category_id=category.id if category else None,
            gender=args.get("gender") if args.get("gender") in set(Gender) else None,
            style=args.get("style") if args.get("style") in set(Style) else None,
            size=args.get("size") or None,
            max_price=args.get("max_price"),
            min_price=args.get("min_price"),
            query=(args.get("query") or None),
            sort="new",
        )
        products = await self.catalog.list_products(flt, limit=60)
        color = args.get("color")
        result = []
        for product in products:
            variants = self._variants_in_stock(product, args.get("size"), color)
            if not variants:
                continue
            seen.add(product.id)
            result.append(
                {
                    "product_id": product.id,
                    "title": product.title,
                    "category": product.category.title,
                    "gender": product.gender,
                    "style": product.style,
                    "price": product.price,
                    "old_price": product.old_price,
                    "colors_in_stock": sorted({v.color for v in variants}),
                    "sizes_in_stock": sorted({v.size for v in variants}, key=size_sort_key),
                }
            )
            if len(result) >= limit:
                break
        if not result:
            return {"products": [], "note": "Ничего не найдено. Попробуйте ослабить фильтры."}
        return {"products": result}

    async def tool_get_product(self, args: dict[str, Any], seen: set[int]) -> dict[str, Any]:
        try:
            product_id = int(args.get("product_id"))
        except (TypeError, ValueError):
            return {"error": "Нужен целочисленный product_id"}
        product = await self.catalog.get_product(product_id)
        if product is None:
            return {"error": f"Товар {product_id} не найден или снят с продажи"}
        seen.add(product.id)
        return {
            "product_id": product.id,
            "title": product.title,
            "category": product.category.title,
            "description": product.description[:600],
            "composition": product.composition,
            "gender": product.gender,
            "style": product.style,
            "price": product.price,
            "old_price": product.old_price,
            "in_stock": [
                {"size": v.size, "color": v.color, "stock": v.stock}
                for v in sorted(product.variants, key=lambda v: size_sort_key(v.size))
                if v.stock > 0
            ],
        }

    async def tool_get_user_history(self, user_id: int) -> dict[str, Any]:
        purchases_stmt = (
            select(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.user_id == user_id, Order.status != "cancelled")
            .order_by(OrderItem.id.desc())
            .limit(15)
        )
        purchases = list((await self.session.scalars(purchases_stmt)).all())
        fav_stmt = (
            select(Favorite)
            .where(Favorite.user_id == user_id)
            .options(selectinload(Favorite.product))
            .order_by(Favorite.id.desc())
            .limit(10)
        )
        favorites = list((await self.session.scalars(fav_stmt)).all())
        sizes = Counter(item.size for item in purchases if item.size)
        return {
            "purchases": [
                {
                    "product_id": item.product_id,
                    "title": item.title,
                    "size": item.size,
                    "color": item.color,
                    "price": item.price,
                }
                for item in purchases
            ],
            "favorites": [
                {
                    "product_id": fav.product_id,
                    "title": fav.product.title,
                    "price": fav.product.price,
                }
                for fav in favorites
            ],
            "usual_size": sizes.most_common(1)[0][0] if sizes else None,
        }

    async def _run_tool(
        self, name: str, args: dict[str, Any], user_id: int, seen: set[int]
    ) -> dict[str, Any]:
        if name == "search_products":
            return await self.tool_search_products(args, seen)
        if name == "get_product":
            return await self.tool_get_product(args, seen)
        if name == "get_user_history":
            return await self.tool_get_user_history(user_id)
        return {"error": f"Неизвестный инструмент {name}"}

    # ---------- Сборка образов ----------
    async def _build_looks(
        self, args: dict[str, Any], seen: set[int], user_id: int, request_id: int | None
    ) -> tuple[list[Look], list[str]]:
        """Проверяет образы модели по БД. Возвращает образы и список замечаний для модели."""
        problems: list[str] = []
        budget = args.get("budget")
        budget = int(budget) if isinstance(budget, int | float) and budget > 0 else None
        raw_looks = args.get("looks") if isinstance(args.get("looks"), list) else []
        looks: list[Look] = []
        for raw in raw_looks[:MAX_LOOKS]:
            if not isinstance(raw, dict):
                continue
            items: list[LookItem] = []
            used: set[int] = set()
            raw_items = raw.get("items") if isinstance(raw.get("items"), list) else []
            for raw_item in raw_items[:MAX_ITEMS_PER_LOOK]:
                if not isinstance(raw_item, dict):
                    continue
                try:
                    product_id = int(raw_item.get("product_id"))
                except (TypeError, ValueError):
                    continue
                if product_id in used:
                    continue
                if product_id not in seen:
                    problems.append(f"Товар {product_id} не был получен через инструменты")
                    continue
                product = await self.catalog.get_product(product_id)
                if product is None or product.total_stock <= 0:
                    problems.append(f"Товара {product_id} нет в наличии")
                    continue
                size = raw_item.get("size") or None
                color = raw_item.get("color") or None
                # Вариант выбираем, только если он однозначен: иначе размер покупатель
                # выберет сам в карточке товара.
                variant = None
                if size:
                    matches = self._variants_in_stock(product, size, color) or (
                        self._variants_in_stock(product, size)
                    )
                    variant = matches[0] if matches else None
                else:
                    in_stock = self._variants_in_stock(product)
                    if len(in_stock) == 1:
                        variant = in_stock[0]
                used.add(product_id)
                items.append(
                    LookItem(
                        product_id=product.id,
                        title=product.title,
                        price=product.price,
                        size=variant.size if variant else size,
                        color=variant.color if variant else color,
                        variant_id=variant.id if variant else None,
                    )
                )
            if not items:
                continue
            look = Look(
                id=0,
                title=str(raw.get("title") or "Образ")[:120],
                explanation=str(raw.get("explanation") or "")[:600],
                items=items,
            )
            if budget and look.total > budget:
                problems.append(f"Образ «{look.title}» дороже бюджета {budget} ₽")
                continue
            looks.append(look)
        for look in looks:
            row = StylistLook(
                user_id=user_id,
                request_id=request_id,
                title=look.title,
                explanation=look.explanation,
                items=[item.as_dict() for item in look.items],
                total=look.total,
            )
            self.session.add(row)
            await self.session.flush()
            look.id = row.id
        return looks, problems

    # ---------- Вызов модели ----------
    async def _call(self, messages: list[dict[str, Any]]):
        kwargs: dict[str, Any] = {
            "model": self.settings.stylist_model,
            "max_tokens": self.settings.stylist_max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": self.system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "tools": TOOLS,
            "messages": messages,
        }
        if self.settings.stylist_model.startswith(FALLBACK_MODELS):
            return await self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        return await self.client.messages.create(**kwargs)

    @staticmethod
    def _user_content(text: str, image: tuple[bytes, str] | None) -> str | list[dict[str, Any]]:
        if image is None:
            return text
        data, media_type = image
        return [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(data).decode("ascii"),
                },
            },
            {"type": "text", "text": text},
        ]

    @staticmethod
    def _history_summary(reply: StylistReply) -> str:
        if not reply.looks:
            return reply.text
        parts = [reply.text]
        for look in reply.looks:
            items = ", ".join(f"#{i.product_id} {i.title} ({i.price} ₽)" for i in look.items)
            parts.append(f"Образ «{look.title}»: {items}. Итого {look.total} ₽.")
        return "\n".join(parts)

    async def ask(
        self,
        user: User,
        text: str,
        image: tuple[bytes, str] | None = None,
        mode: str = "chat",
    ) -> StylistReply:
        if not self.enabled:
            raise StylistDisabled
        if image is not None and len(image[0]) > MAX_IMAGE_BYTES:
            raise ValueError("image too large")
        if await self.used_today(user.id) >= self.settings.stylist_daily_limit:
            raise StylistLimitReached(self.settings.stylist_daily_limit)

        dialog = await self._active_session(user.id)
        history = await self._history(dialog.id)
        messages: list[dict[str, Any]] = [
            *history,
            {"role": "user", "content": self._user_content(text, image)},
        ]
        request = StylistRequest(user_id=user.id, model=self.settings.stylist_model, mode=mode)
        self.session.add(request)
        await self.session.flush()

        usage = Usage()
        seen: set[int] = set()
        reply: StylistReply | None = None
        try:
            for _ in range(MAX_TOOL_ITERATIONS):
                response = await self._call(messages)
                usage.add(response.usage)
                if response.stop_reason == "refusal":
                    reply = StylistReply(text="", refused=True)
                    break
                tool_uses = [b for b in response.content if b.type == "tool_use"]
                final = next((b for b in tool_uses if b.name == "present_looks"), None)
                if final is not None:
                    args = final.input if isinstance(final.input, dict) else {}
                    looks, problems = await self._build_looks(args, seen, user.id, request.id)
                    if looks:
                        reply = StylistReply(text=str(args.get("intro") or "").strip(), looks=looks)
                        break
                    # Все образы отклонены — сообщаем модели причину и даём исправиться.
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": final.id,
                                    "is_error": True,
                                    "content": "Образы отклонены: "
                                    + "; ".join(problems or ["пустые образы"])
                                    + ". Найди товары через search_products и попробуй снова.",
                                },
                                *[
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": b.id,
                                        "content": "{}",
                                    }
                                    for b in tool_uses
                                    if b is not final
                                ],
                            ],
                        }
                    )
                    continue
                if not tool_uses:
                    text_out = "\n".join(b.text for b in response.content if b.type == "text")
                    reply = StylistReply(text=text_out.strip())
                    break
                messages.append({"role": "assistant", "content": response.content})
                results = []
                for block in tool_uses:
                    args = block.input if isinstance(block.input, dict) else {}
                    try:
                        output = await self._run_tool(block.name, args, user.id, seen)
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(output, ensure_ascii=False),
                            }
                        )
                    except Exception as exc:  # ошибка инструмента не должна ронять диалог
                        logger.exception("Ошибка инструмента %s", block.name)
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "is_error": True,
                                "content": f"Ошибка: {type(exc).__name__}",
                            }
                        )
                messages.append({"role": "user", "content": results})
        except anthropic.APITimeoutError as exc:
            await self._fail(request, usage, "timeout", exc)
        except anthropic.RateLimitError as exc:
            await self._fail(request, usage, "rate_limit", exc)
        except anthropic.APIConnectionError as exc:
            await self._fail(request, usage, "connection", exc)
        except anthropic.APIStatusError as exc:
            await self._fail(request, usage, f"status_{exc.status_code}", exc)

        if reply is None:
            reply = StylistReply(text="")
        request.status = "refusal" if reply.refused else "ok"
        self._account(request, usage)

        user_record = text if image is None else f"[Покупатель прислал фото] {text}"
        self.session.add(StylistMessage(session_id=dialog.id, role="user", content=user_record))
        summary = self._history_summary(reply) if not reply.refused else "Отказ: тема вне подбора."
        if summary:
            self.session.add(
                StylistMessage(session_id=dialog.id, role="assistant", content=summary)
            )
        await self.session.commit()
        return reply

    def _account(self, request: StylistRequest, usage: Usage) -> None:
        request.api_calls = usage.calls
        request.input_tokens = usage.input_tokens
        request.output_tokens = usage.output_tokens
        request.cache_creation_tokens = usage.cache_creation
        request.cache_read_tokens = usage.cache_read
        request.cost_usd = round(estimate_cost(request.model, usage), 6)

    async def _fail(
        self, request: StylistRequest, usage: Usage, reason: str, exc: Exception
    ) -> None:
        logger.warning("Claude API недоступен (%s): %s", reason, exc)
        request.status = "error"
        request.error = f"{reason}: {exc}"[:500]
        self._account(request, usage)
        await self.session.commit()
        raise StylistUnavailable(reason) from exc

    # ---------- Образы → корзина ----------
    async def get_look(self, look_id: int, user_id: int) -> StylistLook | None:
        look = await self.session.get(StylistLook, look_id)
        if look is None or look.user_id != user_id:
            return None
        return look

    async def mark_look_added(self, look: StylistLook) -> None:
        if look.added_to_cart_at is None:
            look.added_to_cart_at = utcnow()

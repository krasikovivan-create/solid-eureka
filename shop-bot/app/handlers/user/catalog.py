"""Каталог: категории, фильтры, сортировка, карточка товара, поиск, избранное, подборки."""

from __future__ import annotations

import math
from typing import Any

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, User
from app.keyboards.callbacks import CartCB, CatCB, MenuCB, ProdCB
from app.keyboards.user import (
    cancel_kb,
    categories_kb,
    filter_values_kb,
    filters_kb,
    product_card_kb,
    product_list_kb,
    products_kb,
    sort_kb,
)
from app.repositories.catalog import CatalogRepository, ProductFilter
from app.services.cart import CartService, NotEnoughStock, VariantUnavailable
from app.services.favorites import FavoriteService
from app.services.recommendations import RecommendationService
from app.states import SearchStates
from app.texts import labels, t
from app.utils.formatting import gender_label, h, price_line, style_label
from app.utils.telegram import render, safe_delete, send_product_photos

router = Router(name="catalog")
PAGE_SIZE = 6


# ---------- Контекст списка (куда возвращаться из карточки) ----------
async def _set_ctx(state: FSMContext, message: Message | None, **ctx: Any) -> None:
    ctx["msg"] = message.message_id if message else None
    await state.update_data(ctx=ctx)


async def _filters(state: FSMContext, cat: int) -> dict[str, str]:
    data = await state.get_data()
    flt = data.get("flt") or {}
    if flt.get("cat") != cat:
        flt = {"cat": cat, "sort": flt.get("sort", "new")}
        await state.update_data(flt=flt)
    return flt


def _filters_label(flt: dict[str, str]) -> str:
    parts = []
    if flt.get("size"):
        parts.append(flt["size"])
    if flt.get("color"):
        parts.append(flt["color"])
    if flt.get("price"):
        parts.append(t(f"price.{flt['price']}"))
    if flt.get("gender"):
        parts.append(labels("gender").get(flt["gender"], ""))
    return t("catalog.filters_active", filters=", ".join(parts)) if parts else ""


# ---------- Категории и списки ----------
@router.callback_query(MenuCB.filter(F.a == "catalog"))
@router.callback_query(CatCB.filter(F.a == "cats"))
async def show_categories(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await state.set_state(None)
    categories = await CatalogRepository(session).categories()
    text = t("catalog.title") if categories else t("catalog.empty_categories")
    await render(callback, text, categories_kb(categories))
    await callback.answer()


async def show_category(
    event: CallbackQuery | Message,
    state: FSMContext,
    session: AsyncSession,
    cat_id: int,
    page: int = 0,
) -> None:
    repo = CatalogRepository(session)
    category = await repo.get_category(cat_id)
    if category is None:
        await render(event, t("common.not_found"), categories_kb(await repo.categories()))
        return
    flt = await _filters(state, cat_id)
    product_filter = ProductFilter(
        category_id=cat_id,
        size=flt.get("size") or None,
        color=flt.get("color") or None,
        price_key=flt.get("price") or None,
        gender=flt.get("gender") or None,
        sort=flt.get("sort", "new"),
    )
    total = await repo.count_products(product_filter)
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    products = await repo.list_products(product_filter, page * PAGE_SIZE, PAGE_SIZE)
    text = t(
        "catalog.list_title",
        category=h(category.label),
        count=total,
        filters=_filters_label(flt),
    )
    if not products:
        text += "\n\n" + t("catalog.empty")
    sent = await render(
        event, text, product_list_kb(products, cat_id, page, pages, product_filter.sort)
    )
    await _set_ctx(state, sent, kind="cat", cat=cat_id, page=page)


@router.callback_query(CatCB.filter(F.a == "list"))
async def cb_category(
    callback: CallbackQuery, callback_data: CatCB, state: FSMContext, session: AsyncSession
) -> None:
    await state.set_state(None)
    await show_category(callback, state, session, callback_data.cat, callback_data.page)
    await callback.answer()


@router.callback_query(CatCB.filter(F.a == "flt"))
async def cb_filters(callback: CallbackQuery, callback_data: CatCB, state: FSMContext) -> None:
    flt = await _filters(state, callback_data.cat)
    any_ = t("catalog.any")
    text = t(
        "catalog.filters_title",
        size=h(flt.get("size") or any_),
        color=h(flt.get("color") or any_),
        price=t(f"price.{flt['price']}") if flt.get("price") else any_,
        gender=gender_label(flt["gender"]) if flt.get("gender") else any_,
    )
    await render(callback, text, filters_kb(callback_data.cat))
    await callback.answer()


@router.callback_query(CatCB.filter(F.a == "fk"))
async def cb_filter_key(
    callback: CallbackQuery, callback_data: CatCB, session: AsyncSession
) -> None:
    repo = CatalogRepository(session)
    values: list[str] = []
    if callback_data.k == "size":
        values = await repo.available_sizes(callback_data.cat)
    elif callback_data.k == "color":
        values = await repo.available_colors(callback_data.cat)
    await render(
        callback,
        t("catalog.choose_value"),
        filter_values_kb(callback_data.cat, callback_data.k, values),
    )
    await callback.answer()


@router.callback_query(CatCB.filter(F.a == "fv"))
async def cb_filter_value(
    callback: CallbackQuery, callback_data: CatCB, state: FSMContext, session: AsyncSession
) -> None:
    if callback_data.k not in {"size", "color", "price", "gender"}:
        await callback.answer()
        return
    flt = await _filters(state, callback_data.cat)
    flt[callback_data.k] = callback_data.v
    await state.update_data(flt=flt)
    await show_category(callback, state, session, callback_data.cat)
    await callback.answer()


@router.callback_query(CatCB.filter(F.a == "reset"))
async def cb_filter_reset(
    callback: CallbackQuery, callback_data: CatCB, state: FSMContext, session: AsyncSession
) -> None:
    flt = await _filters(state, callback_data.cat)
    await state.update_data(flt={"cat": callback_data.cat, "sort": flt.get("sort", "new")})
    await show_category(callback, state, session, callback_data.cat)
    await callback.answer()


@router.callback_query(CatCB.filter(F.a == "sort"))
async def cb_sort(callback: CallbackQuery, callback_data: CatCB, state: FSMContext) -> None:
    flt = await _filters(state, callback_data.cat)
    await render(
        callback, t("catalog.sort_title"), sort_kb(callback_data.cat, flt.get("sort", "new"))
    )
    await callback.answer()


@router.callback_query(CatCB.filter(F.a == "sv"))
async def cb_sort_value(
    callback: CallbackQuery, callback_data: CatCB, state: FSMContext, session: AsyncSession
) -> None:
    flt = await _filters(state, callback_data.cat)
    if callback_data.v in {"new", "cheap", "expensive", "discount"}:
        flt["sort"] = callback_data.v
        await state.update_data(flt=flt)
    await show_category(callback, state, session, callback_data.cat)
    await callback.answer()


@router.callback_query(CartCB.filter(F.a == "noop"))
@router.callback_query(ProdCB.filter(F.a == "noop"))
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


# ---------- Карточка товара ----------
def card_text(product: Product, variant_id: int, color_idx: int) -> str:
    stock = product.total_stock
    if stock <= 0:
        stock_text = t("product.out_of_stock")
    elif stock <= 3:
        stock_text = t("product.low_stock", count=stock)
    else:
        stock_text = t("product.in_stock", count=stock)
    text = t(
        "product.card",
        title=h(product.title),
        price=price_line(product.price, product.old_price),
        description=h(product.description),
        composition=h(product.composition or "—"),
        gender=gender_label(product.gender),
        style=style_label(product.style),
        colors=h(", ".join(product.colors) or "—"),
        stock=stock_text,
    )
    variant = next((v for v in product.variants if v.id == variant_id), None)
    if variant is not None:
        text += t(
            "product.selected", size=h(variant.size), color=h(variant.color), stock=variant.stock
        )
    elif stock > 0:
        many_colors = len(product.colors) > 1 and color_idx < 0
        text += t("product.choose_color") if many_colors else t("product.choose_size")
    return text


async def open_product(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    user: User,
    product_id: int,
) -> None:
    repo = CatalogRepository(session)
    product = await repo.get_product(product_id)
    if product is None:
        await callback.answer(t("product.unavailable"), show_alert=True)
        return
    data = await state.get_data()
    chat_id = callback.from_user.id
    message = callback.message
    old_card = data.get("card") or {}
    to_delete = list(old_card.get("album", []))
    ctx = data.get("ctx") or {}
    if isinstance(message, Message) and message.message_id in (
        ctx.get("msg"),
        old_card.get("msg"),
    ):
        to_delete.append(message.message_id)
    await safe_delete(bot, chat_id, to_delete)

    album = await send_product_photos(bot, chat_id, product, repo)
    is_fav = await FavoriteService(session).is_favorite(user.id, product.id)
    card = await bot.send_message(
        chat_id, card_text(product, 0, -1), reply_markup=product_card_kb(product, -1, 0, is_fav)
    )
    await state.update_data(card={"album": album, "msg": card.message_id, "pid": product.id})
    await repo.add_view(user.id, product.id)
    await callback.answer()


@router.callback_query(ProdCB.filter(F.a == "view"))
async def cb_product(
    callback: CallbackQuery,
    callback_data: ProdCB,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    user: User,
) -> None:
    await open_product(callback, state, session, bot, user, callback_data.pid)


@router.callback_query(ProdCB.filter(F.a.in_({"color", "var"})))
async def cb_product_select(
    callback: CallbackQuery, callback_data: ProdCB, session: AsyncSession, user: User
) -> None:
    product = await CatalogRepository(session).get_product(callback_data.pid)
    if product is None or not isinstance(callback.message, Message):
        await callback.answer(t("product.unavailable"), show_alert=True)
        return
    is_fav = await FavoriteService(session).is_favorite(user.id, product.id)
    variant_id = callback_data.vid if callback_data.a == "var" else 0
    await render(
        callback,
        card_text(product, variant_id, callback_data.c),
        product_card_kb(product, callback_data.c, variant_id, is_fav),
    )
    await callback.answer()


@router.callback_query(ProdCB.filter(F.a == "add"))
async def cb_add_to_cart(
    callback: CallbackQuery, callback_data: ProdCB, session: AsyncSession, user: User
) -> None:
    if not callback_data.vid:
        await callback.answer(t("product.need_variant"), show_alert=True)
        return
    try:
        item = await CartService(session).add(user.id, callback_data.vid)
    except NotEnoughStock as exc:
        await callback.answer(t("product.not_enough", stock=exc.available), show_alert=True)
        return
    except VariantUnavailable:
        await callback.answer(t("product.unavailable"), show_alert=True)
        return
    variant = await CatalogRepository(session).get_variant(item.variant_id)
    await callback.answer(
        t(
            "product.added",
            title=variant.product.title,
            size=variant.size,
            color=variant.color,
        ),
        show_alert=False,
    )


@router.callback_query(ProdCB.filter(F.a == "fav"))
async def cb_toggle_favorite(
    callback: CallbackQuery, callback_data: ProdCB, session: AsyncSession, user: User
) -> None:
    product = await CatalogRepository(session).get_product(callback_data.pid)
    if product is None:
        await callback.answer(t("product.unavailable"), show_alert=True)
        return
    now_fav = await FavoriteService(session).toggle(user.id, product)
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(
            reply_markup=product_card_kb(product, callback_data.c, callback_data.vid, now_fav)
        )
    await callback.answer(t("product.fav_added") if now_fav else t("product.fav_removed"))


@router.callback_query(ProdCB.filter(F.a == "chart"))
async def cb_size_chart(callback: CallbackQuery) -> None:
    if isinstance(callback.message, Message):
        await callback.message.answer(t("product.size_chart"))
    await callback.answer()


async def _show_ctx_list(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    ctx = (await state.get_data()).get("ctx") or {}
    kind = ctx.get("kind")
    if kind == "cat":
        await show_category(callback.message, state, session, ctx["cat"], ctx.get("page", 0))
    elif kind == "search":
        await show_search_results(callback.message, state, session, ctx.get("q", ""))
    elif kind == "fav":
        await show_favorites(callback.message, state, session, user)
    elif kind == "foryou":
        await show_for_you(callback.message, state, session, user)
    elif kind in {"sim", "bw"}:
        await show_related(callback.message, state, session, ctx["pid"], kind)
    else:
        repo = CatalogRepository(session)
        await callback.message.answer(
            t("catalog.title"), reply_markup=categories_kb(await repo.categories())
        )


@router.callback_query(ProdCB.filter(F.a == "back"))
async def cb_product_back(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot, user: User
) -> None:
    data = await state.get_data()
    card = data.get("card") or {}
    ids = list(card.get("album", []))
    if isinstance(callback.message, Message):
        ids.append(callback.message.message_id)
    await safe_delete(bot, callback.from_user.id, ids)
    await state.update_data(card=None)
    await _show_ctx_list(callback, state, session, user)
    await callback.answer()


# ---------- Похожие и «с этим покупают» ----------
async def show_related(
    event: CallbackQuery | Message, state: FSMContext, session: AsyncSession, pid: int, kind: str
) -> None:
    recs = RecommendationService(session)
    product = await CatalogRepository(session).get_product(pid)
    if product is None:
        products = []
    elif kind == "sim":
        products = await recs.similar(product)
    else:
        products = await recs.bought_with(pid)
    title = t("product.similar_title") if kind == "sim" else t("product.bought_with_title")
    if not products:
        title += "\n\n" + t("product.no_recommendations")
    sent = await render(event, title, products_kb(products, ProdCB(a="view", pid=pid)))
    await _set_ctx(state, sent, kind=kind, pid=pid)


@router.callback_query(ProdCB.filter(F.a.in_({"sim", "bw"})))
async def cb_related(
    callback: CallbackQuery,
    callback_data: ProdCB,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    card = (await state.get_data()).get("card") or {}
    await safe_delete(bot, callback.from_user.id, list(card.get("album", [])))
    await state.update_data(card=None)
    await show_related(callback, state, session, callback_data.pid, callback_data.a)
    await callback.answer()


# ---------- Избранное и подборка ----------
async def show_favorites(
    event: CallbackQuery | Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    products = await FavoriteService(session).list(user.id)
    text = t("fav.title") if products else t("fav.empty")
    sent = await render(event, text, products_kb(products, None))
    await _set_ctx(state, sent, kind="fav")


@router.callback_query(MenuCB.filter(F.a == "fav"))
async def cb_favorites(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    await state.set_state(None)
    await show_favorites(callback, state, session, user)
    await callback.answer()


async def show_for_you(
    event: CallbackQuery | Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    products, personal = await RecommendationService(session).personal(user.id)
    text = t("recs.for_you") if personal else t("recs.popular")
    sent = await render(event, text, products_kb(products, None))
    await _set_ctx(state, sent, kind="foryou")


@router.callback_query(MenuCB.filter(F.a == "foryou"))
async def cb_for_you(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    await state.set_state(None)
    await show_for_you(callback, state, session, user)
    await callback.answer()


# ---------- Поиск ----------
@router.callback_query(MenuCB.filter(F.a == "search"))
async def cb_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SearchStates.query)
    await render(callback, t("search.prompt"), cancel_kb())
    await callback.answer()


async def show_search_results(
    event: CallbackQuery | Message, state: FSMContext, session: AsyncSession, query: str
) -> None:
    repo = CatalogRepository(session)
    flt = ProductFilter(query=query, in_stock_only=False, sort="new")
    products = await repo.list_products(flt, limit=20)
    total = await repo.count_products(flt)
    if products:
        text = t("search.results", query=h(query), count=total)
    else:
        text = t("search.empty", query=h(query))
    sent = await render(event, text, products_kb(products, MenuCB(a="search")))
    await _set_ctx(state, sent, kind="search", q=query)


@router.message(SearchStates.query, F.text)
async def search_query(message: Message, state: FSMContext, session: AsyncSession) -> None:
    query = " ".join(message.text.split())[:64]
    if len(query) < 2:
        await message.answer(t("search.too_short"), reply_markup=cancel_kb())
        return
    await state.set_state(None)
    await show_search_results(message, state, session, query)

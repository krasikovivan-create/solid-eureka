"""Админка: товары — создание, редактирование, фото, размеры и остатки, удаление."""

from __future__ import annotations

import asyncio
import math
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import Gender, Style, size_sort_key
from app.db.models import Product, ProductPhoto, ProductVariant
from app.keyboards.admin import (
    admin_categories_kb,
    admin_product_kb,
    admin_products_kb,
    cancel_admin_kb,
    choose_category_kb,
    confirm_delete_kb,
    gender_kb,
    photos_done_kb,
    style_kb,
    variants_kb,
)
from app.keyboards.callbacks import AdminCB
from app.repositories.catalog import CatalogRepository
from app.services.jobs import Jobs
from app.states import AdminProductStates
from app.texts import t
from app.utils.formatting import gender_label, h, money, style_label
from app.utils.telegram import render

router = Router(name="admin_products")
PAGE = 8
VARIANT_RE = re.compile(r"^\s*(\S+)\s+(.+?)\s+(\d+)\s*$")
_background: set[asyncio.Task] = set()


def parse_variants(text: str) -> tuple[list[tuple[str, str, int]], str | None]:
    """«M чёрный 5» по строке → [(size, color, stock)], либо первая некорректная строка."""
    result = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = VARIANT_RE.match(line)
        if not match:
            return [], line
        size, color, stock = match.groups()
        result.append((size.upper(), color.strip().lower()[:32], int(stock)))
    return result, None


def parse_price(text: str) -> int | None:
    digits = text.replace(" ", "").replace("₽", "")
    return int(digits) if digits.isdigit() and 0 < int(digits) < 10_000_000 else None


def product_admin_text(product: Product) -> str:
    variants = "\n".join(
        f"• {h(v.size)} · {h(v.color)}: {v.stock} шт."
        for v in sorted(product.variants, key=lambda v: (v.color, size_sort_key(v.size)))
    )
    return t(
        "adm.product_card",
        id=product.id,
        title=h(product.title),
        active=t("adm.active") if product.is_active else t("adm.inactive"),
        category=h(product.category.label),
        price=money(product.price),
        old_price=f" (было {money(product.old_price)})" if product.old_price else "",
        gender=gender_label(product.gender),
        style=style_label(product.style),
        composition=h(product.composition or "—"),
        photos=len(product.photos),
        description=h(product.description[:1500]),
        variants=variants or "—",
    )


def _notify_favorites(jobs: Jobs | None, product_id: int) -> None:
    """После изменения цены/остатка — сразу проверяем подписчиков избранного."""
    if jobs is None:
        return
    task = asyncio.create_task(jobs.favorite_alerts([product_id]))
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _show_product(
    event: CallbackQuery | Message, session: AsyncSession, product_id: int
) -> None:
    product = await CatalogRepository(session).get_product(product_id, with_inactive=True)
    if product is None:
        await render(event, t("common.not_found"), cancel_admin_kb(AdminCB(s="prod")))
        return
    await render(event, product_admin_text(product), admin_product_kb(product))


# ---------- Списки ----------
@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "")))
async def cb_products(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    categories = await CatalogRepository(session).categories(only_active=False)
    await render(callback, t("adm.products_title"), admin_categories_kb(categories, "prod"))
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "list")))
async def cb_products_list(
    callback: CallbackQuery, callback_data: AdminCB, session: AsyncSession
) -> None:
    repo = CatalogRepository(session)
    category = await repo.get_category(callback_data.id)
    if category is None:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    total = await repo.category_product_count(category.id)
    pages = max(1, math.ceil(total / PAGE))
    page = min(callback_data.page, pages - 1)
    products = list(
        (
            await session.scalars(
                select(Product)
                .where(Product.category_id == category.id)
                .order_by(Product.id.desc())
                .offset(page * PAGE)
                .limit(PAGE)
            )
        ).all()
    )
    await render(
        callback,
        t("adm.products_in_cat", category=h(category.label), count=total),
        admin_products_kb(products, category.id, page, pages),
    )
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "view")))
async def cb_product(
    callback: CallbackQuery, callback_data: AdminCB, state: FSMContext, session: AsyncSession
) -> None:
    await state.set_state(None)
    await _show_product(callback, session, callback_data.id)
    await callback.answer()


# ---------- Создание ----------
@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "new")))
async def cb_new_product(
    callback: CallbackQuery, callback_data: AdminCB, state: FSMContext, session: AsyncSession
) -> None:
    await state.set_state(None)
    if callback_data.id:
        await state.update_data(np={"category_id": callback_data.id})
        await state.set_state(AdminProductStates.title)
        await render(callback, t("adm.add_title"), cancel_admin_kb(AdminCB(s="prod")))
    else:
        categories = await CatalogRepository(session).categories(only_active=False)
        await render(callback, t("adm.add_choose_category"), choose_category_kb(categories))
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "newcat")))
async def cb_new_product_category(
    callback: CallbackQuery, callback_data: AdminCB, state: FSMContext
) -> None:
    await state.update_data(np={"category_id": callback_data.id})
    await state.set_state(AdminProductStates.title)
    await render(callback, t("adm.add_title"), cancel_admin_kb(AdminCB(s="prod")))
    await callback.answer()


async def _np_update(state: FSMContext, **values) -> dict:
    data = await state.get_data()
    np = dict(data.get("np") or {})
    np.update(values)
    await state.update_data(np=np)
    return np


@router.message(AdminProductStates.title, F.text)
async def np_title(message: Message, state: FSMContext) -> None:
    await _np_update(state, title=message.text.strip()[:256])
    await state.set_state(AdminProductStates.description)
    await message.answer(t("adm.add_description"), reply_markup=cancel_admin_kb(AdminCB(s="prod")))


@router.message(AdminProductStates.description, F.text)
async def np_description(message: Message, state: FSMContext) -> None:
    await _np_update(state, description=message.text.strip()[:3000])
    await state.set_state(AdminProductStates.composition)
    await message.answer(t("adm.add_composition"), reply_markup=cancel_admin_kb(AdminCB(s="prod")))


@router.message(AdminProductStates.composition, F.text)
async def np_composition(message: Message, state: FSMContext) -> None:
    await _np_update(state, composition=message.text.strip()[:512])
    await state.set_state(None)
    await message.answer(t("adm.add_gender"), reply_markup=gender_kb())


@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "gender")))
async def np_gender(callback: CallbackQuery, callback_data: AdminCB, state: FSMContext) -> None:
    if callback_data.v in set(Gender):
        await _np_update(state, gender=callback_data.v)
    await render(callback, t("adm.add_style"), style_kb())
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "style")))
async def np_style(callback: CallbackQuery, callback_data: AdminCB, state: FSMContext) -> None:
    if callback_data.v in set(Style):
        await _np_update(state, style=callback_data.v)
    await state.set_state(AdminProductStates.price)
    await render(callback, t("adm.add_price"), cancel_admin_kb(AdminCB(s="prod")))
    await callback.answer()


@router.message(AdminProductStates.price, F.text)
async def np_price(message: Message, state: FSMContext) -> None:
    price = parse_price(message.text)
    if price is None:
        await message.answer(t("adm.bad_value"))
        return
    await _np_update(state, price=price)
    await state.set_state(AdminProductStates.old_price)
    await message.answer(t("adm.add_old_price"), reply_markup=cancel_admin_kb(AdminCB(s="prod")))


@router.message(AdminProductStates.old_price, F.text)
async def np_old_price(message: Message, state: FSMContext) -> None:
    old_price = None
    if message.text.strip() != "-":
        old_price = parse_price(message.text)
        if old_price is None:
            await message.answer(t("adm.bad_value"))
            return
    await _np_update(state, old_price=old_price, photos=[])
    await state.set_state(AdminProductStates.photos)
    await message.answer(
        t("adm.add_photos"), reply_markup=photos_done_kb(AdminCB(s="prod", a="photos_done"))
    )


@router.message(AdminProductStates.photos, F.photo)
async def np_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    np = dict(data.get("np") or {})
    photos = [*np.get("photos", []), message.photo[-1].file_id][:10]
    np["photos"] = photos
    await state.update_data(np=np)
    if not message.media_group_id:
        await message.answer(
            t("adm.photo_saved", n=len(photos)),
            reply_markup=photos_done_kb(AdminCB(s="prod", a="photos_done")),
        )


@router.callback_query(
    AdminProductStates.photos, AdminCB.filter((F.s == "prod") & (F.a == "photos_done"))
)
async def np_photos_done(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminProductStates.variants)
    await render(callback, t("adm.add_variants"), cancel_admin_kb(AdminCB(s="prod")))
    await callback.answer()


@router.message(AdminProductStates.variants, F.text)
async def np_variants(message: Message, state: FSMContext, session: AsyncSession) -> None:
    variants, bad = parse_variants(message.text)
    if bad is not None or not variants:
        await message.answer(t("adm.bad_variants", line=h(bad or "—")))
        return
    np = (await state.get_data()).get("np") or {}
    repo = CatalogRepository(session)
    category = await repo.get_category(np.get("category_id", 0))
    if category is None or "price" not in np:
        await state.set_state(None)
        await message.answer(t("common.error"))
        return
    product = Product(
        category_id=category.id,
        title=np.get("title", "Товар"),
        description=np.get("description", ""),
        composition=np.get("composition", ""),
        gender=np.get("gender", Gender.UNISEX),
        style=np.get("style", Style.CASUAL),
        price=np["price"],
        old_price=np.get("old_price"),
    )
    seen = set()
    product.variants = []
    for size, color, stock in variants:
        if (size, color) in seen:
            continue
        seen.add((size, color))
        product.variants.append(ProductVariant(size=size, color=color, stock=stock))
    product.photos = [
        ProductPhoto(file_id=fid, sort=i) for i, fid in enumerate(np.get("photos", []))
    ]
    product.rebuild_search_text(category.title)
    session.add(product)
    await session.flush()
    await state.set_state(None)
    await state.update_data(np=None)
    await message.answer(t("adm.product_created", id=product.id))
    await _show_product(message, session, product.id)


# ---------- Редактирование ----------
EDITABLE = {"title", "description", "composition", "price", "old_price"}


@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "edit")))
async def cb_edit_field(callback: CallbackQuery, callback_data: AdminCB, state: FSMContext) -> None:
    if callback_data.v not in EDITABLE:
        await callback.answer()
        return
    await state.update_data(edit={"pid": callback_data.id, "field": callback_data.v})
    await state.set_state(AdminProductStates.edit_field)
    hint = t("adm.add_old_price") if callback_data.v == "old_price" else t("adm.enter_value")
    await render(callback, hint, cancel_admin_kb(AdminCB(s="prod", a="view", id=callback_data.id)))
    await callback.answer()


@router.message(AdminProductStates.edit_field, F.text)
async def msg_edit_field(
    message: Message, state: FSMContext, session: AsyncSession, jobs: Jobs | None = None
) -> None:
    edit = (await state.get_data()).get("edit") or {}
    product = await CatalogRepository(session).get_product(edit.get("pid", 0), with_inactive=True)
    field = edit.get("field")
    if product is None or field not in EDITABLE:
        await state.set_state(None)
        await message.answer(t("common.not_found"))
        return
    text = message.text.strip()
    if field == "price":
        value = parse_price(text)
        if value is None:
            await message.answer(t("adm.bad_value"))
            return
        product.price = value
    elif field == "old_price":
        value = None if text == "-" else parse_price(text)
        if text != "-" and value is None:
            await message.answer(t("adm.bad_value"))
            return
        product.old_price = value
    else:
        limits = {"title": 256, "description": 3000, "composition": 512}
        setattr(product, field, text[: limits[field]])
    product.rebuild_search_text(product.category.title)
    await session.commit()
    await state.set_state(None)
    if field == "price":
        _notify_favorites(jobs, product.id)
    await message.answer(t("common.saved"))
    await _show_product(message, session, product.id)


@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "photos")))
async def cb_edit_photos(
    callback: CallbackQuery, callback_data: AdminCB, state: FSMContext, session: AsyncSession
) -> None:
    product = await CatalogRepository(session).get_product(callback_data.id, with_inactive=True)
    if product is None:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    await state.update_data(edit={"pid": product.id, "photos": []})
    await state.set_state(AdminProductStates.edit_photos)
    await render(
        callback,
        t("adm.photos_title", count=len(product.photos)),
        photos_done_kb(AdminCB(s="prod", a="photos_save", id=product.id)),
    )
    await callback.answer()


@router.message(AdminProductStates.edit_photos, F.photo)
async def msg_edit_photo(message: Message, state: FSMContext) -> None:
    edit = dict((await state.get_data()).get("edit") or {})
    edit["photos"] = [*edit.get("photos", []), message.photo[-1].file_id][:10]
    await state.update_data(edit=edit)
    if not message.media_group_id:
        await message.answer(
            t("adm.photo_saved", n=len(edit["photos"])),
            reply_markup=photos_done_kb(AdminCB(s="prod", a="photos_save", id=edit["pid"])),
        )


@router.callback_query(
    AdminProductStates.edit_photos, AdminCB.filter((F.s == "prod") & (F.a == "photos_save"))
)
async def cb_save_photos(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    edit = (await state.get_data()).get("edit") or {}
    repo = CatalogRepository(session)
    product = await repo.get_product(edit.get("pid", 0), with_inactive=True)
    await state.set_state(None)
    if product is None:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    photos = edit.get("photos") or []
    if photos:
        await repo.replace_photos(product, photos)
        await callback.answer(t("adm.photos_replaced", count=len(photos)))
    else:
        await callback.answer()
    await _show_product(callback, session, product.id)


@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "variants")))
async def cb_variants(
    callback: CallbackQuery, callback_data: AdminCB, state: FSMContext, session: AsyncSession
) -> None:
    await state.set_state(None)
    product = await CatalogRepository(session).get_product(callback_data.id, with_inactive=True)
    if product is None:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    await render(callback, t("adm.variants_title", title=h(product.title)), variants_kb(product))
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "stock")))
async def cb_stock(
    callback: CallbackQuery, callback_data: AdminCB, state: FSMContext, session: AsyncSession
) -> None:
    variant = await session.get(ProductVariant, callback_data.id)
    if variant is None:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    await state.update_data(edit={"vid": variant.id, "pid": variant.product_id})
    await state.set_state(AdminProductStates.edit_stock)
    await render(
        callback,
        t("adm.enter_stock", label=h(variant.label)),
        cancel_admin_kb(AdminCB(s="prod", a="variants", id=variant.product_id)),
    )
    await callback.answer()


@router.message(AdminProductStates.edit_stock, F.text)
async def msg_stock(
    message: Message, state: FSMContext, session: AsyncSession, jobs: Jobs | None = None
) -> None:
    edit = (await state.get_data()).get("edit") or {}
    text = message.text.strip()
    if not text.isdigit() or int(text) > 100_000:
        await message.answer(t("adm.bad_value"))
        return
    variant = await session.get(ProductVariant, edit.get("vid", 0))
    if variant is None:
        await state.set_state(None)
        await message.answer(t("common.not_found"))
        return
    variant.stock = int(text)
    await session.commit()
    await state.set_state(None)
    _notify_favorites(jobs, variant.product_id)
    product = await CatalogRepository(session).get_product(variant.product_id, with_inactive=True)
    await message.answer(
        t("adm.variants_title", title=h(product.title)), reply_markup=variants_kb(product)
    )


@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "addvar")))
async def cb_add_variants(
    callback: CallbackQuery, callback_data: AdminCB, state: FSMContext
) -> None:
    await state.update_data(edit={"pid": callback_data.id})
    await state.set_state(AdminProductStates.add_variants)
    await render(
        callback,
        t("adm.add_variants"),
        cancel_admin_kb(AdminCB(s="prod", a="variants", id=callback_data.id)),
    )
    await callback.answer()


@router.message(AdminProductStates.add_variants, F.text)
async def msg_add_variants(
    message: Message, state: FSMContext, session: AsyncSession, jobs: Jobs | None = None
) -> None:
    variants, bad = parse_variants(message.text)
    if bad is not None or not variants:
        await message.answer(t("adm.bad_variants", line=h(bad or "—")))
        return
    edit = (await state.get_data()).get("edit") or {}
    repo = CatalogRepository(session)
    product = await repo.get_product(edit.get("pid", 0), with_inactive=True)
    if product is None:
        await state.set_state(None)
        await message.answer(t("common.not_found"))
        return
    existing = {(v.size, v.color): v for v in product.variants}
    for size, color, stock in variants:
        if (size, color) in existing:
            existing[(size, color)].stock = stock
        else:
            variant = ProductVariant(size=size, color=color, stock=stock)
            product.variants.append(variant)
            existing[(size, color)] = variant
    product.rebuild_search_text(product.category.title)
    await session.commit()
    await state.set_state(None)
    _notify_favorites(jobs, product.id)
    await message.answer(
        t("adm.variants_title", title=h(product.title)), reply_markup=variants_kb(product)
    )


# ---------- Скрытие и удаление ----------
@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "toggle")))
async def cb_toggle(callback: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    product = await session.get(Product, callback_data.id)
    if product is None:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    product.is_active = not product.is_active
    await session.flush()
    await _show_product(callback, session, product.id)
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "delete")))
async def cb_delete(callback: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    product = await session.get(Product, callback_data.id)
    if product is None:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    await render(
        callback,
        t("adm.confirm_delete", title=h(product.title)),
        confirm_delete_kb(
            AdminCB(s="prod", a="delete_yes", id=product.id),
            AdminCB(s="prod", a="view", id=product.id),
        ),
    )
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "prod") & (F.a == "delete_yes")))
async def cb_delete_yes(
    callback: CallbackQuery, callback_data: AdminCB, session: AsyncSession
) -> None:
    product = await session.get(Product, callback_data.id)
    if product is None:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    category_id = product.category_id
    await session.delete(product)
    await session.flush()
    count = int(
        await session.scalar(
            select(func.count(Product.id)).where(Product.category_id == category_id)
        )
        or 0
    )
    await callback.answer(t("common.deleted"))
    category = await CatalogRepository(session).get_category(category_id)
    products = list(
        (
            await session.scalars(
                select(Product)
                .where(Product.category_id == category_id)
                .order_by(Product.id.desc())
                .limit(PAGE)
            )
        ).all()
    )
    await render(
        callback,
        t("adm.products_in_cat", category=h(category.label), count=count),
        admin_products_kb(products, category_id, 0, max(1, math.ceil(count / PAGE))),
    )

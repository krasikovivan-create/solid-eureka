"""Админка: категории, промокоды, зоны и тарифы доставки."""

from __future__ import annotations

import re
from datetime import datetime, time
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.constants import DeliveryMethod, PromoKind
from app.db.models import Category, DeliveryTariff, DeliveryZone, PromoCode
from app.keyboards.admin import (
    admin_categories_kb,
    cancel_admin_kb,
    category_kb,
    confirm_delete_kb,
    promo_kb,
    promo_kind_kb,
    promos_kb,
    zone_kb,
    zones_kb,
)
from app.keyboards.callbacks import AdminCB
from app.repositories.catalog import CatalogRepository
from app.services.promo import PromoService, normalize_code
from app.states import AdminCategoryStates, AdminPromoStates, AdminZoneStates
from app.texts import t
from app.utils.formatting import days_range, delivery_label, h, local_dt, money
from app.utils.telegram import render

router = Router(name="admin_settings")
CODE_RE = re.compile(r"^[A-Z0-9_\-]{3,32}$")


def _slugify(title: str) -> str:
    table = str.maketrans(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        "abvgdeejzijklmnoprstufhccss_y_eua",
    )
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower().translate(table)).strip("-")
    return slug[:48] or "category"


# ---------- Категории ----------
@router.callback_query(AdminCB.filter((F.s == "cat") & (F.a == "")))
async def cb_categories(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    categories = await CatalogRepository(session).categories(only_active=False)
    await render(callback, t("adm.categories_title"), admin_categories_kb(categories, "cat"))
    await callback.answer()


async def _show_category(event, session: AsyncSession, category_id: int) -> None:
    repo = CatalogRepository(session)
    category = await repo.get_category(category_id)
    if category is None:
        await render(event, t("common.not_found"), cancel_admin_kb(AdminCB(s="cat")))
        return
    text = t(
        "adm.category_card",
        label=h(category.label),
        active=t("adm.active") if category.is_active else t("adm.inactive"),
        count=await repo.category_product_count(category.id),
    )
    await render(event, text, category_kb(category))


@router.callback_query(AdminCB.filter((F.s == "cat") & (F.a == "view")))
async def cb_category(
    callback: CallbackQuery, callback_data: AdminCB, session: AsyncSession
) -> None:
    await _show_category(callback, session, callback_data.id)
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "cat") & (F.a.in_({"new", "rename"}))))
async def cb_category_input(
    callback: CallbackQuery, callback_data: AdminCB, state: FSMContext
) -> None:
    await state.update_data(cat_id=callback_data.id)
    await state.set_state(
        AdminCategoryStates.create if callback_data.a == "new" else AdminCategoryStates.rename
    )
    await render(callback, t("adm.enter_category"), cancel_admin_kb(AdminCB(s="cat")))
    await callback.answer()


def _parse_category(text: str) -> tuple[str, str]:
    text = text.strip()
    parts = text.split(maxsplit=1)
    if len(parts) == 2 and not any(ch.isalnum() for ch in parts[0]):
        return parts[0][:8], parts[1][:128]
    return "", text[:128]


@router.message(AdminCategoryStates.create, F.text)
async def msg_category_create(message: Message, state: FSMContext, session: AsyncSession) -> None:
    emoji, title = _parse_category(message.text)
    if len(title) < 2:
        await message.answer(t("adm.bad_value"))
        return
    slug = _slugify(title)
    if await session.scalar(select(Category.id).where(Category.slug == slug)):
        slug = f"{slug}-{int(datetime.now().timestamp())}"
    max_sort = max((c.sort for c in await CatalogRepository(session).categories(False)), default=0)
    category = Category(slug=slug, title=title, emoji=emoji, sort=max_sort + 1)
    session.add(category)
    await session.flush()
    await state.set_state(None)
    await _show_category(message, session, category.id)


@router.message(AdminCategoryStates.rename, F.text)
async def msg_category_rename(message: Message, state: FSMContext, session: AsyncSession) -> None:
    category = await session.get(Category, (await state.get_data()).get("cat_id", 0))
    emoji, title = _parse_category(message.text)
    if category is None or len(title) < 2:
        await message.answer(t("adm.bad_value"))
        return
    category.title = title
    category.emoji = emoji or category.emoji
    await session.flush()
    await state.set_state(None)
    await _show_category(message, session, category.id)


@router.callback_query(AdminCB.filter((F.s == "cat") & (F.a == "toggle")))
async def cb_category_toggle(
    callback: CallbackQuery, callback_data: AdminCB, session: AsyncSession
) -> None:
    category = await session.get(Category, callback_data.id)
    if category:
        category.is_active = not category.is_active
        await session.flush()
    await _show_category(callback, session, callback_data.id)
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "cat") & (F.a == "delete")))
async def cb_category_delete(
    callback: CallbackQuery, callback_data: AdminCB, session: AsyncSession
) -> None:
    repo = CatalogRepository(session)
    category = await repo.get_category(callback_data.id)
    if category is None:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    if await repo.category_product_count(category.id):
        await callback.answer(t("adm.category_not_empty"), show_alert=True)
        return
    await session.delete(category)
    await session.flush()
    await callback.answer(t("common.deleted"))
    categories = await repo.categories(only_active=False)
    await render(callback, t("adm.categories_title"), admin_categories_kb(categories, "cat"))


# ---------- Промокоды ----------
def _promo_value(promo: PromoCode) -> str:
    return f"{promo.value}%" if promo.kind == PromoKind.PERCENT else money(promo.value)


@router.callback_query(AdminCB.filter((F.s == "promo") & (F.a == "")))
async def cb_promos(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    promos = await PromoService(session).list_all()
    lines = [t("adm.promos_title")]
    for p in promos[:30]:
        lines.append(
            t(
                "adm.promo_line",
                code=h(p.code),
                value=_promo_value(p),
                used=p.used_count,
                max=p.max_uses if p.max_uses is not None else "∞",
                to=p.valid_to.strftime("%d.%m.%Y") if p.valid_to else "∞",
                active="🟢" if p.is_active else "🔴",
            )
        )
    await render(callback, "\n".join(lines), promos_kb(promos))
    await callback.answer()


async def _show_promo(event, session: AsyncSession, promo_id: int, settings: Settings) -> None:
    promo = await session.get(PromoCode, promo_id)
    if promo is None:
        await render(event, t("common.not_found"), cancel_admin_kb(AdminCB(s="promo")))
        return
    text = t(
        "adm.promo_card",
        code=h(promo.code),
        active=t("adm.active") if promo.is_active else t("adm.inactive"),
        value=_promo_value(promo),
        min_total=money(promo.min_total),
        valid_from=local_dt(promo.valid_from, settings.timezone) if promo.valid_from else "—",
        valid_to=local_dt(promo.valid_to, settings.timezone) if promo.valid_to else "∞",
        used=promo.used_count,
        max=promo.max_uses if promo.max_uses is not None else "∞",
        per_user=promo.per_user_limit or "∞",
    )
    await render(event, text, promo_kb(promo))


@router.callback_query(AdminCB.filter((F.s == "promo") & (F.a == "view")))
async def cb_promo(
    callback: CallbackQuery, callback_data: AdminCB, session: AsyncSession, settings: Settings
) -> None:
    await _show_promo(callback, session, callback_data.id, settings)
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "promo") & (F.a == "toggle")))
async def cb_promo_toggle(
    callback: CallbackQuery, callback_data: AdminCB, session: AsyncSession, settings: Settings
) -> None:
    promo = await session.get(PromoCode, callback_data.id)
    if promo:
        promo.is_active = not promo.is_active
        await session.flush()
    await _show_promo(callback, session, callback_data.id, settings)
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "promo") & (F.a == "delete")))
async def cb_promo_delete(
    callback: CallbackQuery, callback_data: AdminCB, session: AsyncSession
) -> None:
    promo = await session.get(PromoCode, callback_data.id)
    if promo is None:
        await callback.answer(t("common.not_found"), show_alert=True)
        return
    await render(
        callback,
        t("adm.confirm_delete", title=h(promo.code)),
        confirm_delete_kb(
            AdminCB(s="promo", a="delete_yes", id=promo.id),
            AdminCB(s="promo", a="view", id=promo.id),
        ),
    )
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "promo") & (F.a == "delete_yes")))
async def cb_promo_delete_yes(
    callback: CallbackQuery, callback_data: AdminCB, session: AsyncSession
) -> None:
    promo = await session.get(PromoCode, callback_data.id)
    if promo:
        await session.delete(promo)
        await session.flush()
    await callback.answer(t("common.deleted"))
    await render(callback, t("adm.promos_title"), promos_kb(await PromoService(session).list_all()))


@router.callback_query(AdminCB.filter((F.s == "promo") & (F.a == "new")))
async def cb_promo_new(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(npromo={})
    await state.set_state(AdminPromoStates.code)
    await render(callback, t("adm.promo_code"), cancel_admin_kb(AdminCB(s="promo")))
    await callback.answer()


@router.message(AdminPromoStates.code, F.text)
async def msg_promo_code(message: Message, state: FSMContext, session: AsyncSession) -> None:
    code = normalize_code(message.text)
    if not CODE_RE.match(code):
        await message.answer(t("adm.bad_value"))
        return
    if await PromoService(session).get(code):
        await message.answer(t("adm.promo_exists"))
        return
    await state.update_data(npromo={"code": code})
    await state.set_state(None)
    await message.answer(t("adm.promo_kind"), reply_markup=promo_kind_kb())


@router.callback_query(AdminCB.filter((F.s == "promo") & (F.a == "kind")))
async def cb_promo_kind(callback: CallbackQuery, callback_data: AdminCB, state: FSMContext) -> None:
    data = dict((await state.get_data()).get("npromo") or {})
    if "code" not in data or callback_data.v not in set(PromoKind):
        await callback.answer(t("common.error"), show_alert=True)
        return
    data["kind"] = callback_data.v
    await state.update_data(npromo=data)
    await state.set_state(AdminPromoStates.value)
    await render(callback, t("adm.promo_value"), cancel_admin_kb(AdminCB(s="promo")))
    await callback.answer()


async def _npromo(state: FSMContext, **values) -> dict:
    data = dict((await state.get_data()).get("npromo") or {})
    data.update(values)
    await state.update_data(npromo=data)
    return data


@router.message(AdminPromoStates.value, F.text)
async def msg_promo_value(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    data = (await state.get_data()).get("npromo") or {}
    max_value = 90 if data.get("kind") == PromoKind.PERCENT else 1_000_000
    if not text.isdigit() or not 1 <= int(text) <= max_value:
        await message.answer(t("adm.bad_value"))
        return
    await _npromo(state, value=int(text))
    await state.set_state(AdminPromoStates.min_total)
    await message.answer(t("adm.promo_min_total"), reply_markup=cancel_admin_kb(AdminCB(s="promo")))


@router.message(AdminPromoStates.min_total, F.text)
async def msg_promo_min_total(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text.isdigit():
        await message.answer(t("adm.bad_value"))
        return
    await _npromo(state, min_total=int(text))
    await state.set_state(AdminPromoStates.valid_to)
    await message.answer(t("adm.promo_valid_to"), reply_markup=cancel_admin_kb(AdminCB(s="promo")))


@router.message(AdminPromoStates.valid_to, F.text)
async def msg_promo_valid_to(message: Message, state: FSMContext, settings: Settings) -> None:
    text = message.text.strip()
    valid_to = None
    if text != "-":
        try:
            day = datetime.strptime(text, "%d.%m.%Y").date()
        except ValueError:
            await message.answer(t("adm.bad_value"))
            return
        local_end = datetime.combine(day, time(23, 59, 59), tzinfo=ZoneInfo(settings.timezone))
        valid_to = local_end.astimezone(ZoneInfo("UTC")).replace(tzinfo=None).isoformat()
    await _npromo(state, valid_to=valid_to)
    await state.set_state(AdminPromoStates.max_uses)
    await message.answer(t("adm.promo_max_uses"), reply_markup=cancel_admin_kb(AdminCB(s="promo")))


@router.message(AdminPromoStates.max_uses, F.text)
async def msg_promo_max_uses(
    message: Message, state: FSMContext, session: AsyncSession, settings: Settings
) -> None:
    text = message.text.strip()
    if text != "-" and not text.isdigit():
        await message.answer(t("adm.bad_value"))
        return
    data = await _npromo(state, max_uses=None if text == "-" else int(text))
    promo = await PromoService(session).create(
        code=data["code"],
        kind=data["kind"],
        value=data["value"],
        min_total=data.get("min_total", 0),
        valid_to=datetime.fromisoformat(data["valid_to"]) if data.get("valid_to") else None,
        max_uses=data.get("max_uses"),
    )
    await state.set_state(None)
    await state.update_data(npromo=None)
    await message.answer(t("adm.promo_created", code=h(promo.code)))
    await _show_promo(message, session, promo.id, settings)


# ---------- Зоны и тарифы доставки ----------
async def _zones(session: AsyncSession) -> list[DeliveryZone]:
    stmt = (
        select(DeliveryZone)
        .options(selectinload(DeliveryZone.tariffs))
        .order_by(DeliveryZone.is_default, DeliveryZone.id)
    )
    return list((await session.scalars(stmt)).all())


async def _show_zone(event, session: AsyncSession, zone_id: int) -> None:
    zone = await session.scalar(
        select(DeliveryZone)
        .where(DeliveryZone.id == zone_id)
        .options(selectinload(DeliveryZone.tariffs))
        .execution_options(populate_existing=True)
    )
    if zone is None:
        await render(event, t("common.not_found"), cancel_admin_kb(AdminCB(s="zone")))
        return
    lines = []
    for tariff in zone.tariffs:
        lines.append(
            t(
                "adm.tariff_line",
                method=delivery_label(tariff.method),
                price=money(tariff.price),
                free=t("adm.tariff_free", free=money(tariff.free_from)) if tariff.free_from else "",
                days=days_range(tariff.days_min, tariff.days_max),
                active="" if tariff.is_active else " 🔴",
            )
        )
    text = t(
        "adm.zone_card",
        name=h(zone.name),
        default=t("adm.zone_default") if zone.is_default else "",
        cities=h(zone.cities or "—"),
        tariffs="\n".join(lines) or "—",
    )
    await render(event, text, zone_kb(zone))


@router.callback_query(AdminCB.filter((F.s == "zone") & (F.a == "")))
async def cb_zones(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    await render(callback, t("adm.tariffs_title"), zones_kb(await _zones(session)))
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "zone") & (F.a == "view")))
async def cb_zone(
    callback: CallbackQuery, callback_data: AdminCB, state: FSMContext, session: AsyncSession
) -> None:
    await state.set_state(None)
    await _show_zone(callback, session, callback_data.id)
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "zone") & (F.a == "new")))
async def cb_zone_new(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminZoneStates.create)
    await render(callback, t("adm.enter_zone"), cancel_admin_kb(AdminCB(s="zone")))
    await callback.answer()


def _parse_cities(text: str) -> str:
    return ", ".join(c.strip().lower() for c in text.split(",") if c.strip())[:2000]


@router.message(AdminZoneStates.create, F.text)
async def msg_zone_create(message: Message, state: FSMContext, session: AsyncSession) -> None:
    name, _, cities = message.text.partition(";")
    if len(name.strip()) < 2 or not cities.strip():
        await message.answer(t("adm.bad_value"))
        return
    zone = DeliveryZone(name=name.strip()[:128], cities=_parse_cities(cities))
    session.add(zone)
    await session.flush()
    await state.set_state(None)
    await _show_zone(message, session, zone.id)


@router.callback_query(AdminCB.filter((F.s == "zone") & (F.a == "cities")))
async def cb_zone_cities(
    callback: CallbackQuery, callback_data: AdminCB, state: FSMContext
) -> None:
    await state.update_data(zone_id=callback_data.id)
    await state.set_state(AdminZoneStates.cities)
    await render(
        callback,
        t("adm.enter_cities"),
        cancel_admin_kb(AdminCB(s="zone", a="view", id=callback_data.id)),
    )
    await callback.answer()


@router.message(AdminZoneStates.cities, F.text)
async def msg_zone_cities(message: Message, state: FSMContext, session: AsyncSession) -> None:
    zone = await session.get(DeliveryZone, (await state.get_data()).get("zone_id", 0))
    if zone is None:
        await state.set_state(None)
        await message.answer(t("common.not_found"))
        return
    zone.cities = _parse_cities(message.text)
    await session.flush()
    await state.set_state(None)
    await _show_zone(message, session, zone.id)


@router.callback_query(AdminCB.filter((F.s == "zone") & (F.a == "delete")))
async def cb_zone_delete(
    callback: CallbackQuery, callback_data: AdminCB, session: AsyncSession
) -> None:
    zone = await session.get(DeliveryZone, callback_data.id)
    if zone and not zone.is_default:
        await session.delete(zone)
        await session.flush()
    await callback.answer(t("common.deleted"))
    await render(callback, t("adm.tariffs_title"), zones_kb(await _zones(session)))


@router.callback_query(AdminCB.filter((F.s == "zone") & (F.a == "tariff")))
async def cb_tariff(callback: CallbackQuery, callback_data: AdminCB, state: FSMContext) -> None:
    if callback_data.v not in set(DeliveryMethod):
        await callback.answer()
        return
    await state.update_data(tariff={"zone_id": callback_data.id, "method": callback_data.v})
    await state.set_state(AdminZoneStates.tariff)
    await render(
        callback,
        t("adm.enter_tariff", method=delivery_label(callback_data.v)),
        cancel_admin_kb(AdminCB(s="zone", a="view", id=callback_data.id)),
    )
    await callback.answer()


@router.message(AdminZoneStates.tariff, F.text)
async def msg_tariff(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = (await state.get_data()).get("tariff") or {}
    zone_id, method = data.get("zone_id"), data.get("method")
    tariff = await session.scalar(
        select(DeliveryTariff).where(
            DeliveryTariff.zone_id == zone_id, DeliveryTariff.method == method
        )
    )
    parts = message.text.split()
    if parts and parts[0].lower() == "off":
        if tariff:
            tariff.is_active = False
    else:
        if len(parts) != 4 or not all(
            p.isdigit() or (i == 1 and p == "-") for i, p in enumerate(parts)
        ):
            await message.answer(t("adm.bad_value"))
            return
        price, free_from, days_min, days_max = parts
        if int(days_min) > int(days_max):
            await message.answer(t("adm.bad_value"))
            return
        if tariff is None:
            tariff = DeliveryTariff(zone_id=zone_id, method=method)
            session.add(tariff)
        tariff.price = int(price)
        tariff.free_from = None if free_from == "-" else int(free_from)
        tariff.days_min, tariff.days_max = int(days_min), int(days_max)
        tariff.is_active = True
    await session.flush()
    await state.set_state(None)
    await message.answer(t("common.saved"))
    await _show_zone(message, session, zone_id)

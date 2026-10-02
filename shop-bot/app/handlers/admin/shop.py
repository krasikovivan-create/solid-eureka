"""Админка: настройки магазина (название, приветствие, баннер, самовывоз, оператор ПДн)
и удаление демо-каталога."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Product
from app.keyboards.admin import cancel_admin_kb, confirm_delete_kb, shop_kb
from app.keyboards.callbacks import AdminCB
from app.services.privacy import privacy_policy_text
from app.services.shop_config import ShopConfig
from app.states import AdminShopStates
from app.texts import t
from app.utils.formatting import h
from app.utils.telegram import render

router = Router(name="admin_shop")
TEXT_KEYS = {"shop_name": 64, "welcome": 900, "pickup_address": 300, "operator": 300}
# Поля, которые можно сбросить «-» к значению по умолчанию.
RESETTABLE = {"welcome", "operator"}


async def demo_count(session: AsyncSession) -> int:
    stmt = select(func.count(Product.id)).where(Product.is_demo.is_(True))
    return int(await session.scalar(stmt) or 0)


async def shop_screen(session: AsyncSession, shop: ShopConfig, settings: Settings):
    demo = await demo_count(session)
    text = t(
        "adm.shop_title",
        name=h(shop.shop_name),
        welcome=h(shop.welcome[:80] + "…")
        if len(shop.welcome) > 80
        else (h(shop.welcome) or t("adm.shop_default")),
        banner=t("adm.shop_banner_custom")
        if shop.is_custom("banner")
        else t("adm.shop_banner_default"),
        pickup=h(shop.pickup_address),
        operator=h(shop.operator) or t("adm.shop_operator_empty"),
        payments=t("adm.payments_fake")
        if settings.payments_mode == "fake"
        else t("adm.payments_live"),
        stylist=t("adm.enabled") if settings.stylist_available else t("adm.disabled"),
        demo=demo,
    )
    return text, shop_kb(demo)


@router.callback_query(AdminCB.filter((F.s == "shop") & (F.a == "")))
async def cb_shop(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    shop: ShopConfig,
    settings: Settings,
) -> None:
    await state.set_state(None)
    text, kb = await shop_screen(session, shop, settings)
    await render(callback, text, kb)
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "shop") & (F.a == "edit")))
async def cb_shop_edit(callback: CallbackQuery, callback_data: AdminCB, state: FSMContext) -> None:
    if callback_data.v not in TEXT_KEYS:
        await callback.answer()
        return
    await state.update_data(shop_key=callback_data.v)
    await state.set_state(AdminShopStates.value)
    await render(
        callback, t(f"adm.shop_enter.{callback_data.v}"), cancel_admin_kb(AdminCB(s="shop"))
    )
    await callback.answer()


@router.message(AdminShopStates.value, F.text)
async def msg_shop_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    shop: ShopConfig,
    settings: Settings,
) -> None:
    key = (await state.get_data()).get("shop_key")
    if key not in TEXT_KEYS:
        await state.set_state(None)
        return
    value = message.text.strip()
    if value == "-" and key in RESETTABLE:
        value = ""
    elif len(value) < 2 or len(value) > TEXT_KEYS[key]:
        await message.answer(t("adm.bad_value"))
        return
    await shop.set(session, key, value)
    await state.set_state(None)
    await message.answer(t("common.saved"))
    text, kb = await shop_screen(session, shop, settings)
    await message.answer(text, reply_markup=kb)


@router.callback_query(AdminCB.filter((F.s == "shop") & (F.a == "banner")))
async def cb_shop_banner(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminShopStates.banner)
    await render(callback, t("adm.shop_enter_banner"), cancel_admin_kb(AdminCB(s="shop")))
    await callback.answer()


@router.message(AdminShopStates.banner, F.photo | (F.text == "-"))
async def msg_shop_banner(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    shop: ShopConfig,
    settings: Settings,
) -> None:
    value = message.photo[-1].file_id if message.photo else ""
    await shop.set(session, "banner", value)
    await state.set_state(None)
    await message.answer(t("common.saved"))
    text, kb = await shop_screen(session, shop, settings)
    await message.answer(text, reply_markup=kb)


@router.callback_query(AdminCB.filter((F.s == "shop") & (F.a == "policy")))
async def cb_shop_policy(callback: CallbackQuery, shop: ShopConfig) -> None:
    await callback.message.answer(privacy_policy_text(shop))
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "shop") & (F.a == "demo")))
async def cb_shop_demo(callback: CallbackQuery, session: AsyncSession) -> None:
    count = await demo_count(session)
    await render(
        callback,
        t("adm.confirm_delete_demo", count=count),
        confirm_delete_kb(AdminCB(s="shop", a="demo_yes"), AdminCB(s="shop")),
    )
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "shop") & (F.a == "demo_yes")))
async def cb_shop_demo_yes(
    callback: CallbackQuery, session: AsyncSession, shop: ShopConfig, settings: Settings
) -> None:
    products = (await session.scalars(select(Product).where(Product.is_demo.is_(True)))).all()
    for product in products:
        await session.delete(product)
    await session.commit()
    await callback.answer(t("adm.demo_deleted", count=len(products)), show_alert=True)
    text, kb = await shop_screen(session, shop, settings)
    await render(callback, text, kb)

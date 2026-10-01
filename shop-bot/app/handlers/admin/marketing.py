"""Админка: статистика, статистика стилиста, рассылки с предпросмотром."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.constants import Segment
from app.db.models import Broadcast
from app.keyboards.admin import (
    back_kb,
    bc_category_kb,
    bc_confirm_kb,
    cancel_admin_kb,
    segment_kb,
    stats_kb,
)
from app.keyboards.callbacks import AdminCB
from app.repositories.catalog import CatalogRepository
from app.services.broadcast import (
    BroadcastRunner,
    BroadcastService,
    segment_user_ids,
    send_broadcast_message,
)
from app.services.stats import StatsService
from app.states import AdminBroadcastStates
from app.texts import t
from app.utils.formatting import h, local_dt, money
from app.utils.telegram import render

logger = logging.getLogger(__name__)
router = Router(name="admin_marketing")
_background: set[asyncio.Task] = set()


# ---------- Статистика ----------
@router.callback_query(AdminCB.filter((F.s == "stats") & (F.a == "")))
async def cb_stats(callback: CallbackQuery) -> None:
    await render(callback, t("adm.stats_title"), stats_kb())
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "stats") & (F.a == "p")))
async def cb_stats_period(
    callback: CallbackQuery, callback_data: AdminCB, session: AsyncSession
) -> None:
    period = callback_data.v if callback_data.v in {"day", "week", "month"} else "day"
    s = await StatsService(session).shop(period)
    top = "\n".join(
        f"{i}. {h(title)} — {qty} шт., {money(revenue)}"
        for i, (title, qty, revenue) in enumerate(s.top, start=1)
    )
    sources = "\n".join(
        f"• {h(src)}: {users} польз., {orders} заказ(ов), {money(revenue)}"
        for src, users, orders, revenue in s.sources
    )
    text = t(
        "adm.stats",
        period=t(f"adm.period_{period}").lower(),
        new_users=s.new_users,
        orders=s.orders,
        success=s.success,
        revenue=money(s.revenue),
        avg=money(s.avg_check),
        conversion=s.conversion,
        ordered=s.ordered_users,
        carted=s.carted_users,
        top=top or "—",
        sources=sources or "—",
        referred=s.referred,
        referred_buyers=s.referred_buyers,
    )
    await render(callback, text, stats_kb())
    await callback.answer()


@router.callback_query(AdminCB.filter(F.s == "sty"))
async def cb_stylist_stats(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    s = await StatsService(session).stylist()
    text = t(
        "adm.stylist_stats",
        model=h(settings.stylist_model),
        enabled=t("adm.enabled") if settings.stylist_available else t("adm.disabled"),
        day_requests=s.day_requests,
        day_cost=f"${s.day_cost:.4f}",
        month_requests=s.month_requests,
        month_cost=f"${s.month_cost:.4f}",
        month_errors=s.month_errors,
        in_tokens=s.in_tokens,
        out_tokens=s.out_tokens,
        cache_tokens=s.cache_tokens,
        looks=s.looks,
        looks_carted=s.looks_carted,
        looks_ordered=s.looks_ordered,
    )
    await render(callback, text, back_kb(AdminCB(s="menu")))
    await callback.answer()


# ---------- Рассылки ----------
@router.callback_query(AdminCB.filter((F.s == "bc") & (F.a == "")))
async def cb_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    await state.update_data(bc={})
    await render(callback, t("adm.bc_segment"), segment_kb())
    await callback.answer()


async def _bc_update(state: FSMContext, **values) -> dict:
    data = dict((await state.get_data()).get("bc") or {})
    data.update(values)
    await state.update_data(bc=data)
    return data


@router.callback_query(AdminCB.filter((F.s == "bc") & (F.a == "seg")))
async def cb_bc_segment(
    callback: CallbackQuery, callback_data: AdminCB, state: FSMContext, session: AsyncSession
) -> None:
    if callback_data.v not in set(Segment):
        await callback.answer()
        return
    await _bc_update(state, segment=callback_data.v, category_id=None)
    if callback_data.v == Segment.CATEGORY:
        categories = await CatalogRepository(session).categories()
        await render(callback, t("adm.bc_category"), bc_category_kb(categories))
    else:
        await state.set_state(AdminBroadcastStates.content)
        await render(callback, t("adm.bc_text"), cancel_admin_kb())
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "bc") & (F.a == "cat")))
async def cb_bc_category(
    callback: CallbackQuery, callback_data: AdminCB, state: FSMContext
) -> None:
    await _bc_update(state, category_id=callback_data.id)
    await state.set_state(AdminBroadcastStates.content)
    await render(callback, t("adm.bc_text"), cancel_admin_kb())
    await callback.answer()


@router.message(AdminBroadcastStates.content, F.photo | F.text)
async def msg_bc_content(message: Message, state: FSMContext) -> None:
    if message.photo:
        text = message.html_text if message.caption else ""
        await _bc_update(state, text=text, photo=message.photo[-1].file_id)
    else:
        await _bc_update(state, text=message.html_text, photo=None)
    await state.set_state(AdminBroadcastStates.product)
    await message.answer(t("adm.bc_product"), reply_markup=cancel_admin_kb())


@router.message(AdminBroadcastStates.product, F.text)
async def msg_bc_product(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    text = message.text.strip()
    product_id = None
    if text != "-":
        product = (
            await CatalogRepository(session).get_product(int(text)) if text.isdigit() else None
        )
        if product is None:
            await message.answer(t("common.not_found"))
            return
        product_id = product.id
    data = await _bc_update(state, product_id=product_id)
    await state.set_state(None)
    preview = Broadcast(
        segment=data["segment"],
        text=data.get("text") or "",
        photo=data.get("photo"),
        product_id=product_id,
        created_by=message.from_user.id,
    )
    try:
        await send_broadcast_message(bot, message.chat.id, preview)
    except TelegramAPIError as exc:
        await message.answer(f"{t('common.error')}\n<code>{h(exc)}</code>")
        return
    count = len(await segment_user_ids(session, data["segment"], data.get("category_id")))
    await message.answer(t("adm.bc_preview", count=count), reply_markup=bc_confirm_kb())


async def _create_broadcast(
    session: AsyncSession, state: FSMContext, admin_id: int, scheduled_at: datetime | None
) -> Broadcast | None:
    data = (await state.get_data()).get("bc") or {}
    if not data.get("segment") or not (data.get("text") or data.get("photo")):
        return None
    broadcast = await BroadcastService(session).create(
        created_by=admin_id,
        segment=data["segment"],
        text=data.get("text") or "",
        photo=data.get("photo"),
        product_id=data.get("product_id"),
        category_id=data.get("category_id"),
        scheduled_at=scheduled_at,
    )
    await session.commit()
    await state.update_data(bc=None)
    return broadcast


@router.callback_query(AdminCB.filter((F.s == "bc") & (F.a == "send")))
async def cb_bc_send(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    broadcast = await _create_broadcast(session, state, callback.from_user.id, None)
    if broadcast is None:
        await callback.answer(t("common.error"), show_alert=True)
        return
    count = len(await segment_user_ids(session, broadcast.segment, broadcast.category_id))
    runner = BroadcastRunner(bot, session_factory, settings.broadcast_rate_per_sec)
    task = asyncio.create_task(runner.run(broadcast.id))
    _background.add(task)
    task.add_done_callback(_background.discard)
    await render(
        callback, t("adm.bc_started", id=broadcast.id, count=count), back_kb(AdminCB(s="menu"))
    )
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "bc") & (F.a == "schedule")))
async def cb_bc_schedule(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminBroadcastStates.schedule)
    await render(callback, t("adm.bc_enter_time"), cancel_admin_kb())
    await callback.answer()


@router.message(AdminBroadcastStates.schedule, F.text)
async def msg_bc_schedule(
    message: Message, state: FSMContext, session: AsyncSession, settings: Settings
) -> None:
    try:
        local = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M").replace(
            tzinfo=ZoneInfo(settings.timezone)
        )
    except ValueError:
        await message.answer(t("adm.bad_value"))
        return
    when_utc = local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    broadcast = await _create_broadcast(session, state, message.from_user.id, when_utc)
    await state.set_state(None)
    if broadcast is None:
        await message.answer(t("common.error"))
        return
    await message.answer(
        t("adm.bc_scheduled", id=broadcast.id, when=local_dt(when_utc, settings.timezone)),
        reply_markup=back_kb(AdminCB(s="menu")),
    )

"""Карточки клиентов: просмотр, смена статуса."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from app import keyboards
from app.constants import CLIENT_STATUSES
from app.context import AppContext
from app.handlers.common import edit_or_send
from app.services import clients as client_service
from app.services.profile import get_profile
from app.services.tasks import NotFoundError

router = Router(name="clients")


@router.callback_query(F.data.startswith("client:view:"))
async def cb_client_view(call: CallbackQuery, app: AppContext, bot: Bot) -> None:
    client_id = int(call.data.rsplit(":", 1)[1])
    await call.answer()
    try:
        client = await client_service.get_client(app.sf, client_id)
    except NotFoundError:
        await call.message.answer("Клиент не найден — возможно, уже удалён.")
        return
    profile = await get_profile(app.sf)
    text = client_service.format_client_card(client, profile.timezone)
    await edit_or_send(
        bot, call.message.chat.id, call.message.message_id, text, keyboards.client_card(client)
    )


@router.callback_query(F.data.startswith("client:status:"))
async def cb_client_status(call: CallbackQuery, bot: Bot) -> None:
    client_id = int(call.data.rsplit(":", 1)[1])
    await call.answer()
    await edit_or_send(
        bot,
        call.message.chat.id,
        call.message.message_id,
        "Выберите новый статус сделки:",
        keyboards.client_statuses(client_id),
    )


@router.callback_query(F.data.startswith("client:setstatus:"))
async def cb_client_set_status(call: CallbackQuery, app: AppContext, bot: Bot) -> None:
    _, _, client_id_s, status = call.data.split(":")
    if status not in CLIENT_STATUSES:
        await call.answer("Неизвестный статус", show_alert=True)
        return
    try:
        client = await client_service.update_client(app.sf, int(client_id_s), status=status)
    except NotFoundError:
        await call.answer("Клиент не найден", show_alert=True)
        return
    await call.answer(f"Статус: {CLIENT_STATUSES[status]}")
    client = await client_service.get_client(app.sf, client.id)
    profile = await get_profile(app.sf)
    await edit_or_send(
        bot,
        call.message.chat.id,
        call.message.message_id,
        client_service.format_client_card(client, profile.timezone),
        keyboards.client_card(client),
    )

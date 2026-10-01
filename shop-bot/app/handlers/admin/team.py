"""Админка: список администраторов, добавление и удаление прямо в боте."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, MessageOriginUser, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import confirm_delete_kb, pick_user_kb, team_kb
from app.keyboards.callbacks import AdminCB
from app.services.admins import AdminRegistry
from app.states import AdminTeamStates
from app.texts import t
from app.utils.telegram import render

router = Router(name="admin_team")


def _team_text(admins: AdminRegistry) -> str:
    lines = [
        f"• <code>{user_id}</code>{' 🔒' if user_id in admins.env_ids else ''}"
        for user_id in admins.ids
    ]
    return t("adm.team_title", admins="\n".join(lines))


def _removable(admins: AdminRegistry) -> list[int]:
    return admins.db_ids if len(admins.ids) > 1 else []


@router.callback_query(AdminCB.filter((F.s == "team") & (F.a == "")))
async def cb_team(callback: CallbackQuery, state: FSMContext, admins: AdminRegistry) -> None:
    await state.set_state(None)
    await render(callback, _team_text(admins), team_kb(_removable(admins)))
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "team") & (F.a == "add")))
async def cb_team_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminTeamStates.add)
    await callback.message.answer(t("adm.add_admin_prompt"), reply_markup=pick_user_kb())
    await callback.answer()


def extract_user_id(message: Message) -> int | None:
    """ID нового админа: выбор из контактов, пересланное сообщение или число."""
    if message.users_shared and message.users_shared.users:
        return message.users_shared.users[0].user_id
    if isinstance(message.forward_origin, MessageOriginUser):
        return message.forward_origin.sender_user.id
    if message.contact and message.contact.user_id:
        return message.contact.user_id
    text = (message.text or "").strip()
    return int(text) if text.isdigit() and 4 <= len(text) <= 15 else None


@router.message(AdminTeamStates.add, F.text == t("common.cancel"))
async def msg_team_cancel(message: Message, state: FSMContext, admins: AdminRegistry) -> None:
    await state.set_state(None)
    await message.answer(t("common.cancelled"), reply_markup=ReplyKeyboardRemove())
    await message.answer(_team_text(admins), reply_markup=team_kb(_removable(admins)))


@router.message(AdminTeamStates.add)
async def msg_team_add(
    message: Message, state: FSMContext, session: AsyncSession, admins: AdminRegistry
) -> None:
    user_id = extract_user_id(message)
    if user_id is None:
        await message.answer(t("adm.bad_admin"), reply_markup=pick_user_kb())
        return
    await state.set_state(None)
    added = await admins.add(session, user_id, added_by=message.from_user.id)
    text = t("adm.admin_added", user_id=user_id) if added else t("adm.admin_exists")
    await message.answer(text, reply_markup=ReplyKeyboardRemove())
    await message.answer(_team_text(admins), reply_markup=team_kb(_removable(admins)))


@router.callback_query(AdminCB.filter((F.s == "team") & (F.a == "del")))
async def cb_team_del(callback: CallbackQuery, callback_data: AdminCB) -> None:
    await render(
        callback,
        t("adm.confirm_remove_admin", user_id=callback_data.id),
        confirm_delete_kb(AdminCB(s="team", a="del_yes", id=callback_data.id), AdminCB(s="team")),
    )
    await callback.answer()


@router.callback_query(AdminCB.filter((F.s == "team") & (F.a == "del_yes")))
async def cb_team_del_yes(
    callback: CallbackQuery,
    callback_data: AdminCB,
    session: AsyncSession,
    admins: AdminRegistry,
) -> None:
    removed = await admins.remove(session, callback_data.id)
    await callback.answer(
        t("adm.admin_removed") if removed else t("adm.admin_cannot_remove"), show_alert=True
    )
    await render(callback, _team_text(admins), team_kb(_removable(admins)))

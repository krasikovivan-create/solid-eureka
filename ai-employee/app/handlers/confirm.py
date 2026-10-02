"""Удаление с подтверждением: задачи, клиенты, документы, факты."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app import keyboards
from app.context import AppContext
from app.services import clients as client_service
from app.services import memory as memory_service
from app.services import tasks as task_service
from app.services.tasks import NotFoundError
from app.services.textutils import esc

router = Router(name="confirm")

KINDS = {"task", "client", "document", "fact"}


async def describe(app: AppContext, kind: str, object_id: int, user_id: int) -> str:
    if kind == "task":
        task = await task_service.get_task(app.sf, object_id)
        if task.user_id != user_id:
            raise NotFoundError("Задача не найдена")
        return f"задачу #{task.id} «{esc(task.title)}»"
    if kind == "client":
        client = await client_service.get_client(app.sf, object_id)
        return f"клиента #{client.id} «{esc(client.company)}» вместе с историей"
    if kind == "document":
        doc = await app.kb.get_document(object_id)
        return f"документ #{doc.id} «{esc(doc.filename)}»"
    fact = await memory_service.get_fact(app.sf, object_id)
    return f"факт #{fact.id} «{esc(fact.content[:80])}»"


async def perform_delete(app: AppContext, kind: str, object_id: int, user_id: int) -> str:
    if kind == "task":
        task = await task_service.get_task(app.sf, object_id)
        if task.user_id != user_id:
            raise NotFoundError("Задача не найдена")
        await task_service.delete_task(app.sf, object_id)
        if app.scheduler is not None:
            app.scheduler.unschedule_task_reminder(object_id)
        return f"🗑 Задача «{esc(task.title)}» удалена."
    if kind == "client":
        client = await client_service.delete_client(app.sf, object_id)
        return f"🗑 Клиент «{esc(client.company)}» удалён."
    if kind == "document":
        doc = await app.kb.delete_document(object_id)
        return f"🗑 Документ «{esc(doc.filename)}» удалён из базы знаний."
    fact = await memory_service.delete_fact(app.sf, object_id)
    return f"🗑 Факт удалён: {esc(fact.content[:100])}"


def _parse(data: str) -> tuple[str, int] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[1] not in KINDS or not parts[2].isdigit():
        return None
    return parts[1], int(parts[2])


@router.callback_query(F.data.startswith("del:"))
async def cb_ask_delete(call: CallbackQuery, app: AppContext) -> None:
    parsed = _parse(call.data)
    if parsed is None:
        await call.answer()
        return
    kind, object_id = parsed
    try:
        label = await describe(app, kind, object_id, call.from_user.id)
    except NotFoundError:
        await call.answer("Уже удалено", show_alert=True)
        return
    await call.answer()
    await call.message.answer(
        f"🗑 Удалить {label}?", reply_markup=keyboards.confirm_delete(kind, object_id)
    )


@router.callback_query(F.data.startswith("delok:"))
async def cb_confirm_delete(call: CallbackQuery, app: AppContext) -> None:
    parsed = _parse(call.data)
    if parsed is None:
        await call.answer()
        return
    kind, object_id = parsed
    try:
        text = await perform_delete(app, kind, object_id, call.from_user.id)
    except NotFoundError:
        await call.answer("Уже удалено", show_alert=True)
        await call.message.edit_reply_markup(reply_markup=None)
        return
    await call.answer("Удалено")
    await call.message.edit_text(text)


@router.callback_query(F.data == "delno")
async def cb_cancel_delete(call: CallbackQuery) -> None:
    await call.answer("Отменено")
    await call.message.edit_text("Удаление отменено 👌")

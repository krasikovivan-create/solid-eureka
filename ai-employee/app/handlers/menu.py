"""Главное меню и разделы: задачи, клиенты, база знаний, тексты, память, расходы."""

from __future__ import annotations

from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards, texts
from app.context import AppContext
from app.handlers.common import edit_or_send, send_html
from app.services import clients as client_service
from app.services import memory as memory_service
from app.services import reports
from app.services import tasks as task_service
from app.services import usage as usage_service
from app.services.profile import get_profile
from app.services.textutils import esc
from app.services.timeutils import now_local, now_utc, parse_local_datetime

router = Router(name="menu")


# --- Тексты разделов ---------------------------------------------------------


async def tasks_view(app: AppContext, user_id: int, mode: str = "open") -> tuple[str, object]:
    profile = await get_profile(app.sf)
    tz = profile.timezone
    if mode == "today":
        tasks = await task_service.list_tasks(app.sf, user_id, tz, period="today")
        title = "📅 Задачи на сегодня"
    elif mode == "overdue":
        tasks = await task_service.list_tasks(app.sf, user_id, tz, period="overdue")
        title = "⚠️ Просроченные задачи"
    elif mode == "done":
        tasks = await task_service.list_tasks(app.sf, user_id, tz, status="done", limit=20)
        title = "✔️ Выполненные задачи"
    else:
        tasks = await task_service.list_tasks(app.sf, user_id, tz)
        title = "📋 Открытые задачи"
    lines = [f"<b>{title}</b> ({len(tasks)})", ""]
    if tasks:
        lines += [task_service.format_task(t, tz) for t in tasks[:30]]
        if len(tasks) > 30:
            lines.append(f"… и ещё {len(tasks) - 30}")
    else:
        lines.append(
            "Пусто. Чтобы добавить задачу, просто напишите: «Напомни завтра в 10 позвонить Иванову»."
        )
    open_tasks = tasks if mode != "done" else []
    return "\n".join(lines), keyboards.tasks_list(open_tasks)


async def clients_view(app: AppContext) -> tuple[str, object]:
    clients = await client_service.find_clients(app.sf, limit=20)
    total = await client_service.count_clients(app.sf)
    if not clients:
        return (
            "👥 <b>Клиенты</b>\n\nПока пусто. Напишите, например: "
            "«Добавь клиента ООО Ромашка, ритейл, контакт Пётр +7 900 000-00-00».",
            keyboards.back_to_menu(),
        )
    text = f"👥 <b>Клиенты</b> (всего {total}, показаны последние)\nНажмите на клиента, чтобы открыть карточку."
    return text, keyboards.clients_list(clients)


async def kb_view(app: AppContext) -> tuple[str, object]:
    docs = await app.kb.list_documents()
    lines = ["📚 <b>База знаний</b>", ""]
    if docs:
        for d, n in docs:
            lines.append(f"📄 #{d.id} {esc(d.filename)} — {n} фрагм.")
        lines += ["", "Нажмите на документ ниже, чтобы удалить его."]
    else:
        lines.append("Документов пока нет.")
    lines += ["", texts.KB_HINT]
    return "\n".join(lines), keyboards.documents_list([d for d, _ in docs])


async def memory_view(app: AppContext, user_id: int) -> str:
    facts = await memory_service.list_facts(app.sf, limit=50)
    summary = await memory_service.get_summary(app.sf, user_id)
    lines = ["🧠 <b>Память</b>", "", "<b>Важные факты:</b>"]
    lines.append(esc(memory_service.format_facts(facts)))
    if summary and summary.summary:
        lines += ["", "<b>Резюме прошлых разговоров:</b>", esc(summary.summary[:1500])]
    lines += [
        "",
        "Чтобы я запомнил факт, напишите: «Запомни: …». Удалить — «Забудь факт №…».",
    ]
    return "\n".join(lines)


# --- Команды ---------------------------------------------------------------------


@router.message(Command("tasks"))
async def cmd_tasks(message: Message, app: AppContext) -> None:
    text, kb = await tasks_view(app, message.from_user.id)
    await send_html(message.bot, message.chat.id, text, kb)


@router.message(Command("today"))
async def cmd_today(message: Message, app: AppContext) -> None:
    text = await reports.morning_plan(app.sf, message.from_user.id)
    await send_html(message.bot, message.chat.id, text, keyboards.back_to_menu())


@router.message(Command("clients"))
async def cmd_clients(message: Message, app: AppContext) -> None:
    text, kb = await clients_view(app)
    await send_html(message.bot, message.chat.id, text, kb)


@router.message(Command("kb"))
async def cmd_kb(message: Message, app: AppContext) -> None:
    text, kb = await kb_view(app)
    await send_html(message.bot, message.chat.id, text, kb)


@router.message(Command("usage"))
async def cmd_usage(message: Message, app: AppContext) -> None:
    profile = await get_profile(app.sf)
    s = app.settings
    text = await usage_service.usage_report(
        app.sf, profile.timezone, s.daily_budget_usd, s.monthly_budget_usd
    )
    await message.answer(text, reply_markup=keyboards.back_to_menu())


# --- Кнопки меню -----------------------------------------------------------------


@router.callback_query(F.data.startswith("menu:"))
async def cb_menu(call: CallbackQuery, app: AppContext, bot: Bot, state: FSMContext) -> None:
    section = call.data.split(":", 1)[1]
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    user_id = call.from_user.id
    await call.answer()
    if section == "main":
        await state.clear()
        await edit_or_send(bot, chat_id, msg_id, "Главное меню 👇", keyboards.main_menu())
    elif section == "tasks":
        text, kb = await tasks_view(app, user_id)
        await edit_or_send(bot, chat_id, msg_id, text, kb)
    elif section == "today":
        text = await reports.morning_plan(app.sf, user_id)
        await edit_or_send(bot, chat_id, msg_id, text, keyboards.back_to_menu())
    elif section == "clients":
        text, kb = await clients_view(app)
        await edit_or_send(bot, chat_id, msg_id, text, kb)
    elif section == "pipeline":
        data = await client_service.pipeline(app.sf)
        await edit_or_send(
            bot, chat_id, msg_id, client_service.format_pipeline(data), keyboards.back_to_menu()
        )
    elif section == "audit":
        from app.handlers.audit import audit_menu_view

        text, kb = await audit_menu_view(app)
        await edit_or_send(bot, chat_id, msg_id, text, kb)
    elif section == "kb":
        text, kb = await kb_view(app)
        await edit_or_send(bot, chat_id, msg_id, text, kb)
    elif section == "texts":
        await edit_or_send(bot, chat_id, msg_id, texts.TEXTS_HINT, keyboards.back_to_menu())
    elif section == "memory":
        await edit_or_send(
            bot, chat_id, msg_id, await memory_view(app, user_id), keyboards.memory_menu()
        )
    elif section == "usage":
        profile = await get_profile(app.sf)
        s = app.settings
        text = await usage_service.usage_report(
            app.sf, profile.timezone, s.daily_budget_usd, s.monthly_budget_usd
        )
        await edit_or_send(bot, chat_id, msg_id, text, keyboards.back_to_menu())
    elif section == "settings":
        from app.handlers.settings import settings_text

        profile = await get_profile(app.sf)
        await edit_or_send(
            bot, chat_id, msg_id, settings_text(profile), keyboards.settings_menu(profile)
        )
    elif section == "help":
        await edit_or_send(bot, chat_id, msg_id, texts.HELP, keyboards.back_to_menu())


@router.callback_query(F.data.startswith("tasks:"))
async def cb_tasks_filter(call: CallbackQuery, app: AppContext, bot: Bot) -> None:
    mode = call.data.split(":", 1)[1]
    await call.answer()
    text, kb = await tasks_view(app, call.from_user.id, mode)
    await edit_or_send(bot, call.message.chat.id, call.message.message_id, text, kb)


@router.callback_query(F.data.startswith("task:done:"))
async def cb_task_done(call: CallbackQuery, app: AppContext) -> None:
    task_id = int(call.data.rsplit(":", 1)[1])
    try:
        task = await task_service.get_task(app.sf, task_id)
    except task_service.NotFoundError:
        await call.answer("Задача уже удалена", show_alert=True)
        return
    if task.user_id != call.from_user.id:
        await call.answer("Это не ваша задача", show_alert=True)
        return
    await task_service.update_task(app.sf, task_id, status="done")
    if app.scheduler is not None:
        app.scheduler.unschedule_task_reminder(task_id)
    await call.answer("✅ Отмечено как выполненное")
    await call.message.answer(f"✅ Готово: {esc(task.title)}")


@router.callback_query(F.data.startswith("snooze:"))
async def cb_snooze(call: CallbackQuery, app: AppContext) -> None:
    _, task_id_s, amount = call.data.split(":")
    task_id = int(task_id_s)
    profile = await get_profile(app.sf)
    if amount == "tomorrow":
        tomorrow = now_local(profile.timezone).date() + timedelta(days=1)
        when = parse_local_datetime(
            f"{tomorrow.isoformat()}T{profile.morning_time}", profile.timezone
        )
    else:
        when = now_utc() + timedelta(minutes=int(amount))
    try:
        task = await task_service.update_task(app.sf, task_id, remind_at=when)
    except task_service.NotFoundError:
        await call.answer("Задача не найдена", show_alert=True)
        return
    if app.scheduler is not None:
        app.scheduler.schedule_task_reminder(task)
    from app.services.timeutils import fmt_dt

    await call.answer("⏰ Напоминание перенесено")
    await call.message.answer(f"⏰ Напомню {fmt_dt(when, profile.timezone)}: {esc(task.title)}")


@router.callback_query(F.data == "memory:clear")
async def cb_memory_clear(call: CallbackQuery, app: AppContext) -> None:
    await memory_service.clear_history(app.sf, call.from_user.id)
    await call.answer("История диалога очищена")
    await call.message.answer("🧹 История диалога очищена. Факты, задачи и клиенты сохранены.")

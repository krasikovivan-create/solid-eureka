"""Аудит процессов клиента: интервью по шагам, отчёт, КП."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from app import keyboards
from app.agent import workflows
from app.agent.llm import LLMError
from app.context import AppContext
from app.database.models import Audit
from app.handlers.common import send_html
from app.services import audit as audit_service
from app.services import clients as client_service
from app.services import proposals as proposal_service
from app.services.tasks import NotFoundError
from app.services.textutils import esc

log = logging.getLogger(__name__)
router = Router(name="audit")


class AuditInput(StatesGroup):
    waiting_client = State()


async def audit_menu_view(app: AppContext) -> tuple[str, object]:
    audits = await audit_service.list_audits(app.sf)
    lines = [
        "🔍 <b>Аудит процессов клиента</b>",
        "",
        f"Я задам {len(audit_service.AUDIT_QUESTIONS)} вопросов о бизнесе клиента, а затем "
        "подготовлю отчёт: карту рутинных процессов, что автоматизировать ИИ, сложность, сроки "
        "и экономию часов в месяц. По отчёту сделаю КП в DOCX.",
    ]
    if audits:
        lines += ["", "<b>Последние аудиты:</b>"]
        status = {"in_progress": "идёт", "completed": "готов", "cancelled": "прерван"}
        for a in audits[:8]:
            lines.append(f"• #{a.id} {esc(a.client_name)} — {status.get(a.status, a.status)}")
    return "\n".join(lines), keyboards.audit_menu(audits)


async def send_audit_question(
    bot: Bot, chat_id: int, app: AppContext, audit_id: int, intro: bool = False
) -> None:
    audit = await audit_service.get_audit(app.sf, audit_id)
    question = audit_service.current_question(audit)
    if question is None:
        return
    head = ""
    if intro:
        head = (
            f"🔍 Начинаем аудит для <b>{esc(audit.client_name)}</b>. Отвечайте своими словами — "
            "можно коротко. Если ответа нет — «Пропустить».\n\n"
        )
    await bot.send_message(
        chat_id,
        f"{head}<b>{audit_service.question_header(audit)}</b>\n{esc(question)}",
        reply_markup=keyboards.audit_question(),
    )


async def finish_audit(bot: Bot, chat_id: int, app: AppContext, audit: Audit, user_id: int) -> None:
    await bot.send_message(chat_id, "✅ Интервью завершено. Готовлю отчёт — это займёт до минуты…")
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=chat_id):
            audit = await workflows.generate_audit_report(app, audit.id, user_id)
    except LLMError as exc:
        await bot.send_message(
            chat_id,
            f"{esc(exc.user_message)}\n\nОтветы сохранены. Нажмите «Повторить», когда будете готовы.",
            reply_markup=_retry_kb(audit.id),
        )
        return
    await send_html(
        bot, chat_id, audit_service.format_report(audit), keyboards.audit_done(audit.id)
    )


def _retry_kb(audit_id: int):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔁 Повторить отчёт", callback_data=f"audit:retry:{audit_id}"
                )
            ]
        ]
    )


async def handle_audit_answer(
    bot: Bot, chat_id: int, app: AppContext, audit: Audit, text: str | None, user_id: int
) -> None:
    audit = await audit_service.answer(app.sf, audit.id, text)
    if audit_service.is_interview_finished(audit):
        await finish_audit(bot, chat_id, app, audit, user_id)
    else:
        await send_audit_question(bot, chat_id, app, audit.id)


async def begin_audit(
    bot: Bot, chat_id: int, app: AppContext, user_id: int, name: str, client_id: int | None
) -> None:
    if client_id is None:
        try:
            client = await client_service.resolve_client(app.sf, None, name)
            client_id, name = client.id, client.company
        except (NotFoundError, ValueError):
            client_id = None
    audit = await audit_service.start_audit(app.sf, user_id, name, client_id)
    await send_audit_question(bot, chat_id, app, audit.id, intro=True)


@router.message(Command("audit"))
async def cmd_audit(message: Message, app: AppContext) -> None:
    text, kb = await audit_menu_view(app)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "audit:new")
async def cb_audit_new(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(AuditInput.waiting_client)
    await call.message.answer(
        "Для какого клиента проводим аудит? Напишите название компании.",
        reply_markup=keyboards.cancel_input(),
    )


@router.message(StateFilter(AuditInput.waiting_client), F.text)
async def on_audit_client(message: Message, state: FSMContext, app: AppContext, bot: Bot) -> None:
    await state.clear()
    await begin_audit(bot, message.chat.id, app, message.from_user.id, message.text.strip(), None)


@router.callback_query(F.data.startswith("client:audit:"))
async def cb_client_audit(call: CallbackQuery, app: AppContext, bot: Bot) -> None:
    client_id = int(call.data.rsplit(":", 1)[1])
    await call.answer()
    try:
        client = await client_service.get_client(app.sf, client_id)
    except NotFoundError:
        await call.message.answer("Клиент не найден.")
        return
    await begin_audit(bot, call.message.chat.id, app, call.from_user.id, client.company, client.id)


@router.callback_query(F.data == "audit:skip")
async def cb_audit_skip(call: CallbackQuery, app: AppContext, bot: Bot) -> None:
    audit = await audit_service.get_active_audit(app.sf, call.from_user.id)
    await call.answer()
    if audit is None:
        await call.message.answer("Сейчас нет активного аудита.")
        return
    await call.message.edit_reply_markup(reply_markup=None)
    await handle_audit_answer(bot, call.message.chat.id, app, audit, None, call.from_user.id)


@router.callback_query(F.data == "audit:stop")
async def cb_audit_stop(call: CallbackQuery, app: AppContext) -> None:
    audit = await audit_service.get_active_audit(app.sf, call.from_user.id)
    await call.answer()
    if audit is not None:
        await audit_service.cancel_audit(app.sf, audit.id)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("⏹ Аудит прерван.", reply_markup=keyboards.main_menu())


@router.callback_query(F.data.startswith("audit:retry:"))
async def cb_audit_retry(call: CallbackQuery, app: AppContext, bot: Bot) -> None:
    audit_id = int(call.data.rsplit(":", 1)[1])
    await call.answer()
    try:
        audit = await audit_service.get_audit(app.sf, audit_id)
    except NotFoundError:
        await call.message.answer("Аудит не найден.")
        return
    await finish_audit(bot, call.message.chat.id, app, audit, call.from_user.id)


@router.callback_query(F.data.startswith("audit:report:"))
async def cb_audit_report(call: CallbackQuery, app: AppContext, bot: Bot) -> None:
    audit_id = int(call.data.rsplit(":", 1)[1])
    await call.answer()
    try:
        audit = await audit_service.get_audit(app.sf, audit_id)
    except NotFoundError:
        await call.message.answer("Аудит не найден.")
        return
    if not audit.report:
        await call.message.answer("Отчёт по этому аудиту ещё не готов.")
        return
    await send_html(
        bot,
        call.message.chat.id,
        audit_service.format_report(audit),
        keyboards.audit_done(audit.id),
    )


@router.callback_query(F.data.startswith("audit:proposal:"))
async def cb_audit_proposal(call: CallbackQuery, app: AppContext, bot: Bot) -> None:
    audit_id = int(call.data.rsplit(":", 1)[1])
    chat_id = call.message.chat.id
    await call.answer("Готовлю КП…")
    await bot.send_message(chat_id, "📄 Готовлю коммерческое предложение — до минуты…")
    try:
        async with ChatActionSender.upload_document(bot=bot, chat_id=chat_id):
            proposal, data, filename = await workflows.generate_proposal(
                app, audit_id, call.from_user.id
            )
    except (LLMError, ValueError, NotFoundError) as exc:
        msg = exc.user_message if isinstance(exc, LLMError) else str(exc)
        await bot.send_message(chat_id, f"⚠️ {esc(msg)}")
        return
    content = proposal.content
    await bot.send_document(
        chat_id,
        BufferedInputFile(data, filename=filename),
        caption=(
            f"📄 <b>{esc(content.get('title', 'Коммерческое предложение'))}</b>\n"
            f"Сроки: ~{content.get('total_weeks', 0):g} нед. · "
            f"Стоимость: {proposal_service.money(proposal.total_cost)}"
        )[:1000],
    )

"""/start, онбординг, /help, /menu, /cancel, /new."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards, texts
from app.constants import COMMUNICATION_STYLES
from app.context import AppContext
from app.services import memory as memory_service
from app.services import profile as profile_service

router = Router(name="start")


async def send_onboarding_step(bot: Bot, chat_id: int, step: int) -> None:
    _, question = texts.ONBOARDING_STEPS[step]
    markup = keyboards.style_choice() if step == len(texts.ONBOARDING_STEPS) - 1 else None
    await bot.send_message(chat_id, question, reply_markup=markup)


async def save_onboarding_answer(bot: Bot, chat_id: int, app: AppContext, value: str) -> None:
    profile = await profile_service.get_profile(app.sf)
    step = profile.onboarding_step
    if profile.onboarded or step >= len(texts.ONBOARDING_STEPS):
        return
    value = value.strip()
    if not value:
        await bot.send_message(chat_id, "Напишите ответ текстом, пожалуйста 🙂")
        return
    field, _ = texts.ONBOARDING_STEPS[step]
    limits = {"company_name": 200, "agent_name": 100, "agent_role": 200}
    if field in limits and len(value) > limits[field]:
        await bot.send_message(chat_id, f"Слишком длинно — уложитесь в {limits[field]} символов.")
        return
    step += 1
    finished = step >= len(texts.ONBOARDING_STEPS)
    profile = await profile_service.update_profile(
        app.sf, **{field: value, "onboarding_step": step, "onboarded": finished}
    )
    if not finished:
        await send_onboarding_step(bot, chat_id, step)
        return
    if app.scheduler is not None:
        await app.scheduler.reschedule_daily()
    await bot.send_message(
        chat_id,
        texts.onboarding_done(
            profile.agent_name, profile.agent_role, profile.morning_time, profile.evening_time
        ),
        reply_markup=keyboards.main_menu(),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, app: AppContext, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    profile = await profile_service.get_profile(app.sf)
    if not profile.onboarded:
        await send_onboarding_step(bot, message.chat.id, profile.onboarding_step)
        return
    await message.answer(
        texts.welcome_back(profile.agent_name, profile.company_name),
        reply_markup=keyboards.main_menu(),
    )


@router.callback_query(F.data.startswith("style:"))
async def cb_style(call: CallbackQuery, app: AppContext, bot: Bot, state: FSMContext) -> None:
    key = call.data.split(":", 1)[1]
    style = COMMUNICATION_STYLES.get(key)
    await call.answer()
    if style is None:
        return
    profile = await profile_service.get_profile(app.sf)
    if profile.onboarded:
        await state.clear()
        await profile_service.update_profile(app.sf, communication_style=style)
        await call.message.answer(f"✅ Стиль общения обновлён:\n{style}")
        return
    await save_onboarding_answer(bot, call.message.chat.id, app, style)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP, reply_markup=keyboards.back_to_menu())


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Главное меню 👇", reply_markup=keyboards.main_menu())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, app: AppContext) -> None:
    from app.services import audit as audit_service

    await state.clear()
    active = await audit_service.get_active_audit(app.sf, message.from_user.id)
    if active is not None:
        await audit_service.cancel_audit(app.sf, active.id)
        await message.answer("⏹ Аудит прерван.", reply_markup=keyboards.main_menu())
        return
    await message.answer("Действие отменено.", reply_markup=keyboards.main_menu())


@router.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext, app: AppContext) -> None:
    await state.clear()
    await memory_service.clear_history(app.sf, message.from_user.id)
    await message.answer(
        "🧹 Начали диалог заново. Факты в памяти, задачи и клиенты сохранены.",
        reply_markup=keyboards.main_menu(),
    )

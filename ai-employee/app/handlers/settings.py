"""/settings: профиль компании и расписание сводок."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app import keyboards
from app.context import AppContext
from app.database.models import CompanyProfile
from app.handlers.common import edit_or_send
from app.services import profile as profile_service
from app.services.textutils import esc

router = Router(name="settings")


class SettingsInput(StatesGroup):
    waiting_value = State()


FIELD_PROMPTS = {
    "company_name": "Введите новое название компании:",
    "company_description": "Опишите компанию (чем занимаетесь, для кого, чем отличаетесь):",
    "agent_name": "Как зовут виртуального сотрудника?",
    "agent_role": "Какая у сотрудника должность?",
    "communication_style": "Опишите стиль общения своими словами или выберите вариант:",
    "morning_time": "Во сколько присылать план дня? Формат ЧЧ:ММ, например 08:30",
    "evening_time": "Во сколько присылать итоги дня? Формат ЧЧ:ММ, например 19:00",
    "timezone": "Укажите часовой пояс, например: Europe/Moscow, Europe/Samara, "
    "Asia/Yekaterinburg, Asia/Novosibirsk, Asia/Vladivostok",
    "hourly_rate": "Ставка для расчёта стоимости в КП, ₽ за час (например 3500):",
}


def settings_text(p: CompanyProfile) -> str:
    def v(x: object) -> str:
        return esc(x) if x not in (None, "") else "—"

    return "\n".join(
        [
            "⚙️ <b>Настройки</b>",
            "",
            f"🏢 Компания: <b>{v(p.company_name)}</b>",
            f"📝 Описание: {v(p.company_description)}",
            f"👤 Сотрудник: {v(p.agent_name)}, {v(p.agent_role)}",
            f"🗣 Стиль: {v(p.communication_style)}",
            f"☀️ План дня: {p.morning_time} ({'вкл' if p.morning_enabled else 'выкл'})",
            f"🌙 Итоги дня: {p.evening_time} ({'вкл' if p.evening_enabled else 'выкл'})",
            f"🌍 Часовой пояс: {p.timezone}",
            f"💵 Ставка для КП: {p.hourly_rate} ₽/ч",
            "",
            "Нажмите, что изменить:",
        ]
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message, app: AppContext, state: FSMContext) -> None:
    await state.clear()
    profile = await profile_service.get_profile(app.sf)
    await message.answer(settings_text(profile), reply_markup=keyboards.settings_menu(profile))


@router.callback_query(F.data.startswith("set:"))
async def cb_set_field(call: CallbackQuery, state: FSMContext) -> None:
    field = call.data.split(":", 1)[1]
    await call.answer()
    if field not in FIELD_PROMPTS:
        return
    await state.set_state(SettingsInput.waiting_value)
    await state.update_data(field=field)
    markup = (
        keyboards.style_choice() if field == "communication_style" else keyboards.cancel_input()
    )
    await call.message.answer(FIELD_PROMPTS[field], reply_markup=markup)


@router.callback_query(F.data.startswith("toggle:"))
async def cb_toggle(call: CallbackQuery, app: AppContext, bot: Bot) -> None:
    field = call.data.split(":", 1)[1]
    if field not in ("morning_enabled", "evening_enabled"):
        await call.answer()
        return
    profile = await profile_service.get_profile(app.sf)
    profile = await profile_service.update_profile(app.sf, **{field: not getattr(profile, field)})
    if app.scheduler is not None:
        await app.scheduler.reschedule_daily()
    await call.answer("Сохранено")
    await edit_or_send(
        bot,
        call.message.chat.id,
        call.message.message_id,
        settings_text(profile),
        keyboards.settings_menu(profile),
    )


@router.callback_query(F.data == "input:cancel")
async def cb_input_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer("Отменено")
    await call.message.edit_text("Отменено 👌")


@router.message(StateFilter(SettingsInput.waiting_value), F.text)
async def on_setting_value(message: Message, state: FSMContext, app: AppContext) -> None:
    data = await state.get_data()
    field = data.get("field")
    value: object = message.text.strip()
    if field == "hourly_rate":
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        if not digits:
            await message.answer("Нужно число, например 3500")
            return
        value = int(digits)
    try:
        profile = await profile_service.update_profile(app.sf, **{field: value})
    except ValueError as exc:
        await message.answer(f"⚠️ {esc(exc)}\nПопробуйте ещё раз или нажмите «Отмена».")
        return
    await state.clear()
    if field in ("morning_time", "evening_time", "timezone") and app.scheduler is not None:
        await app.scheduler.reschedule_daily()
    await message.answer(
        "✅ Сохранено.\n\n" + settings_text(profile), reply_markup=keyboards.settings_menu(profile)
    )

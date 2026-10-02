"""Inline-клавиатуры."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.constants import CLIENT_STATUSES, COMMUNICATION_STYLES
from app.database.models import Client, CompanyProfile, Document, Task


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("📋 Задачи", "menu:tasks"), _btn("📅 План дня", "menu:today")],
            [_btn("👥 Клиенты", "menu:clients"), _btn("📊 Воронка", "menu:pipeline")],
            [_btn("🔍 Аудит", "menu:audit"), _btn("📚 База знаний", "menu:kb")],
            [_btn("✍️ Тексты", "menu:texts"), _btn("🧠 Память", "menu:memory")],
            [_btn("💰 Расходы", "menu:usage"), _btn("⚙️ Настройки", "menu:settings")],
            [_btn("❓ Помощь", "menu:help")],
        ]
    )


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("⬅️ Меню", "menu:main")]])


def style_choice() -> InlineKeyboardMarkup:
    labels = {
        "business": "💼 Деловой",
        "friendly": "😊 Дружелюбный",
        "brief": "⚡ Краткий",
        "expert": "🎓 Экспертный",
    }
    rows = [[_btn(labels[k], f"style:{k}")] for k in COMMUNICATION_STYLES]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tasks_list(tasks: list[Task]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in tasks[:15]:
        title = t.title if len(t.title) <= 28 else t.title[:27] + "…"
        kb.row(_btn(f"✅ {title}", f"task:done:{t.id}"), _btn("🗑", f"del:task:{t.id}"))
    kb.row(_btn("📅 Сегодня", "tasks:today"), _btn("⚠️ Просрочено", "tasks:overdue"))
    kb.row(_btn("✔️ Выполненные", "tasks:done"), _btn("⬅️ Меню", "menu:main"))
    return kb.as_markup()


def reminder(task: Task) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("✅ Сделано", f"task:done:{task.id}")],
            [
                _btn("⏰ +15 мин", f"snooze:{task.id}:15"),
                _btn("+1 час", f"snooze:{task.id}:60"),
                _btn("Завтра", f"snooze:{task.id}:tomorrow"),
            ],
        ]
    )


def clients_list(clients: list[Client]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for c in clients[:20]:
        status = CLIENT_STATUSES.get(c.status, c.status).split(" ")[0]
        kb.row(_btn(f"{status} {c.company}"[:60], f"client:view:{c.id}"))
    kb.row(_btn("📊 Воронка", "menu:pipeline"), _btn("⬅️ Меню", "menu:main"))
    return kb.as_markup()


def client_card(client: Client) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("🔄 Статус сделки", f"client:status:{client.id}")],
            [_btn("🔍 Провести аудит", f"client:audit:{client.id}")],
            [_btn("🗑 Удалить", f"del:client:{client.id}"), _btn("⬅️ Клиенты", "menu:clients")],
        ]
    )


def client_statuses(client_id: int) -> InlineKeyboardMarkup:
    rows = [
        [_btn(label, f"client:setstatus:{client_id}:{key}")]
        for key, label in CLIENT_STATUSES.items()
    ]
    rows.append([_btn("⬅️ Назад", f"client:view:{client_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def audit_question() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn("⏭ Пропустить", "audit:skip"), _btn("⏹ Прервать", "audit:stop")]]
    )


def audit_done(audit_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("📄 Сделать КП (DOCX)", f"audit:proposal:{audit_id}")],
            [_btn("⬅️ Меню", "menu:main")],
        ]
    )


def audit_menu(audits: list) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_btn("➕ Новый аудит", "audit:new"))
    for a in audits[:8]:
        if a.status == "completed":
            kb.row(
                _btn(f"📊 #{a.id} {a.client_name}"[:40], f"audit:report:{a.id}"),
                _btn("📄 КП", f"audit:proposal:{a.id}"),
            )
    kb.row(_btn("⬅️ Меню", "menu:main"))
    return kb.as_markup()


def documents_list(docs: list[Document]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for d in docs[:20]:
        kb.row(_btn(f"🗑 {d.filename}"[:60], f"del:document:{d.id}"))
    kb.row(_btn("⬅️ Меню", "menu:main"))
    return kb.as_markup()


def confirm_delete(kind: str, object_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("🗑 Да, удалить", f"delok:{kind}:{object_id}"),
                _btn("Отмена", "delno"),
            ]
        ]
    )


def settings_menu(profile: CompanyProfile) -> InlineKeyboardMarkup:
    m = "вкл" if profile.morning_enabled else "выкл"
    e = "вкл" if profile.evening_enabled else "выкл"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("🏢 Название", "set:company_name"), _btn("📝 Описание", "set:company_description")],
            [_btn("👤 Имя сотрудника", "set:agent_name"), _btn("💼 Должность", "set:agent_role")],
            [_btn("🗣 Стиль общения", "set:communication_style")],
            [_btn(f"☀️ План дня: {profile.morning_time}", "set:morning_time"),
             _btn(f"{m}", "toggle:morning_enabled")],
            [_btn(f"🌙 Итоги дня: {profile.evening_time}", "set:evening_time"),
             _btn(f"{e}", "toggle:evening_enabled")],
            [_btn("🌍 Часовой пояс", "set:timezone"), _btn("💵 Ставка ₽/ч", "set:hourly_rate")],
            [_btn("⬅️ Меню", "menu:main")],
        ]
    )  # fmt: skip


def cancel_input() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("Отмена", "input:cancel")]])


def memory_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("🧹 Очистить историю диалога", "memory:clear")],
            [_btn("⬅️ Меню", "menu:main")],
        ]
    )

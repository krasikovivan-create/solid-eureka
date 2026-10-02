"""Справочники: статусы, приоритеты и их подписи на русском."""

TASK_PRIORITIES = {
    "low": "🟢 низкий",
    "normal": "🟡 обычный",
    "high": "🟠 высокий",
    "urgent": "🔴 срочный",
}
PRIORITY_ORDER = {"urgent": 0, "high": 1, "normal": 2, "low": 3}

TASK_STATUSES = {
    "todo": "к выполнению",
    "in_progress": "в работе",
    "done": "выполнена",
    "cancelled": "отменена",
}
OPEN_TASK_STATUSES = ("todo", "in_progress")

CLIENT_STATUSES = {
    "lead": "🆕 Лид",
    "contacted": "📞 Первый контакт",
    "audit": "🔍 Аудит",
    "proposal": "📄 КП отправлено",
    "negotiation": "🤝 Переговоры",
    "won": "✅ Сделка",
    "lost": "❌ Отказ",
}

INTERACTION_KINDS = {
    "call": "📞 звонок",
    "meeting": "🤝 встреча",
    "email": "✉️ письмо",
    "message": "💬 сообщение",
    "note": "📝 заметка",
}

FACT_CATEGORIES = {
    "company": "о компании",
    "client": "о клиенте",
    "preference": "предпочтения",
    "other": "другое",
}

COMMUNICATION_STYLES = {
    "business": "Деловой: вежливо, по делу, без лишних эмоций, на «вы».",
    "friendly": "Дружелюбный: тепло и просто, допустимы эмодзи, можно на «ты».",
    "brief": "Краткий: максимально сжато, списками, только суть.",
    "expert": "Экспертный: уверенно, с аргументами и цифрами, как консультант.",
}

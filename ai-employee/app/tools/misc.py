"""Инструменты: тексты, память, настройки, расходы."""

from __future__ import annotations

from app.agent import workflows
from app.agent.prompts import TEXT_KINDS
from app.constants import FACT_CATEGORIES
from app.services import memory as memory_service
from app.services import profile as profile_service
from app.services import usage as usage_service
from app.services.textutils import md_to_html, strip_html
from app.tools.base import S_BOOL, S_INT, S_STR, OutConfirm, OutText, ToolContext, registry


@registry.register(
    "write_text",
    "Написать текст в стиле компании: письмо клиенту (email), пост для соцсетей (post), "
    "отчёт (report), сообщение (message), другое (other). Готовый текст сразу отправляется "
    "пользователю. В brief передай всё важное: цель, адресата, факты, цифры, тон, объём.",
    {
        "kind": {"type": "string", "enum": list(TEXT_KINDS)},
        "brief": {"type": "string", "description": "Подробное задание на текст"},
        "client_id": {"type": "integer", "description": "Если текст для конкретного клиента"},
    },
    required=["kind", "brief"],
)
async def write_text(ctx: ToolContext, kind: str, brief: str, client_id: int | None = None):
    text = await workflows.write_text(ctx.app, kind, brief, ctx.user_id, client_id)
    ctx.outbox.append(OutText(md_to_html(text)))
    return {"status": "Текст отправлен пользователю отдельным сообщением.", "chars": len(text)}


@registry.register(
    "remember_fact",
    "Запомнить важный долговременный факт: о компании (цены, услуги, условия), о клиенте "
    "(с client_id), о предпочтениях пользователя.",
    {
        "content": S_STR,
        "category": {"type": "string", "enum": list(FACT_CATEGORIES)},
        "client_id": S_INT,
    },
    required=["content"],
)
async def remember_fact(
    ctx: ToolContext, content: str, category: str = "company", client_id: int | None = None
):
    if client_id is not None:
        category = "client"
    fact = await memory_service.add_fact(ctx.app.sf, content, category, client_id)
    return {"saved_fact_id": fact.id}


@registry.register(
    "list_facts",
    "Показать сохранённые факты (вся память или по клиенту).",
    {"client_id": S_INT},
)
async def list_facts(ctx: ToolContext, client_id: int | None = None):
    facts = await memory_service.list_facts(ctx.app.sf, client_id=client_id)
    return memory_service.format_facts(facts)


@registry.register(
    "forget_fact",
    "Удалить факт из памяти. Выполнится после подтверждения пользователем кнопкой.",
    {"fact_id": S_INT},
    required=["fact_id"],
)
async def forget_fact(ctx: ToolContext, fact_id: int):
    fact = await memory_service.get_fact(ctx.app.sf, fact_id)
    ctx.outbox.append(OutConfirm("fact", fact.id, f"факт #{fact.id} «{fact.content[:80]}»"))
    return "Пользователю показана кнопка подтверждения удаления."


@registry.register(
    "update_settings",
    "Изменить настройки: время утреннего плана и вечернего отчёта (ЧЧ:ММ), их включение, "
    "часовой пояс (например Europe/Moscow), ставку в рублях за час для КП, стиль общения.",
    {
        "morning_time": S_STR,
        "evening_time": S_STR,
        "morning_enabled": S_BOOL,
        "evening_enabled": S_BOOL,
        "timezone": S_STR,
        "hourly_rate": S_INT,
        "communication_style": S_STR,
    },
)
async def update_settings(ctx: ToolContext, **fields):
    if not fields:
        return "Нечего менять."
    profile = await profile_service.update_profile(ctx.app.sf, **fields)
    if ctx.app.scheduler is not None:
        await ctx.app.scheduler.reschedule_daily()
    return {
        "morning": f"{profile.morning_time} ({'вкл' if profile.morning_enabled else 'выкл'})",
        "evening": f"{profile.evening_time} ({'вкл' if profile.evening_enabled else 'выкл'})",
        "timezone": profile.timezone,
        "hourly_rate": profile.hourly_rate,
    }


@registry.register("get_usage", "Расходы на ИИ за сегодня и за месяц.", {})
async def get_usage(ctx: ToolContext):
    s = ctx.app.settings
    report = await usage_service.usage_report(
        ctx.app.sf, ctx.tz, s.daily_budget_usd, s.monthly_budget_usd
    )
    return strip_html(report)

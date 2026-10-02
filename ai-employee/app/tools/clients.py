"""Инструменты: клиенты, лиды, история, follow-up, воронка."""

from __future__ import annotations

from app.constants import CLIENT_STATUSES, INTERACTION_KINDS
from app.services import clients as client_service
from app.services import tasks as task_service
from app.services.textutils import strip_html
from app.services.timeutils import parse_local_datetime
from app.tools.base import S_BOOL, S_DT, S_INT, S_STR, OutConfirm, ToolContext, registry

S_STATUS = {"type": "string", "enum": list(CLIENT_STATUSES)}
CLIENT_PROPS = {
    "company": {"type": "string", "description": "Название компании клиента"},
    "industry": {"type": "string", "description": "Сфера бизнеса"},
    "contact_name": {"type": "string", "description": "Контактное лицо (ФИО, должность)"},
    "phone": S_STR,
    "email": S_STR,
    "telegram": S_STR,
    "website": S_STR,
    "status": S_STATUS,
    "notes": S_STR,
}


@registry.register(
    "create_client",
    "Добавить клиента или лида в базу. Перед этим проверь find_clients, нет ли его уже.",
    CLIENT_PROPS,
    required=["company"],
)
async def create_client(ctx: ToolContext, company: str, **fields):
    client = await client_service.create_client(ctx.app.sf, company, **fields)
    return {"created": client_service.client_to_dict(client, ctx.tz)}


@registry.register(
    "update_client",
    "Изменить карточку клиента: контакты, сферу, статус сделки, заметки. "
    "append_notes=true — дописать заметку к существующим, а не заменить.",
    {"client_id": S_INT, **CLIENT_PROPS, "append_notes": S_BOOL},
    required=["client_id"],
)
async def update_client(ctx: ToolContext, client_id: int, append_notes: bool = False, **fields):
    client = await client_service.update_client(
        ctx.app.sf, client_id, append_notes=append_notes, **fields
    )
    return {"updated": client_service.client_to_dict(client, ctx.tz)}


@registry.register(
    "find_clients",
    "Найти клиентов по тексту (название, контакт, сфера, заметки) и/или статусу сделки. "
    "Без параметров — последние клиенты.",
    {"query": S_STR, "status": S_STATUS},
)
async def find_clients(ctx: ToolContext, query: str | None = None, status: str | None = None):
    clients = await client_service.find_clients(ctx.app.sf, query=query, status=status)
    return {
        "count": len(clients),
        "clients": [
            {"id": c.id, "company": c.company, "industry": c.industry, "status": c.status}
            for c in clients
        ],
    }


@registry.register(
    "get_client",
    "Полная карточка клиента: контакты, статус, заметки, история взаимодействий, открытые задачи.",
    {"client_id": S_INT},
    required=["client_id"],
)
async def get_client(ctx: ToolContext, client_id: int):
    client = await client_service.get_client(ctx.app.sf, client_id)
    data = client_service.client_to_dict(client, ctx.tz, with_history=True)
    tasks = await task_service.list_tasks(
        ctx.app.sf, None, ctx.tz, status="open", client_id=client_id
    )
    data["open_tasks"] = [task_service.task_to_dict(t, ctx.tz) for t in tasks]
    return data


@registry.register(
    "add_interaction",
    "Записать взаимодействие с клиентом в историю: звонок, встреча, письмо, сообщение, заметка.",
    {
        "client_id": S_INT,
        "kind": {"type": "string", "enum": list(INTERACTION_KINDS)},
        "summary": {"type": "string", "description": "О чём договорились, итог"},
        "occurred_at": S_DT,
    },
    required=["client_id", "summary"],
)
async def add_interaction(
    ctx: ToolContext,
    client_id: int,
    summary: str,
    kind: str = "note",
    occurred_at: str | None = None,
):
    when = parse_local_datetime(occurred_at, ctx.tz)
    item = await client_service.add_interaction(ctx.app.sf, client_id, summary, kind, when)
    return {"saved": {"id": item.id, "client_id": client_id, "kind": kind, "summary": summary}}


@registry.register(
    "schedule_follow_up",
    "Запланировать follow-up с клиентом: создаёт задачу с напоминанием, привязанную к клиенту.",
    {"client_id": S_INT, "when": S_DT, "note": {"type": "string", "description": "Что сделать"}},
    required=["client_id", "when"],
)
async def schedule_follow_up(ctx: ToolContext, client_id: int, when: str, note: str = ""):
    client = await client_service.get_client(ctx.app.sf, client_id)
    remind = parse_local_datetime(when, ctx.tz)
    title = f"Follow-up: {client.company}" + (f" — {note}" if note else "")
    task = await task_service.create_task(
        ctx.app.sf,
        ctx.user_id,
        title,
        priority="high",
        due_at=remind,
        remind_at=remind,
        client_id=client_id,
    )
    if ctx.app.scheduler is not None:
        ctx.app.scheduler.schedule_task_reminder(task)
    return {"follow_up_task": task_service.task_to_dict(task, ctx.tz)}


@registry.register(
    "sales_pipeline",
    "Воронка продаж: сколько клиентов на каждом статусе сделки и кто именно.",
    {},
)
async def sales_pipeline(ctx: ToolContext):
    data = await client_service.pipeline(ctx.app.sf)
    return strip_html(client_service.format_pipeline(data))


@registry.register(
    "delete_client",
    "Удалить клиента вместе с историей. Выполнится после подтверждения пользователем кнопкой.",
    {"client_id": S_INT},
    required=["client_id"],
)
async def delete_client(ctx: ToolContext, client_id: int):
    client = await client_service.get_client(ctx.app.sf, client_id)
    ctx.outbox.append(OutConfirm("client", client.id, f"клиента #{client.id} «{client.company}»"))
    return "Пользователю показана кнопка подтверждения удаления."

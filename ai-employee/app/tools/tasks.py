"""Инструменты: задачи и напоминания, план дня."""

from __future__ import annotations

from datetime import date

from app.constants import TASK_PRIORITIES, TASK_STATUSES
from app.services import reports
from app.services import tasks as task_service
from app.services.timeutils import fmt_dt, now_local, parse_local_datetime
from app.tools.base import S_BOOL, S_DT, S_INT, S_STR, OutConfirm, ToolContext, registry

S_PRIORITY = {"type": "string", "enum": list(TASK_PRIORITIES)}


def _schedule(ctx: ToolContext, task) -> None:
    if ctx.app.scheduler is not None:
        ctx.app.scheduler.schedule_task_reminder(task)


@registry.register(
    "create_task",
    "Создать задачу или напоминание. «Напомни завтра в 10 позвонить Иванову» → title "
    "«Позвонить Иванову», remind_at = завтра 10:00. due_at — срок выполнения.",
    {
        "title": {"type": "string", "description": "Коротко, что сделать"},
        "description": S_STR,
        "priority": S_PRIORITY,
        "due_at": S_DT,
        "remind_at": S_DT,
        "client_id": {"type": "integer", "description": "id клиента, если задача про клиента"},
    },
    required=["title"],
)
async def create_task(
    ctx: ToolContext,
    title: str,
    description: str = "",
    priority: str = "normal",
    due_at: str | None = None,
    remind_at: str | None = None,
    client_id: int | None = None,
):
    due = parse_local_datetime(due_at, ctx.tz)
    remind = parse_local_datetime(remind_at, ctx.tz)
    if remind is None and due is not None and due_at and "T" in due_at:
        remind = due
    task = await task_service.create_task(
        ctx.app.sf, ctx.user_id, title, description, priority, due, remind, client_id
    )
    _schedule(ctx, task)
    result = {"created": task_service.task_to_dict(task, ctx.tz)}
    if remind is not None and remind < task.created_at:
        result["warning"] = "Время напоминания уже прошло — напоминание придёт сразу."
    return result


@registry.register(
    "list_tasks",
    "Список задач пользователя. status: open (по умолчанию), done, all, todo, in_progress, "
    "cancelled. period: all, today, tomorrow, week, overdue, no_date.",
    {
        "status": {"type": "string", "enum": ["open", "done", "all", *TASK_STATUSES]},
        "period": {"type": "string", "enum": list(task_service.PERIODS)},
        "client_id": S_INT,
    },
)
async def list_tasks(
    ctx: ToolContext, status: str = "open", period: str = "all", client_id: int | None = None
):
    tasks = await task_service.list_tasks(
        ctx.app.sf, ctx.user_id, ctx.tz, status=status, period=period, client_id=client_id
    )
    return {"count": len(tasks), "tasks": [task_service.task_to_dict(t, ctx.tz) for t in tasks]}


@registry.register(
    "update_task",
    "Изменить задачу: название, описание, приоритет, статус (todo, in_progress, done, "
    "cancelled), срок, напоминание. Чтобы отметить выполненной — status=done. "
    "clear_due / clear_reminder убирают срок / напоминание.",
    {
        "task_id": S_INT,
        "title": S_STR,
        "description": S_STR,
        "priority": S_PRIORITY,
        "status": {"type": "string", "enum": list(TASK_STATUSES)},
        "due_at": S_DT,
        "remind_at": S_DT,
        "clear_due": S_BOOL,
        "clear_reminder": S_BOOL,
        "client_id": S_INT,
    },
    required=["task_id"],
)
async def update_task(
    ctx: ToolContext,
    task_id: int,
    clear_due: bool = False,
    clear_reminder: bool = False,
    **fields,
):
    await _own_task(ctx, task_id)
    if "due_at" in fields:
        fields["due_at"] = parse_local_datetime(fields["due_at"], ctx.tz)
    if "remind_at" in fields:
        fields["remind_at"] = parse_local_datetime(fields["remind_at"], ctx.tz)
    if clear_due:
        fields["due_at"] = None
    if clear_reminder:
        fields["remind_at"] = None
    if not fields:
        return "Нечего менять — укажите новые значения."
    task = await task_service.update_task(ctx.app.sf, task_id, **fields)
    if ctx.app.scheduler is not None:
        if task.status in ("done", "cancelled"):
            ctx.app.scheduler.unschedule_task_reminder(task.id)
        else:
            _schedule(ctx, task)
    return {"updated": task_service.task_to_dict(task, ctx.tz)}


@registry.register(
    "delete_task",
    "Удалить задачу. Удаление выполнится после подтверждения пользователем кнопкой.",
    {"task_id": S_INT},
    required=["task_id"],
)
async def delete_task(ctx: ToolContext, task_id: int):
    task = await _own_task(ctx, task_id)
    ctx.outbox.append(OutConfirm("task", task.id, f"задачу #{task.id} «{task.title}»"))
    return "Пользователю показана кнопка подтверждения удаления."


@registry.register(
    "day_overview",
    "План на день: задачи на дату, просроченные, важные без срока. date — ГГГГ-ММ-ДД, "
    "по умолчанию сегодня. Используй для «что у меня сегодня/завтра».",
    {"date": {"type": "string", "description": "ГГГГ-ММ-ДД"}},
)
async def day_overview(ctx: ToolContext, date: str | None = None):
    day = _parse_date(date) if date else now_local(ctx.tz).date()
    text = await reports.morning_plan(ctx.app.sf, ctx.user_id, day)
    return {"overview": text}


@registry.register(
    "evening_summary",
    "Итоги дня: что выполнено, работа с клиентами, что просрочено, что завтра.",
    {"date": {"type": "string", "description": "ГГГГ-ММ-ДД, по умолчанию сегодня"}},
)
async def evening_summary(ctx: ToolContext, date: str | None = None):
    day = _parse_date(date) if date else now_local(ctx.tz).date()
    return {"summary": await reports.evening_report(ctx.app.sf, ctx.user_id, day)}


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError("Дата нужна в формате ГГГГ-ММ-ДД") from exc


async def _own_task(ctx: ToolContext, task_id: int):
    task = await task_service.get_task(ctx.app.sf, task_id)
    if task.user_id != ctx.user_id:
        raise task_service.NotFoundError(f"Задача #{task_id} не найдена")
    return task


def describe_task(task, tz: str) -> str:
    when = fmt_dt(task.remind_at or task.due_at, tz) if (task.remind_at or task.due_at) else ""
    return f"#{task.id} {task.title}" + (f" ({when})" if when else "")

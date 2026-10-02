"""Задачи и напоминания."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select

from app.constants import OPEN_TASK_STATUSES, PRIORITY_ORDER, TASK_PRIORITIES, TASK_STATUSES
from app.database.models import Client, Task
from app.database.session import SessionFactory
from app.services.textutils import esc
from app.services.timeutils import fmt_dt, local_day_bounds, now_local, now_utc

PERIODS = ("all", "today", "tomorrow", "week", "overdue", "no_date")


class NotFoundError(ValueError):
    pass


def _check_priority(priority: str | None) -> str | None:
    if priority is None:
        return None
    if priority not in TASK_PRIORITIES:
        raise ValueError(f"Приоритет должен быть одним из: {', '.join(TASK_PRIORITIES)}")
    return priority


def _check_status(status: str | None) -> str | None:
    if status is None:
        return None
    if status not in TASK_STATUSES:
        raise ValueError(f"Статус должен быть одним из: {', '.join(TASK_STATUSES)}")
    return status


async def create_task(
    sf: SessionFactory,
    user_id: int,
    title: str,
    description: str = "",
    priority: str = "normal",
    due_at: datetime | None = None,
    remind_at: datetime | None = None,
    client_id: int | None = None,
) -> Task:
    title = (title or "").strip()
    if not title:
        raise ValueError("У задачи должно быть название")
    _check_priority(priority)
    async with sf() as s:
        if client_id is not None and await s.get(Client, client_id) is None:
            raise NotFoundError(f"Клиент #{client_id} не найден")
        task = Task(
            user_id=user_id,
            title=title[:500],
            description=description or "",
            priority=priority or "normal",
            due_at=due_at,
            remind_at=remind_at,
            client_id=client_id,
        )
        s.add(task)
        await s.commit()
        await s.refresh(task)
        return task


async def get_task(sf: SessionFactory, task_id: int) -> Task:
    async with sf() as s:
        task = await s.get(Task, task_id)
        if task is None:
            raise NotFoundError(f"Задача #{task_id} не найдена")
        return task


async def update_task(sf: SessionFactory, task_id: int, **fields: object) -> Task:
    allowed = {"title", "description", "priority", "status", "due_at", "remind_at", "client_id"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Нельзя изменить поля: {', '.join(sorted(unknown))}")
    _check_priority(fields.get("priority"))  # type: ignore[arg-type]
    _check_status(fields.get("status"))  # type: ignore[arg-type]
    async with sf() as s:
        task = await s.get(Task, task_id)
        if task is None:
            raise NotFoundError(f"Задача #{task_id} не найдена")
        for key, value in fields.items():
            setattr(task, key, value)
        if "remind_at" in fields:
            task.reminder_sent = False
        if fields.get("status") == "done":
            task.completed_at = now_utc()
        elif "status" in fields:
            task.completed_at = None
        await s.commit()
        await s.refresh(task)
        return task


async def delete_task(sf: SessionFactory, task_id: int) -> Task:
    async with sf() as s:
        task = await s.get(Task, task_id)
        if task is None:
            raise NotFoundError(f"Задача #{task_id} не найдена")
        await s.delete(task)
        await s.commit()
        return task


async def list_tasks(
    sf: SessionFactory,
    user_id: int | None,
    tz: str,
    status: str = "open",
    period: str = "all",
    client_id: int | None = None,
    limit: int = 50,
) -> list[Task]:
    """status: open | done | all | todo | in_progress | cancelled; period — см. PERIODS."""
    if period not in PERIODS:
        raise ValueError(f"Период должен быть одним из: {', '.join(PERIODS)}")
    conds = []
    if user_id is not None:
        conds.append(Task.user_id == user_id)
    if status == "open":
        conds.append(Task.status.in_(OPEN_TASK_STATUSES))
    elif status != "all":
        _check_status(status)
        conds.append(Task.status == status)
    if client_id is not None:
        conds.append(Task.client_id == client_id)

    today = now_local(tz).date()
    when = None
    if period == "today":
        start, end = local_day_bounds(today, tz)
        when = or_(
            and_(Task.due_at >= start, Task.due_at < end),
            and_(Task.remind_at >= start, Task.remind_at < end),
        )
    elif period == "tomorrow":
        start, end = local_day_bounds(today + timedelta(days=1), tz)
        when = or_(
            and_(Task.due_at >= start, Task.due_at < end),
            and_(Task.remind_at >= start, Task.remind_at < end),
        )
    elif period == "week":
        start, _ = local_day_bounds(today, tz)
        end = start + timedelta(days=7)
        when = or_(
            and_(Task.due_at >= start, Task.due_at < end),
            and_(Task.remind_at >= start, Task.remind_at < end),
        )
    elif period == "overdue":
        when = and_(Task.due_at.is_not(None), Task.due_at < now_utc())
    elif period == "no_date":
        when = and_(Task.due_at.is_(None), Task.remind_at.is_(None))
    if when is not None:
        conds.append(when)

    async with sf() as s:
        rows = (await s.scalars(select(Task).where(*conds))).all()
    return sort_tasks(list(rows))[:limit]


def sort_tasks(tasks: list[Task]) -> list[Task]:
    far = datetime.max.replace(tzinfo=None)

    def key(t: Task) -> tuple:
        when = t.due_at or t.remind_at
        return (
            PRIORITY_ORDER.get(t.priority, 9),
            when.replace(tzinfo=None) if when else far,
            t.id,
        )

    return sorted(tasks, key=key)


async def pending_reminders(sf: SessionFactory) -> list[Task]:
    async with sf() as s:
        rows = await s.scalars(
            select(Task).where(
                Task.remind_at.is_not(None),
                Task.reminder_sent.is_(False),
                Task.status.in_(OPEN_TASK_STATUSES),
            )
        )
        return list(rows.all())


async def mark_reminder_sent(sf: SessionFactory, task_id: int) -> None:
    async with sf() as s:
        task = await s.get(Task, task_id)
        if task is not None:
            task.reminder_sent = True
            await s.commit()


async def completed_between(
    sf: SessionFactory, user_id: int, start: datetime, end: datetime
) -> list[Task]:
    async with sf() as s:
        rows = await s.scalars(
            select(Task).where(
                Task.user_id == user_id,
                Task.status == "done",
                Task.completed_at >= start,
                Task.completed_at < end,
            )
        )
        return list(rows.all())


def format_task(task: Task, tz: str, with_id: bool = True) -> str:
    mark = "✅" if task.status == "done" else ("❌" if task.status == "cancelled" else "▫️")
    parts = [f"{mark} {'#' + str(task.id) + ' ' if with_id else ''}{esc(task.title)}"]
    meta = []
    if task.priority != "normal":
        meta.append(TASK_PRIORITIES.get(task.priority, task.priority))
    if task.due_at:
        overdue = task.status in OPEN_TASK_STATUSES and task.due_at < now_utc()
        meta.append(("⚠️ просрочено, " if overdue else "срок: ") + fmt_dt(task.due_at, tz))
    if task.remind_at and not task.reminder_sent and task.status in OPEN_TASK_STATUSES:
        meta.append("⏰ " + fmt_dt(task.remind_at, tz))
    if task.status == "in_progress":
        meta.append("в работе")
    if meta:
        parts.append("   " + " · ".join(meta))
    return "\n".join(parts)


def task_to_dict(task: Task, tz: str) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "priority": task.priority,
        "status": task.status,
        "due": fmt_dt(task.due_at, tz) if task.due_at else None,
        "remind": fmt_dt(task.remind_at, tz) if task.remind_at else None,
        "reminder_sent": task.reminder_sent,
        "client_id": task.client_id,
    }

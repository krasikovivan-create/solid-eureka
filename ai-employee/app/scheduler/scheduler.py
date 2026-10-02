"""Планировщик: напоминания по задачам и ежедневные сводки (APScheduler).

Напоминания хранятся в БД (Task.remind_at). При старте все неотправленные напоминания
заново ставятся в расписание, а пропущенные за время простоя — отправляются сразу.
Дополнительно раз в минуту идёт «страховочная» проверка просроченных напоминаний.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.constants import OPEN_TASK_STATUSES, TASK_PRIORITIES
from app.context import AppContext
from app.database.models import Task
from app.services import reports
from app.services import tasks as task_service
from app.services.profile import get_profile, recipients
from app.services.textutils import esc
from app.services.timeutils import fmt_dt, get_tz, now_utc

log = logging.getLogger(__name__)

Sender = Callable[[int, str, Any], Awaitable[None]]
KeyboardFactory = Callable[[Task], Any]


def reminder_job_id(task_id: int) -> str:
    return f"reminder:{task_id}"


class BotScheduler:
    def __init__(
        self,
        app: AppContext,
        sender: Sender,
        reminder_keyboard: KeyboardFactory | None = None,
        scheduler: AsyncIOScheduler | None = None,
    ) -> None:
        self.app = app
        self.sender = sender
        self.reminder_keyboard = reminder_keyboard
        self.scheduler = scheduler or AsyncIOScheduler(timezone="UTC")
        self._lock = asyncio.Lock()

    # --- запуск -----------------------------------------------------------

    async def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
        await self.restore_reminders()
        await self.reschedule_daily()
        self.scheduler.add_job(
            self.sweep,
            IntervalTrigger(seconds=60),
            id="sweep",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        log.info("Планировщик запущен, задач в расписании: %s", len(self.scheduler.get_jobs()))

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def restore_reminders(self) -> int:
        tasks = await task_service.pending_reminders(self.app.sf)
        for task in tasks:
            self.schedule_task_reminder(task)
        log.info("Восстановлено напоминаний: %s", len(tasks))
        return len(tasks)

    # --- напоминания -------------------------------------------------------

    def schedule_task_reminder(self, task: Task) -> None:
        job_id = reminder_job_id(task.id)
        if task.remind_at is None or task.reminder_sent or task.status not in OPEN_TASK_STATUSES:
            self.unschedule_task_reminder(task.id)
            return
        run_at = task.remind_at
        if run_at <= now_utc():
            run_at = now_utc() + timedelta(seconds=2)
        self.scheduler.add_job(
            self.fire_reminder,
            DateTrigger(run_date=run_at),
            args=[task.id],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=None,
        )

    def unschedule_task_reminder(self, task_id: int) -> None:
        job = self.scheduler.get_job(reminder_job_id(task_id))
        if job is not None:
            job.remove()

    async def fire_reminder(self, task_id: int) -> bool:
        async with self._lock:
            try:
                task = await task_service.get_task(self.app.sf, task_id)
            except task_service.NotFoundError:
                return False
            if (
                task.reminder_sent
                or task.remind_at is None
                or task.status not in OPEN_TASK_STATUSES
            ):
                return False
            if task.remind_at > now_utc() + timedelta(seconds=30):
                # Время перенесли — ставим заново.
                self.schedule_task_reminder(task)
                return False
            profile = await get_profile(self.app.sf)
            text = self.reminder_text(task, profile.timezone)
            keyboard = self.reminder_keyboard(task) if self.reminder_keyboard else None
            try:
                await self.sender(task.user_id, text, keyboard)
            except Exception:
                log.exception("Не удалось отправить напоминание по задаче #%s", task_id)
                return False
            await task_service.mark_reminder_sent(self.app.sf, task_id)
            return True

    @staticmethod
    def reminder_text(task: Task, tz: str) -> str:
        lines = [f"⏰ <b>Напоминание</b>\n{esc(task.title)}"]
        if task.description:
            lines.append(esc(task.description))
        meta = []
        if task.due_at:
            meta.append(f"срок: {fmt_dt(task.due_at, tz)}")
        if task.priority in ("high", "urgent"):
            meta.append(TASK_PRIORITIES[task.priority])
        if meta:
            lines.append(" · ".join(meta))
        lines.append(f"<i>Задача #{task.id}</i>")
        return "\n".join(lines)

    async def sweep(self) -> int:
        """Отправляет напоминания, время которых наступило, но которые не ушли."""
        sent = 0
        now = now_utc()
        for task in await task_service.pending_reminders(self.app.sf):
            if task.remind_at is not None and task.remind_at <= now:
                if self.scheduler.get_job(reminder_job_id(task.id)) is not None:
                    continue
                if await self.fire_reminder(task.id):
                    sent += 1
        return sent

    # --- ежедневные сводки --------------------------------------------------

    async def reschedule_daily(self) -> None:
        profile = await get_profile(self.app.sf)
        tz = get_tz(profile.timezone)
        for key, enabled, hhmm, func in (
            ("morning", profile.morning_enabled, profile.morning_time, self.send_morning),
            ("evening", profile.evening_enabled, profile.evening_time, self.send_evening),
        ):
            job_id = f"daily:{key}"
            if not enabled:
                if self.scheduler.get_job(job_id):
                    self.scheduler.remove_job(job_id)
                continue
            hour, minute = (int(x) for x in hhmm.split(":"))
            self.scheduler.add_job(
                func,
                CronTrigger(hour=hour, minute=minute, timezone=tz),
                id=job_id,
                replace_existing=True,
                misfire_grace_time=3600,
                coalesce=True,
            )

    async def send_morning(self) -> int:
        return await self._broadcast(reports.morning_plan)

    async def send_evening(self) -> int:
        return await self._broadcast(reports.evening_report)

    async def _broadcast(self, builder) -> int:
        profile = await get_profile(self.app.sf)
        if not profile.onboarded:
            return 0
        count = 0
        for user_id in await recipients(self.app.sf, self.app.settings.allowed_user_ids):
            try:
                text = await builder(self.app.sf, user_id)
                await self.sender(user_id, text, None)
                count += 1
            except Exception:
                log.exception("Не удалось отправить сводку пользователю %s", user_id)
        return count

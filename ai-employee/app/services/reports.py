"""Утренний план дня и вечерний отчёт."""

from __future__ import annotations

from datetime import date, timedelta

from app.constants import INTERACTION_KINDS
from app.database.session import SessionFactory
from app.services import clients as client_service
from app.services import tasks as task_service
from app.services.profile import get_profile
from app.services.textutils import esc
from app.services.timeutils import fmt_date_long, local_day_bounds, now_local


async def morning_plan(sf: SessionFactory, user_id: int, day: date | None = None) -> str:
    profile = await get_profile(sf)
    tz = profile.timezone
    day = day or now_local(tz).date()
    is_today = day == now_local(tz).date()
    start, end = local_day_bounds(day, tz)

    open_tasks = await task_service.list_tasks(sf, user_id, tz, status="open", limit=500)

    def on_day(t) -> bool:
        return any(x is not None and start <= x < end for x in (t.due_at, t.remind_at))

    today_tasks = [t for t in open_tasks if on_day(t)]
    overdue = [t for t in open_tasks if t.due_at is not None and t.due_at < start]
    no_date = [t for t in open_tasks if t.due_at is None and t.remind_at is None]
    urgent_no_date = [t for t in no_date if t.priority in ("urgent", "high")]

    greeting = "☀️ <b>Доброе утро!</b>" if is_today else "🗓 <b>План</b>"
    lines = [f"{greeting} План на {fmt_date_long(day)}", ""]
    if today_tasks:
        lines.append(f"<b>На {'сегодня' if is_today else 'этот день'} ({len(today_tasks)}):</b>")
        lines += [task_service.format_task(t, tz) for t in today_tasks]
        lines.append("")
    if overdue:
        lines.append(f"<b>⚠️ Просрочено ({len(overdue)}):</b>")
        lines += [task_service.format_task(t, tz) for t in overdue[:10]]
        lines.append("")
    if urgent_no_date:
        lines.append("<b>Важное без срока:</b>")
        lines += [task_service.format_task(t, tz) for t in urgent_no_date[:5]]
        lines.append("")
    if not (today_tasks or overdue or urgent_no_date):
        lines.append("Задач со сроком на этот день нет. Хорошее время для новых клиентов 🙂")
        lines.append("")
    pipeline = await client_service.pipeline(sf)
    in_work = sum(
        len(pipeline.get(s, [])) for s in ("contacted", "audit", "proposal", "negotiation")
    )
    leads = len(pipeline.get("lead", []))
    if in_work or leads:
        lines.append(f"👥 Клиенты: новых лидов — {leads}, в работе — {in_work}.")
    lines.append(f"Всего открытых задач: {len(open_tasks)}.")
    return "\n".join(lines).strip()


async def evening_report(sf: SessionFactory, user_id: int, day: date | None = None) -> str:
    profile = await get_profile(sf)
    tz = profile.timezone
    day = day or now_local(tz).date()
    start, end = local_day_bounds(day, tz)

    done = await task_service.completed_between(sf, user_id, start, end)
    open_tasks = await task_service.list_tasks(sf, user_id, tz, status="open", limit=500)
    overdue = [t for t in open_tasks if t.due_at is not None and t.due_at < end]
    t_start, t_end = local_day_bounds(day + timedelta(days=1), tz)
    tomorrow = [
        t
        for t in open_tasks
        if any(x is not None and t_start <= x < t_end for x in (t.due_at, t.remind_at))
    ]
    interactions = await client_service.interactions_between(sf, start, end)

    lines = [f"🌙 <b>Итоги дня</b> — {fmt_date_long(day)}", ""]
    lines.append(f"<b>✅ Выполнено ({len(done)}):</b>")
    lines += [f"• {esc(t.title)}" for t in done] or ["• пока ничего не отмечено"]
    lines.append("")
    if interactions:
        lines.append(f"<b>👥 Работа с клиентами ({len(interactions)}):</b>")
        for item, company in interactions[:15]:
            kind = INTERACTION_KINDS.get(item.kind, item.kind)
            lines.append(f"• {esc(company)} — {kind}: {esc(item.summary[:150])}")
        lines.append("")
    if overdue:
        lines.append(f"<b>⚠️ Не успели / просрочено ({len(overdue)}):</b>")
        lines += [task_service.format_task(t, tz) for t in overdue[:10]]
        lines.append("")
    if tomorrow:
        lines.append(f"<b>📅 Завтра ({len(tomorrow)}):</b>")
        lines += [task_service.format_task(t, tz) for t in tomorrow[:10]]
        lines.append("")
    lines.append(f"Открытых задач всего: {len(open_tasks)}.")
    return "\n".join(lines).strip()

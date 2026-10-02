"""Аудит процессов клиента: пошаговое интервью и отчёт."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.database.models import Audit
from app.database.session import SessionFactory
from app.services.tasks import NotFoundError
from app.services.textutils import esc
from app.services.timeutils import now_utc

AUDIT_QUESTIONS: list[str] = [
    "Чем занимается компания клиента: продукт или услуга, рынок, сколько сотрудников?",
    "Какие есть отделы и роли? Кто за что отвечает?",
    "Как приходят клиенты и заявки и что с ними происходит дальше — опишите путь клиента по шагам.",
    "Какие задачи сотрудники делают вручную и регулярно (каждый день или неделю)?",
    "Сколько времени уходит на эти задачи: примерно часов в неделю и сколько человек этим заняты?",
    "Какие документы, отчёты, письма и КП готовятся регулярно? Кто и как их делает?",
    "Какие программы и сервисы используются: CRM, 1С, таблицы, мессенджеры, почта, сайт?",
    "Где чаще всего бывают ошибки, задержки, потерянные заявки или «узкие места»?",
    "Как обрабатываются вопросы клиентов и поддержка? Примерный объём обращений в день?",
    "Что клиент хочет улучшить в первую очередь? Есть ли ориентир по бюджету и срокам?",
]

COMPLEXITY = ["низкая", "средняя", "высокая"]

REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "processes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "who": {"type": "string"},
                    "hours_per_month": {"type": "number"},
                },
                "required": ["name", "description", "who", "hours_per_month"],
                "additionalProperties": False,
            },
        },
        "automations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "process": {"type": "string"},
                    "solution": {"type": "string"},
                    "complexity": {"type": "string", "enum": COMPLEXITY},
                    "duration_weeks": {"type": "number"},
                    "effort_hours": {"type": "number"},
                    "hours_saved_per_month": {"type": "number"},
                },
                "required": [
                    "process",
                    "solution",
                    "complexity",
                    "duration_weeks",
                    "effort_hours",
                    "hours_saved_per_month",
                ],
                "additionalProperties": False,
            },
        },
        "quick_wins": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "processes", "automations", "quick_wins", "risks"],
    "additionalProperties": False,
}


async def start_audit(
    sf: SessionFactory, user_id: int, client_name: str, client_id: int | None = None
) -> Audit:
    """Начинает новый аудит; незавершённый аудит этого пользователя отменяется."""
    async with sf() as s:
        active = await s.scalars(
            select(Audit).where(Audit.user_id == user_id, Audit.status == "in_progress")
        )
        for a in active.all():
            a.status = "cancelled"
        audit = Audit(
            user_id=user_id,
            client_id=client_id,
            client_name=client_name.strip() or "Клиент",
            status="in_progress",
            step=0,
            answers=[],
        )
        s.add(audit)
        await s.commit()
        await s.refresh(audit)
        return audit


async def get_active_audit(sf: SessionFactory, user_id: int) -> Audit | None:
    async with sf() as s:
        return await s.scalar(
            select(Audit)
            .where(Audit.user_id == user_id, Audit.status == "in_progress")
            .order_by(Audit.id.desc())
        )


async def get_audit(sf: SessionFactory, audit_id: int) -> Audit:
    async with sf() as s:
        audit = await s.get(Audit, audit_id)
        if audit is None:
            raise NotFoundError(f"Аудит #{audit_id} не найден")
        return audit


async def list_audits(sf: SessionFactory, limit: int = 20) -> list[Audit]:
    async with sf() as s:
        rows = await s.scalars(select(Audit).order_by(Audit.id.desc()).limit(limit))
        return list(rows.all())


def current_question(audit: Audit) -> str | None:
    if audit.step < len(AUDIT_QUESTIONS):
        return AUDIT_QUESTIONS[audit.step]
    return None


def question_header(audit: Audit) -> str:
    return f"Вопрос {audit.step + 1} из {len(AUDIT_QUESTIONS)}"


async def answer(sf: SessionFactory, audit_id: int, text: str | None) -> Audit:
    """Сохраняет ответ на текущий вопрос (None — пропуск) и переходит к следующему."""
    async with sf() as s:
        audit = await s.get(Audit, audit_id)
        if audit is None or audit.status != "in_progress":
            raise NotFoundError("Активный аудит не найден")
        question = current_question(audit)
        if question is None:
            return audit
        answers = list(audit.answers or [])
        answers.append({"question": question, "answer": (text or "").strip() or "—"})
        audit.answers = answers
        audit.step += 1
        await s.commit()
        await s.refresh(audit)
        return audit


def is_interview_finished(audit: Audit) -> bool:
    return audit.step >= len(AUDIT_QUESTIONS)


async def cancel_audit(sf: SessionFactory, audit_id: int) -> None:
    async with sf() as s:
        audit = await s.get(Audit, audit_id)
        if audit is not None and audit.status == "in_progress":
            audit.status = "cancelled"
            await s.commit()


async def save_report(sf: SessionFactory, audit_id: int, report: dict) -> Audit:
    async with sf() as s:
        audit = await s.get(Audit, audit_id)
        if audit is None:
            raise NotFoundError(f"Аудит #{audit_id} не найден")
        audit.report = normalize_report(report)
        audit.status = "completed"
        audit.completed_at = now_utc()
        await s.commit()
        await s.refresh(audit)
        return audit


def _num(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def normalize_report(report: dict) -> dict:
    """Приводит отчёт к ожидаемому виду и считает итоги."""
    processes = [
        {
            "name": str(p.get("name", "")),
            "description": str(p.get("description", "")),
            "who": str(p.get("who", "")),
            "hours_per_month": round(_num(p.get("hours_per_month")), 1),
        }
        for p in report.get("processes", []) or []
    ]
    automations = []
    for a in report.get("automations", []) or []:
        complexity = str(a.get("complexity", "средняя")).lower()
        automations.append(
            {
                "process": str(a.get("process", "")),
                "solution": str(a.get("solution", "")),
                "complexity": complexity if complexity in COMPLEXITY else "средняя",
                "duration_weeks": round(_num(a.get("duration_weeks")), 1),
                "effort_hours": round(_num(a.get("effort_hours")), 1),
                "hours_saved_per_month": round(_num(a.get("hours_saved_per_month")), 1),
            }
        )
    return {
        "summary": str(report.get("summary", "")),
        "processes": processes,
        "automations": automations,
        "quick_wins": [str(x) for x in report.get("quick_wins", []) or []],
        "risks": [str(x) for x in report.get("risks", []) or []],
        "total_hours_saved_per_month": round(
            sum(a["hours_saved_per_month"] for a in automations), 1
        ),
        "total_routine_hours_per_month": round(sum(p["hours_per_month"] for p in processes), 1),
    }


def build_report_prompt(audit: Audit, company_context: str) -> str:
    qa = "\n\n".join(
        f"Вопрос: {item['question']}\nОтвет: {item['answer']}" for item in audit.answers or []
    )
    return (
        f"{company_context}\n\n"
        f"Мы провели интервью с клиентом «{audit.client_name}», чтобы найти рутинные процессы, "
        "которые можно автоматизировать с помощью ИИ.\n\n"
        f"<interview>\n{qa}\n</interview>\n\n"
        "Составь отчёт по аудиту:\n"
        "1. summary — 3–5 предложений: что за бизнес и главные выводы.\n"
        "2. processes — карта рутинных процессов: название, описание, кто выполняет, "
        "сколько часов в месяц уходит (оценка по ответам; если данных мало — разумная "
        "консервативная оценка).\n"
        "3. automations — что автоматизировать ИИ: процесс, конкретное решение (чат-бот, "
        "ИИ-агент, генерация документов, интеграция с CRM и т.п.), сложность "
        "(низкая/средняя/высокая), срок внедрения в неделях, трудоёмкость внедрения в часах, "
        "экономия часов в месяц. Сортируй по выгоде.\n"
        "4. quick_wins — что можно сделать за 1–2 недели.\n"
        "5. risks — риски и что нужно от клиента.\n"
        "Пиши по-русски, конкретно, без воды. Числа — реалистичные."
    )


def format_report(audit: Audit) -> str:
    r = audit.report or {}
    lines = [f"🔍 <b>Аудит процессов: {esc(audit.client_name)}</b> (#{audit.id})", ""]
    if r.get("summary"):
        lines += [esc(r["summary"]), ""]
    if r.get("processes"):
        lines.append("<b>🗺 Карта рутинных процессов</b>")
        for p in r["processes"]:
            who = f" ({esc(p['who'])})" if p.get("who") else ""
            lines.append(f"• <b>{esc(p['name'])}</b>{who} — ~{p['hours_per_month']:g} ч/мес")
            if p.get("description"):
                lines.append(f"   {esc(p['description'])}")
        lines.append("")
    if r.get("automations"):
        lines.append("<b>🤖 Что автоматизировать ИИ</b>")
        for i, a in enumerate(r["automations"], start=1):
            lines.append(f"{i}. <b>{esc(a['process'])}</b>: {esc(a['solution'])}")
            lines.append(
                f"   Сложность: {a['complexity']} · срок: {a['duration_weeks']:g} нед. · "
                f"экономия: <b>{a['hours_saved_per_month']:g} ч/мес</b>"
            )
        lines.append("")
    if r.get("quick_wins"):
        lines.append("<b>⚡ Быстрые победы</b>")
        lines += [f"• {esc(x)}" for x in r["quick_wins"]]
        lines.append("")
    if r.get("risks"):
        lines.append("<b>⚠️ Риски</b>")
        lines += [f"• {esc(x)}" for x in r["risks"]]
        lines.append("")
    lines.append(
        f"📈 Итого экономия: <b>{r.get('total_hours_saved_per_month', 0):g} ч в месяц</b> "
        f"(рутина сейчас: ~{r.get('total_routine_hours_per_month', 0):g} ч/мес)"
    )
    return "\n".join(lines)

"""Клиенты и лиды: карточки, история взаимодействий, воронка."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.constants import CLIENT_STATUSES, INTERACTION_KINDS
from app.database.models import Client, Interaction
from app.database.session import SessionFactory
from app.services.tasks import NotFoundError
from app.services.textutils import esc
from app.services.timeutils import fmt_dt, now_utc

CLIENT_FIELDS = (
    "company",
    "industry",
    "contact_name",
    "phone",
    "email",
    "telegram",
    "website",
    "status",
    "notes",
)


def _check_status(status: str | None) -> None:
    if status is not None and status not in CLIENT_STATUSES:
        raise ValueError(f"Статус сделки должен быть одним из: {', '.join(CLIENT_STATUSES)}")


async def create_client(sf: SessionFactory, company: str, **fields: str) -> Client:
    company = (company or "").strip()
    if not company:
        raise ValueError("Укажите название компании клиента")
    unknown = set(fields) - set(CLIENT_FIELDS)
    if unknown:
        raise ValueError(f"Неизвестные поля: {', '.join(sorted(unknown))}")
    _check_status(fields.get("status"))
    clean = {k: (v or "") for k, v in fields.items() if v is not None}
    clean.setdefault("status", "lead")
    async with sf() as s:
        client = Client(company=company[:200], **clean)
        s.add(client)
        await s.commit()
        await s.refresh(client)
        return client


async def get_client(sf: SessionFactory, client_id: int) -> Client:
    async with sf() as s:
        client = await s.get(Client, client_id, options=[selectinload(Client.interactions)])
        if client is None:
            raise NotFoundError(f"Клиент #{client_id} не найден")
        return client


async def update_client(
    sf: SessionFactory, client_id: int, append_notes: bool = False, **fields: str
) -> Client:
    unknown = set(fields) - set(CLIENT_FIELDS)
    if unknown:
        raise ValueError(f"Неизвестные поля: {', '.join(sorted(unknown))}")
    _check_status(fields.get("status"))
    async with sf() as s:
        client = await s.get(Client, client_id)
        if client is None:
            raise NotFoundError(f"Клиент #{client_id} не найден")
        for key, value in fields.items():
            if value is None:
                continue
            if key == "notes" and append_notes and client.notes:
                value = f"{client.notes}\n{value}"
            setattr(client, key, value)
        client.updated_at = now_utc()
        await s.commit()
        await s.refresh(client)
        return client


async def delete_client(sf: SessionFactory, client_id: int) -> Client:
    async with sf() as s:
        client = await s.get(Client, client_id)
        if client is None:
            raise NotFoundError(f"Клиент #{client_id} не найден")
        await s.delete(client)
        await s.commit()
        return client


async def find_clients(
    sf: SessionFactory, query: str | None = None, status: str | None = None, limit: int = 30
) -> list[Client]:
    _check_status(status)
    stmt = select(Client)
    if status:
        stmt = stmt.where(Client.status == status)
    if query:
        # SQLite lower() не понимает кириллицу — фильтруем в Python.
        rows = (await _all(sf, stmt)).copy()
        q = query.lower().strip()
        return [
            c
            for c in rows
            if q
            in " ".join(
                [c.company, c.industry, c.contact_name, c.email, c.phone, c.telegram, c.notes]
            ).lower()
        ][:limit]
    stmt = stmt.order_by(Client.updated_at.desc()).limit(limit)
    return await _all(sf, stmt)


async def _all(sf: SessionFactory, stmt) -> list[Client]:
    async with sf() as s:
        return list((await s.scalars(stmt)).all())


async def resolve_client(sf: SessionFactory, client_id: int | None, name: str | None) -> Client:
    """Находит клиента по id или названию; если по названию несколько — ошибка с вариантами."""
    if client_id:
        return await get_client(sf, client_id)
    if not name:
        raise ValueError("Укажите id клиента или название компании")
    matches = await find_clients(sf, query=name)
    exact = [c for c in matches if c.company.lower() == name.lower().strip()]
    if len(exact) == 1:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise NotFoundError(f"Клиент «{name}» не найден")
    variants = ", ".join(f"#{c.id} {c.company}" for c in matches[:10])
    raise ValueError(f"Найдено несколько клиентов: {variants}. Уточните id.")


async def add_interaction(
    sf: SessionFactory,
    client_id: int,
    summary: str,
    kind: str = "note",
    occurred_at: datetime | None = None,
) -> Interaction:
    if kind not in INTERACTION_KINDS:
        raise ValueError(f"Тип взаимодействия: {', '.join(INTERACTION_KINDS)}")
    if not (summary or "").strip():
        raise ValueError("Опишите взаимодействие")
    async with sf() as s:
        client = await s.get(Client, client_id)
        if client is None:
            raise NotFoundError(f"Клиент #{client_id} не найден")
        item = Interaction(
            client_id=client_id, kind=kind, summary=summary.strip(), occurred_at=occurred_at
        )
        if item.occurred_at is None:
            item.occurred_at = now_utc()
        client.updated_at = now_utc()
        s.add(item)
        await s.commit()
        await s.refresh(item)
        return item


async def interactions_between(
    sf: SessionFactory, start: datetime, end: datetime
) -> list[tuple[Interaction, str]]:
    async with sf() as s:
        rows = await s.execute(
            select(Interaction, Client.company)
            .join(Client)
            .where(Interaction.occurred_at >= start, Interaction.occurred_at < end)
            .order_by(Interaction.occurred_at)
        )
        return [(i, company) for i, company in rows.all()]


async def pipeline(sf: SessionFactory) -> dict[str, list[Client]]:
    async with sf() as s:
        rows = (await s.scalars(select(Client).order_by(Client.updated_at.desc()))).all()
    result: dict[str, list[Client]] = {status: [] for status in CLIENT_STATUSES}
    for c in rows:
        result.setdefault(c.status, []).append(c)
    return result


async def count_clients(sf: SessionFactory) -> int:
    async with sf() as s:
        return int(await s.scalar(select(func.count(Client.id))) or 0)


def format_pipeline(data: dict[str, list[Client]]) -> str:
    total = sum(len(v) for v in data.values())
    if not total:
        return "В базе пока нет клиентов. Напишите, например: «Добавь клиента ООО Ромашка, ритейл»."
    lines = [f"📊 <b>Воронка продаж</b> (всего {total})", ""]
    for status, label in CLIENT_STATUSES.items():
        items = data.get(status, [])
        bar = "█" * min(len(items), 20)
        lines.append(f"{label}: <b>{len(items)}</b> {bar}")
        for c in items[:5]:
            lines.append(f"   • #{c.id} {esc(c.company)}")
        if len(items) > 5:
            lines.append(f"   … и ещё {len(items) - 5}")
    return "\n".join(lines)


def format_client_card(client: Client, tz: str, history_limit: int = 10) -> str:
    lines = [
        f"🏢 <b>{esc(client.company)}</b> (#{client.id})",
        f"Статус: {CLIENT_STATUSES.get(client.status, client.status)}",
    ]
    fields = [
        ("Сфера", client.industry),
        ("Контакт", client.contact_name),
        ("Телефон", client.phone),
        ("Email", client.email),
        ("Telegram", client.telegram),
        ("Сайт", client.website),
    ]
    lines += [f"{k}: {esc(v)}" for k, v in fields if v]
    if client.notes:
        lines.append(f"📝 Заметки: {esc(client.notes)}")
    interactions = list(client.interactions or [])
    if interactions:
        lines.append("")
        lines.append("<b>История:</b>")
        for i in interactions[-history_limit:]:
            kind = INTERACTION_KINDS.get(i.kind, i.kind)
            lines.append(f"• {fmt_dt(i.occurred_at, tz)} — {kind}: {esc(i.summary)}")
    return "\n".join(lines)


def client_to_dict(client: Client, tz: str, with_history: bool = False) -> dict:
    data = {
        "id": client.id,
        "company": client.company,
        "industry": client.industry,
        "contact_name": client.contact_name,
        "phone": client.phone,
        "email": client.email,
        "telegram": client.telegram,
        "website": client.website,
        "status": client.status,
        "notes": client.notes,
    }
    if with_history:
        data["history"] = [
            {"when": fmt_dt(i.occurred_at, tz), "kind": i.kind, "summary": i.summary}
            for i in (client.interactions or [])[-20:]
        ]
    return data

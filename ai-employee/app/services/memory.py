"""Память агента: история диалога, резюме старых сообщений и важные факты."""

from __future__ import annotations

from sqlalchemy import delete, select

from app.constants import FACT_CATEGORIES
from app.database.models import Client, ConversationSummary, Fact, Message
from app.database.session import SessionFactory
from app.services.tasks import NotFoundError


async def add_message(sf: SessionFactory, user_id: int, role: str, content: str) -> Message:
    async with sf() as s:
        msg = Message(user_id=user_id, role=role, content=content)
        s.add(msg)
        await s.commit()
        await s.refresh(msg)
        return msg


async def get_summary(sf: SessionFactory, user_id: int) -> ConversationSummary | None:
    async with sf() as s:
        return await s.get(ConversationSummary, user_id)


async def unsummarized_messages(sf: SessionFactory, user_id: int) -> list[Message]:
    summary = await get_summary(sf, user_id)
    last_id = summary.last_message_id if summary else 0
    async with sf() as s:
        rows = await s.scalars(
            select(Message)
            .where(Message.user_id == user_id, Message.id > last_id)
            .order_by(Message.id)
        )
        return list(rows.all())


async def save_summary(sf: SessionFactory, user_id: int, text: str, last_message_id: int) -> None:
    async with sf() as s:
        row = await s.get(ConversationSummary, user_id)
        if row is None:
            row = ConversationSummary(user_id=user_id)
            s.add(row)
        row.summary = text
        row.last_message_id = last_message_id
        await s.commit()


async def clear_history(sf: SessionFactory, user_id: int) -> None:
    async with sf() as s:
        await s.execute(delete(Message).where(Message.user_id == user_id))
        await s.execute(delete(ConversationSummary).where(ConversationSummary.user_id == user_id))
        await s.commit()


def build_history(messages: list[Message], limit: int) -> list[dict]:
    """Последние сообщения в формате Messages API: роли чередуются, первая — user."""
    recent = messages[-limit:] if limit > 0 else []
    result: list[dict] = []
    for m in recent:
        role = "assistant" if m.role == "assistant" else "user"
        if result and result[-1]["role"] == role:
            result[-1]["content"] += "\n\n" + m.content
        else:
            result.append({"role": role, "content": m.content})
    while result and result[0]["role"] != "user":
        result.pop(0)
    return result


# --- Факты ---------------------------------------------------------------


async def add_fact(
    sf: SessionFactory, content: str, category: str = "company", client_id: int | None = None
) -> Fact:
    content = (content or "").strip()
    if not content:
        raise ValueError("Пустой факт")
    if category not in FACT_CATEGORIES:
        raise ValueError(f"Категория: {', '.join(FACT_CATEGORIES)}")
    async with sf() as s:
        if client_id is not None and await s.get(Client, client_id) is None:
            raise NotFoundError(f"Клиент #{client_id} не найден")
        fact = Fact(content=content, category=category, client_id=client_id)
        s.add(fact)
        await s.commit()
        await s.refresh(fact)
        return fact


async def list_facts(
    sf: SessionFactory, client_id: int | None = None, limit: int = 100
) -> list[Fact]:
    stmt = select(Fact).order_by(Fact.id.desc()).limit(limit)
    if client_id is not None:
        stmt = select(Fact).where(Fact.client_id == client_id).order_by(Fact.id.desc()).limit(limit)
    async with sf() as s:
        return list(reversed((await s.scalars(stmt)).all()))


async def get_fact(sf: SessionFactory, fact_id: int) -> Fact:
    async with sf() as s:
        fact = await s.get(Fact, fact_id)
        if fact is None:
            raise NotFoundError(f"Факт #{fact_id} не найден")
        return fact


async def delete_fact(sf: SessionFactory, fact_id: int) -> Fact:
    async with sf() as s:
        fact = await s.get(Fact, fact_id)
        if fact is None:
            raise NotFoundError(f"Факт #{fact_id} не найден")
        await s.delete(fact)
        await s.commit()
        return fact


def format_facts(facts: list[Fact]) -> str:
    if not facts:
        return "—"
    lines = []
    for f in facts:
        suffix = f" (клиент #{f.client_id})" if f.client_id else ""
        lines.append(f"#{f.id} [{FACT_CATEGORIES.get(f.category, f.category)}{suffix}] {f.content}")
    return "\n".join(lines)

"""Учёт расходов на Claude API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from sqlalchemy import func, select

from app.config import price_for
from app.database.models import UsageRecord
from app.database.session import SessionFactory
from app.services.timeutils import get_tz, now_local


def calc_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    price_in, price_out = price_for(model)
    cost = (
        input_tokens * price_in
        + output_tokens * price_out
        + cache_write_tokens * price_in * 1.25
        + cache_read_tokens * price_in * 0.1
    ) / 1_000_000
    return round(cost, 6)


async def record_usage(
    sf: SessionFactory,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    purpose: str = "chat",
    user_id: int | None = None,
) -> UsageRecord:
    cost = calc_cost(model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)
    async with sf() as s:
        rec = UsageRecord(
            user_id=user_id,
            model=model,
            purpose=purpose,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            cost_usd=cost,
        )
        s.add(rec)
        await s.commit()
        return rec


@dataclass
class UsageTotals:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


def period_starts(tz_name: str) -> tuple[datetime, datetime]:
    """Начало текущих суток и месяца (в местном времени), как aware-datetime."""
    tz = get_tz(tz_name)
    now = now_local(tz_name)
    day_start = datetime.combine(now.date(), time.min, tzinfo=tz)
    month_start = datetime.combine(now.date().replace(day=1), time.min, tzinfo=tz)
    return day_start, month_start


async def totals_since(sf: SessionFactory, since: datetime) -> UsageTotals:
    async with sf() as s:
        row = (
            await s.execute(
                select(
                    func.count(UsageRecord.id),
                    func.coalesce(
                        func.sum(
                            UsageRecord.input_tokens
                            + UsageRecord.cache_read_tokens
                            + UsageRecord.cache_write_tokens
                        ),
                        0,
                    ),
                    func.coalesce(func.sum(UsageRecord.output_tokens), 0),
                    func.coalesce(func.sum(UsageRecord.cost_usd), 0.0),
                ).where(UsageRecord.created_at >= since)
            )
        ).one()
    return UsageTotals(int(row[0]), int(row[1]), int(row[2]), float(row[3]))


async def totals_by_model(sf: SessionFactory, since: datetime) -> list[tuple[str, int, float]]:
    async with sf() as s:
        rows = await s.execute(
            select(UsageRecord.model, func.count(UsageRecord.id), func.sum(UsageRecord.cost_usd))
            .where(UsageRecord.created_at >= since)
            .group_by(UsageRecord.model)
            .order_by(func.sum(UsageRecord.cost_usd).desc())
        )
        return [(m, int(n), float(c or 0)) for m, n, c in rows.all()]


async def usage_report(
    sf: SessionFactory, tz_name: str, daily_budget: float = 0.0, monthly_budget: float = 0.0
) -> str:
    day_start, month_start = period_starts(tz_name)
    day = await totals_since(sf, day_start)
    month = await totals_since(sf, month_start)
    by_model = await totals_by_model(sf, month_start)

    def block(title: str, t: UsageTotals, budget: float) -> list[str]:
        lines = [
            f"<b>{title}</b>",
            f"Запросов к ИИ: {t.requests}",
            f"Токены: {t.input_tokens:,} вход / {t.output_tokens:,} выход".replace(",", " "),
            f"Стоимость: <b>${t.cost_usd:.4f}</b>",
        ]
        if budget > 0:
            lines.append(f"Лимит: ${budget:.2f} (использовано {t.cost_usd / budget * 100:.0f}%)")
        return lines

    lines = ["💰 <b>Расходы на ИИ</b>", ""]
    lines += block("Сегодня", day, daily_budget)
    lines.append("")
    lines += block("Этот месяц", month, monthly_budget)
    if by_model:
        lines += ["", "<b>По моделям за месяц:</b>"]
        lines += [f"• {m}: {n} запр., ${c:.4f}" for m, n, c in by_model]
    return "\n".join(lines)

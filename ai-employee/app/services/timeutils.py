"""Работа со временем и часовыми поясами."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]  # fmt: skip

TIME_RE = re.compile(r"^\s*([01]?\d|2[0-3])[:.]([0-5]\d)\s*$")


def get_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Europe/Moscow")


def is_valid_tz(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_local(tz_name: str) -> datetime:
    return datetime.now(get_tz(tz_name))


def parse_hhmm(value: str) -> str | None:
    """'9:00', '09.30' → '09:00' / '09:30'; None если формат неверный."""
    m = TIME_RE.match(value or "")
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def parse_local_datetime(value: str | None, tz_name: str) -> datetime | None:
    """ISO-строку в местном времени ('2026-10-03T10:00' или '2026-10-03') → UTC.

    Дата без времени трактуется как 09:00 местного времени. Если в строке указан
    часовой пояс — он учитывается.
    """
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    value = value.replace(" ", "T", 1) if "T" not in value and " " in value else value
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        if len(value) == 10:
            d = date.fromisoformat(value)
            dt = datetime.combine(d, time(9, 0))
        else:
            dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Не удалось разобрать дату «{value}». Нужен формат ГГГГ-ММ-ДДTЧЧ:ММ"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=get_tz(tz_name))
    return dt.astimezone(UTC)


def to_local(dt: datetime, tz_name: str) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(get_tz(tz_name))


def fmt_dt(dt: datetime | None, tz_name: str, with_weekday: bool = False) -> str:
    """Человекочитаемая дата: 'сегодня 10:00', 'завтра 09:30', '5 октября 14:00'."""
    if dt is None:
        return "—"
    local = to_local(dt, tz_name)
    today = now_local(tz_name).date()
    hhmm = local.strftime("%H:%M")
    if local.date() == today:
        day = "сегодня"
    elif local.date() == today + timedelta(days=1):
        day = "завтра"
    elif local.date() == today - timedelta(days=1):
        day = "вчера"
    else:
        day = f"{local.day} {MONTHS[local.month - 1]}"
        if local.year != today.year:
            day += f" {local.year}"
        if with_weekday:
            day += f" ({WEEKDAYS[local.weekday()]})"
    return f"{day} {hhmm}"


def fmt_date_long(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year}"


def local_day_bounds(day: date, tz_name: str) -> tuple[datetime, datetime]:
    """Начало и конец местных суток в UTC."""
    tz = get_tz(tz_name)
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)

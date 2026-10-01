from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from app.texts import labels, t


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₽"


def h(value: object) -> str:
    """Экранирование пользовательских данных для parse_mode=HTML."""
    return escape(str(value), quote=False)


def status_label(status: str) -> str:
    return labels("status").get(status, status)


def delivery_label(method: str) -> str:
    return labels("delivery").get(method, method)


def gender_label(gender: str) -> str:
    return labels("gender").get(gender, gender)


def style_label(style: str) -> str:
    return labels("style").get(style, style)


def payment_label(method: str) -> str:
    return labels("payment").get(method, method)


def local_dt(value: datetime | None, tz: str = "Europe/Moscow") -> str:
    if value is None:
        return "—"
    return value.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(tz)).strftime("%d.%m.%Y %H:%M")


def days_range(days_min: int, days_max: int) -> str:
    if days_min == days_max:
        return t("delivery.days_one", days=days_min)
    return t("delivery.days_range", dmin=days_min, dmax=days_max)


def price_line(price: int, old_price: int | None) -> str:
    if old_price and old_price > price:
        percent = round((old_price - price) * 100 / old_price)
        return f"<b>{money(price)}</b>  <s>{money(old_price)}</s>  −{percent}%"
    return f"<b>{money(price)}</b>"

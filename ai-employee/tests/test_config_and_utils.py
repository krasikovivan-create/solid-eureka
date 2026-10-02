from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings, price_for
from app.services.textutils import esc, md_to_html, split_message, strip_html
from app.services.timeutils import (
    fmt_dt,
    local_day_bounds,
    now_local,
    parse_hhmm,
    parse_local_datetime,
)


def test_allowed_ids_parsing():
    s = Settings(ALLOWED_USER_IDS="1, 2;3 4", _env_file=None)
    assert s.allowed_user_ids == [1, 2, 3, 4]
    assert Settings(ALLOWED_USER_IDS="", _env_file=None).allowed_user_ids == []


def test_allowed_ids_from_env(monkeypatch):
    monkeypatch.setenv("ALLOWED_USER_IDS", "555,777")
    monkeypatch.setenv("MODEL_FAST", "claude-haiku-4-5")
    s = Settings(_env_file=None)
    assert s.allowed_user_ids == [555, 777]


def test_defaults_and_missing():
    s = Settings(_env_file=None, TELEGRAM_BOT_TOKEN="", ANTHROPIC_API_KEY="")
    assert s.model_smart == "claude-sonnet-5-5"
    assert s.model_fast == "claude-haiku-4-5"
    assert set(s.missing_required()) == {"TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY"}


def test_price_for_longest_prefix():
    assert price_for("claude-sonnet-5-5") == (2.0, 10.0)
    assert price_for("claude-haiku-4-5") == (1.0, 5.0)
    assert price_for("claude-opus-5-5") == (4.0, 20.0)
    assert price_for("claude-opus-5") == (5.0, 25.0)
    assert price_for("unknown-model") == (4.0, 20.0)


def test_parse_hhmm():
    assert parse_hhmm("9:00") == "09:00"
    assert parse_hhmm("18.30") == "18:30"
    assert parse_hhmm("25:00") is None
    assert parse_hhmm("abc") is None


def test_parse_local_datetime_moscow():
    dt = parse_local_datetime("2026-10-03T10:00", "Europe/Moscow")
    assert dt == datetime(2026, 10, 3, 7, 0, tzinfo=UTC)
    # дата без времени → 09:00
    assert parse_local_datetime("2026-10-03", "Europe/Moscow") == datetime(
        2026, 10, 3, 6, 0, tzinfo=UTC
    )
    assert parse_local_datetime(None, "Europe/Moscow") is None
    with pytest.raises(ValueError):
        parse_local_datetime("завтра", "Europe/Moscow")


def test_fmt_dt_relative():
    tz = "Europe/Moscow"
    now = now_local(tz)
    tomorrow = (now + timedelta(days=1)).replace(hour=10, minute=0)
    assert fmt_dt(tomorrow.astimezone(UTC), tz) == "завтра 10:00"
    assert fmt_dt(None, tz) == "—"


def test_day_bounds():
    start, end = local_day_bounds(datetime(2026, 10, 3).date(), "Europe/Moscow")
    assert start == datetime(2026, 10, 2, 21, 0, tzinfo=UTC)
    assert end - start == timedelta(days=1)


def test_md_to_html_escapes_and_formats():
    html = md_to_html("**Важно** <script> & `code` \n# Заголовок\n- пункт")
    assert "<b>Важно</b>" in html
    assert "&lt;script&gt;" in html
    assert "<code>code</code>" in html
    assert "<b>Заголовок</b>" in html
    assert "• пункт" in html


def test_split_and_strip():
    parts = split_message("строка\n" * 2000, limit=1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "".join(p + "\n" for p in parts).count("строка") == 2000
    assert strip_html("<b>a</b> &amp; b") == "a & b"
    assert esc("<a>") == "&lt;a&gt;"

"""Форматирование текста для Telegram (HTML)."""

from __future__ import annotations

import html
import re

TG_LIMIT = 4000


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


_CODE_BLOCK = re.compile(r"```(?:\w+)?\n?(.*?)```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BULLET = re.compile(r"^(\s*)[-*]\s+", re.MULTILINE)


def md_to_html(text: str) -> str:
    """Безопасно превращает простой Markdown ответа модели в HTML для Telegram."""
    placeholders: list[str] = []

    def keep(fragment: str) -> str:
        placeholders.append(fragment)
        return f"\x00{len(placeholders) - 1}\x00"

    text = _CODE_BLOCK.sub(lambda m: keep(f"<pre>{esc(m.group(1).strip())}</pre>"), text)
    text = _INLINE_CODE.sub(lambda m: keep(f"<code>{esc(m.group(1))}</code>"), text)
    text = esc(text)
    text = _HEADING.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _ITALIC.sub(lambda m: f"<i>{m.group(1)}</i>", text)
    text = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    text = _BULLET.sub(lambda m: f"{m.group(1)}• ", text)
    text = re.sub(r"^\s*---+\s*$", "", text, flags=re.MULTILINE)
    return re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], text)


def strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def split_message(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Режет длинный текст на части по границам строк."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts

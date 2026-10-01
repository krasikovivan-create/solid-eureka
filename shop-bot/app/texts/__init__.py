"""Тексты бота. Чтобы добавить язык, создайте модуль с тем же набором ключей
и зарегистрируйте его в LOCALES."""

from __future__ import annotations

from app.texts import ru

DEFAULT_LANG = "ru"
LOCALES: dict[str, dict[str, str]] = {"ru": ru.TEXTS}


def t(key: str, lang: str = DEFAULT_LANG, /, **kwargs: object) -> str:
    texts = LOCALES.get(lang) or LOCALES[DEFAULT_LANG]
    template = texts.get(key) or LOCALES[DEFAULT_LANG].get(key)
    if template is None:
        raise KeyError(f"Нет текста для ключа {key!r}")
    return template.format(**kwargs) if kwargs else template


def labels(prefix: str, lang: str = DEFAULT_LANG) -> dict[str, str]:
    """Все тексты вида «prefix.<код>» → {код: текст} (статусы, способы доставки и т.п.)."""
    texts = LOCALES.get(lang) or LOCALES[DEFAULT_LANG]
    start = prefix + "."
    return {k.removeprefix(start): v for k, v in texts.items() if k.startswith(start)}

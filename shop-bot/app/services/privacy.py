"""Политика обработки персональных данных (152-ФЗ), собранная из настроек магазина."""

from __future__ import annotations

from html import escape

from app.services.shop_config import ShopConfig
from app.texts import t


def _operator(shop: ShopConfig) -> str:
    return shop.operator or t("privacy.operator_default", shop=shop.shop_name)


def privacy_policy_text(shop: ShopConfig) -> str:
    """Текст для Telegram (parse_mode=HTML)."""
    return t(
        "privacy.policy",
        shop=escape(shop.shop_name),
        operator=escape(_operator(shop)),
    )


def privacy_policy_html(shop: ShopConfig) -> str:
    """Та же политика веб-страницей — для ссылки в платёжном провайдере и т.п."""
    body = privacy_policy_text(shop).replace("\n", "<br>\n")
    title = escape(t("privacy.title", shop=shop.shop_name))
    return (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{title}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:24px auto;"
        "padding:0 16px;line-height:1.5;color:#222;background:#fff}</style></head>"
        f"<body>{body}</body></html>"
    )

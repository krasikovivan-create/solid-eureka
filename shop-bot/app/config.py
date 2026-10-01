"""Настройки приложения. Все секреты читаются только из окружения / .env."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Telegram ---
    bot_token: SecretStr = SecretStr("")
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    shop_name: str = "Fashion Store"
    banner_url: str = "https://placehold.co/1200x600/png?text=Fashion+Store"
    manager_username: str = ""
    privacy_policy_url: str = "https://example.com/privacy"

    # --- Режим запуска: polling (по умолчанию) или webhook ---
    # На Render адрес сервиса подставляется сам из RENDER_EXTERNAL_URL.
    webhook_url: str = Field(
        default="", validation_alias=AliasChoices("WEBHOOK_URL", "RENDER_EXTERNAL_URL")
    )
    webhook_path: str = "/webhook"
    webhook_secret: SecretStr = SecretStr("")
    # Бесплатный Render усыпляет сервис через 15 минут без запросов, и фоновые задачи
    # (напоминания, отложенные рассылки) встают. KEEP_AWAKE=true — бот сам пингует свой
    # /health каждые 10 минут (нужен WEBHOOK_URL / RENDER_EXTERNAL_URL).
    keep_awake: bool = False
    host: str = "0.0.0.0"
    port: int = 8080

    # --- База данных ---
    database_url: str = "sqlite+aiosqlite:///./shop.db"
    db_echo: bool = False
    # Хранилище FSM: без REDIS_URL — в памяти (состояния диалогов сбрасываются при перезапуске).
    redis_url: str = ""

    # --- Оплата ---
    # fake — тестовая кнопка «Оплатить» без провайдера;
    # telegram — счёт Telegram Payments (токен ЮKassa из @BotFather, тестовый или боевой).
    payments_mode: Literal["fake", "telegram"] = "fake"
    payment_provider_token: SecretStr = SecretStr("")
    currency: str = "RUB"
    cod_enabled: bool = True
    send_receipt: bool = False  # передавать чек 54-ФЗ в ЮKassa через provider_data
    vat_code: int = 1  # 1 — без НДС (коды ЮKassa)
    unpaid_order_ttl_hours: int = 24

    # --- Доставка ---
    pickup_address: str = "Москва, ул. Тверская, 1, шоурум (ежедневно 10:00–21:00)"
    mock_tracking_autoadvance: bool = False

    # --- Маркетинг ---
    abandoned_cart_hours: int = 24
    referral_bonus: int = 300
    max_bonus_share_percent: int = 30
    broadcast_rate_per_sec: int = 25

    # --- Защита от флуда ---
    throttle_rate: float = 0.4

    # --- ИИ-стилист ---
    stylist_enabled: bool = True
    anthropic_api_key: SecretStr = SecretStr("")
    stylist_model: str = "claude-haiku-4-5-20251001"
    stylist_daily_limit: int = 20
    stylist_timeout: float = 45.0
    stylist_max_retries: int = 2
    stylist_max_tokens: int = 2048
    stylist_history_size: int = 10

    # --- Прочее ---
    timezone: str = "Europe/Moscow"
    log_level: str = "INFO"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.replace(";", ",").split(",") if part.strip()]
        if isinstance(value, int):
            return [value]
        return value

    @property
    def is_webhook(self) -> bool:
        return bool(self.webhook_url)

    @property
    def stylist_available(self) -> bool:
        return self.stylist_enabled and bool(self.anthropic_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()

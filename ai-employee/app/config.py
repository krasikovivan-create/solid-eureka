"""Настройки приложения из переменных окружения."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Цены моделей Claude, долларов за 1 млн токенов: (вход, выход).
# Запись в кэш стоит 1.25× входа, чтение из кэша — 0.1× входа.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
DEFAULT_PRICE = (4.0, 20.0)


def price_for(model: str) -> tuple[float, float]:
    """Цена модели: ищем самый длинный подходящий префикс."""
    best: tuple[int, tuple[float, float]] | None = None
    for prefix, price in MODEL_PRICES.items():
        if model.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), price)
    return best[1] if best else DEFAULT_PRICE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    allowed_user_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list, alias="ALLOWED_USER_IDS"
    )
    db_path: str = Field(default="data/bot.db", alias="DB_PATH")
    model_smart: str = Field(default="claude-sonnet-5-5", alias="MODEL_SMART")
    model_fast: str = Field(default="claude-haiku-4-5", alias="MODEL_FAST")

    default_timezone: str = Field(default="Europe/Moscow", alias="DEFAULT_TIMEZONE")
    max_tokens_per_request: int = Field(default=4096, alias="MAX_TOKENS_PER_REQUEST")
    max_tokens_long: int = Field(default=12000, alias="MAX_TOKENS_LONG")
    max_tool_iterations: int = Field(default=8, alias="MAX_TOOL_ITERATIONS")
    daily_budget_usd: float = Field(default=0.0, alias="DAILY_BUDGET_USD")
    monthly_budget_usd: float = Field(default=0.0, alias="MONTHLY_BUDGET_USD")
    history_limit: int = Field(default=20, alias="HISTORY_LIMIT")
    port: int = Field(default=8080, alias="PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _parse_ids(cls, value: object) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, int):
            return [value]
        if isinstance(value, (list, tuple)):
            return [int(v) for v in value]
        parts = str(value).replace(";", ",").replace(" ", ",").split(",")
        return [int(p) for p in parts if p.strip()]

    @property
    def data_dir(self) -> Path:
        return Path(self.db_path).expanduser().resolve().parent

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{Path(self.db_path).expanduser().resolve()}"

    def missing_required(self) -> list[str]:
        missing = []
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()

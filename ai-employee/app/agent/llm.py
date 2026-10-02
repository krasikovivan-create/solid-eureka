"""Обёртка над Claude API: лимиты, учёт стоимости, понятные ошибки."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import anthropic

from app.config import Settings
from app.database.session import SessionFactory
from app.services import usage as usage_service
from app.services.profile import get_profile
from app.services.usage import period_starts, totals_since

log = logging.getLogger(__name__)


class LLMError(Exception):
    """Ошибка с понятным пользователю текстом."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class BudgetExceededError(LLMError):
    pass


class LLMRefusalError(LLMError):
    pass


def friendly_api_error(exc: Exception) -> str:
    if isinstance(exc, anthropic.AuthenticationError):
        return "🔑 Ключ Anthropic API не подходит. Проверьте переменную ANTHROPIC_API_KEY."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return (
            "🔒 У ключа Anthropic API нет доступа к этой модели. Проверьте MODEL_SMART/MODEL_FAST."
        )
    if isinstance(exc, anthropic.NotFoundError):
        return "❓ Модель не найдена. Проверьте значения MODEL_SMART и MODEL_FAST."
    if isinstance(exc, anthropic.RateLimitError):
        return "⏳ Слишком много запросов к ИИ. Подождите минуту и повторите."
    if isinstance(exc, anthropic.BadRequestError):
        text = str(exc).lower()
        if "credit" in text or "balance" in text:
            return "💳 На балансе Anthropic закончились средства. Пополните его в console.anthropic.com."
        return "⚠️ ИИ не смог обработать запрос. Попробуйте переформулировать."
    if isinstance(exc, anthropic.InternalServerError):
        return "🛠 Сервис ИИ временно перегружен. Повторите через минуту."
    if isinstance(exc, anthropic.APITimeoutError):
        return "⌛ ИИ отвечал слишком долго. Повторите запрос."
    if isinstance(exc, anthropic.APIConnectionError):
        return "📡 Нет связи с сервисом ИИ. Повторите чуть позже."
    return "⚠️ Ошибка при обращении к ИИ. Подробности записаны в лог."


def _supports_effort(model: str) -> bool:
    return "haiku" not in model and "claude-3" not in model


class LLM:
    def __init__(self, settings: Settings, sf: SessionFactory, client: Any | None = None) -> None:
        self.settings = settings
        self.sf = sf
        self.client = client or anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key or None, max_retries=3, timeout=180.0
        )

    @property
    def smart(self) -> str:
        return self.settings.model_smart

    @property
    def fast(self) -> str:
        return self.settings.model_fast

    async def check_budget(self) -> None:
        daily = self.settings.daily_budget_usd
        monthly = self.settings.monthly_budget_usd
        if daily <= 0 and monthly <= 0:
            return
        profile = await get_profile(self.sf)
        day_start, month_start = period_starts(profile.timezone)
        if daily > 0 and (await totals_since(self.sf, day_start)).cost_usd >= daily:
            raise BudgetExceededError(
                f"💸 Дневной лимит расходов на ИИ (${daily:.2f}) исчерпан. "
                "Он обновится завтра, а изменить его можно переменной DAILY_BUDGET_USD."
            )
        if monthly > 0 and (await totals_since(self.sf, month_start)).cost_usd >= monthly:
            raise BudgetExceededError(
                f"💸 Месячный лимит расходов на ИИ (${monthly:.2f}) исчерпан. "
                "Изменить его можно переменной MONTHLY_BUDGET_USD."
            )

    async def create(
        self,
        *,
        model: str,
        messages: list[dict],
        system: str | list[dict] | None = None,
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        purpose: str = "chat",
        user_id: int | None = None,
        output_schema: dict | None = None,
        effort: str | None = None,
    ) -> Any:
        """Один запрос к Messages API с учётом расходов. Возвращает ответ SDK."""
        await self.check_budget()
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or self.settings.max_tokens_per_request,
            "messages": messages,
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = tools
        output_config: dict[str, Any] = {}
        if output_schema:
            output_config["format"] = {"type": "json_schema", "schema": output_schema}
        if effort and _supports_effort(model):
            output_config["effort"] = effort
        if output_config:
            params["output_config"] = output_config
        try:
            response = await self.client.messages.create(**params)
        except anthropic.APIError as exc:
            log.exception("Ошибка Claude API (%s, %s)", model, purpose)
            raise LLMError(friendly_api_error(exc)) from exc
        await self._record(response, model, purpose, user_id)
        return response

    async def _record(self, response: Any, model: str, purpose: str, user_id: int | None) -> None:
        u = getattr(response, "usage", None)
        if u is None:
            return
        try:
            await usage_service.record_usage(
                self.sf,
                model=getattr(response, "model", None) or model,
                input_tokens=int(getattr(u, "input_tokens", 0) or 0),
                output_tokens=int(getattr(u, "output_tokens", 0) or 0),
                cache_read_tokens=int(getattr(u, "cache_read_input_tokens", 0) or 0),
                cache_write_tokens=int(getattr(u, "cache_creation_input_tokens", 0) or 0),
                purpose=purpose,
                user_id=user_id,
            )
        except Exception:  # учёт не должен ломать ответ
            log.exception("Не удалось записать расход")

    async def complete_text(
        self,
        *,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        purpose: str = "text",
        user_id: int | None = None,
        effort: str | None = None,
    ) -> str:
        model = model or self.fast
        response = await self.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            system=system,
            max_tokens=max_tokens,
            purpose=purpose,
            user_id=user_id,
            effort=effort,
        )
        if response.stop_reason == "refusal":
            if model != self.fast:
                log.warning("Модель %s отказалась, пробую %s", model, self.fast)
                return await self.complete_text(
                    prompt=prompt,
                    system=system,
                    model=self.fast,
                    max_tokens=max_tokens,
                    purpose=purpose,
                    user_id=user_id,
                )
            raise LLMRefusalError(
                "🙅 ИИ отказался выполнять этот запрос. Попробуйте переформулировать."
            )
        return response_text(response)

    async def complete_json(
        self,
        *,
        prompt: str,
        schema: dict,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        purpose: str = "json",
        user_id: int | None = None,
        effort: str | None = None,
    ) -> dict:
        model = model or self.smart
        response = await self.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            system=system,
            max_tokens=max_tokens or self.settings.max_tokens_long,
            purpose=purpose,
            user_id=user_id,
            output_schema=schema,
            effort=effort,
        )
        if response.stop_reason == "refusal":
            raise LLMRefusalError("🙅 ИИ отказался выполнять этот запрос.")
        if response.stop_reason == "max_tokens":
            raise LLMError(
                "✂️ Ответ ИИ не поместился в лимит токенов. Увеличьте MAX_TOKENS_LONG и повторите."
            )
        return parse_json(response_text(response))


def response_text(response: Any) -> str:
    parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    return "\n".join(p for p in parts if p).strip()


def parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise LLMError("⚠️ ИИ вернул ответ в неожиданном формате. Повторите попытку.")

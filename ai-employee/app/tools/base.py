"""Реестр инструментов агента и общий контекст их выполнения."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.llm import LLMError
from app.context import AppContext

log = logging.getLogger(__name__)


@dataclass
class OutText:
    """Готовый HTML-текст, который бот отправит пользователю как есть."""

    text: str


@dataclass
class OutFile:
    filename: str
    data: bytes
    caption: str = ""


@dataclass
class OutConfirm:
    """Запрос подтверждения удаления: kind — task/client/document/fact."""

    kind: str
    object_id: int
    label: str


@dataclass
class OutAuditStarted:
    audit_id: int


@dataclass
class ToolContext:
    app: AppContext
    user_id: int
    tz: str
    outbox: list[Any] = field(default_factory=list)


ToolHandler = Callable[..., Awaitable[Any]]


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: ToolHandler

    def definition(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, description: str, properties: dict, required=()):
        schema = {"type": "object", "properties": properties, "required": list(required)}

        def deco(fn: ToolHandler) -> ToolHandler:
            if name in self._tools:
                raise ValueError(f"Инструмент {name} уже зарегистрирован")
            self._tools[name] = Tool(name, description, schema, fn)
            return fn

        return deco

    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> list[dict]:
        return [t.definition() for t in self._tools.values()]

    async def execute(self, ctx: ToolContext, name: str, arguments: dict) -> tuple[str, bool]:
        """Выполняет инструмент. Возвращает (результат-строка, is_error)."""
        tool = self._tools.get(name)
        if tool is None:
            return f"Неизвестный инструмент: {name}", True
        if not isinstance(arguments, dict):
            return "Аргументы должны быть объектом", True
        args = {k: v for k, v in arguments.items() if v is not None}
        try:
            result = await tool.handler(ctx, **args)
        except TypeError as exc:
            log.warning("Неверные аргументы %s: %s", name, exc)
            return f"Неверные аргументы: {exc}", True
        except LLMError as exc:
            return exc.user_message, True
        except ValueError as exc:
            return str(exc), True
        except Exception as exc:
            log.exception("Ошибка инструмента %s", name)
            return f"Внутренняя ошибка инструмента: {type(exc).__name__}", True
        if isinstance(result, str):
            return result, False
        return json.dumps(result, ensure_ascii=False, default=str), False


registry = ToolRegistry()

# Схемы часто используемых полей.
S_STR = {"type": "string"}
S_INT = {"type": "integer"}
S_BOOL = {"type": "boolean"}
S_DT = {
    "type": "string",
    "description": "Местное время компании в формате ГГГГ-ММ-ДДTЧЧ:ММ (например 2026-10-03T10:00)",
}

"""Агент: свободный диалог с вызовом инструментов (tool use)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.agent import workflows
from app.agent.llm import response_text
from app.agent.prompts import build_system
from app.context import AppContext
from app.services import memory as memory_service
from app.services.profile import get_profile
from app.tools import ToolContext, ToolRegistry, registry

log = logging.getLogger(__name__)

SMART_HINTS = re.compile(
    r"проанализ|анализ|стратег|сравни|подробн|придумай|предложи|продума|бизнес-план|"
    r"план развития|исследу|оцени|почему|объясни",
    re.IGNORECASE,
)


def choose_model(app: AppContext, text: str) -> str:
    """Простые просьбы — быстрая модель, длинные и аналитические — умная."""
    if len(text) > 600 or SMART_HINTS.search(text):
        return app.llm.smart
    return app.llm.fast


@dataclass
class AgentReply:
    text: str
    outbox: list[Any] = field(default_factory=list)
    model: str = ""
    tool_calls: list[str] = field(default_factory=list)


class Agent:
    def __init__(self, app: AppContext, tools: ToolRegistry | None = None) -> None:
        self.app = app
        self.tools = tools or registry

    async def handle(self, user_id: int, text: str, model: str | None = None) -> AgentReply:
        sf = self.app.sf
        profile = await get_profile(sf)
        await memory_service.add_message(sf, user_id, "user", text)

        unsummarized = await memory_service.unsummarized_messages(sf, user_id)
        history = memory_service.build_history(unsummarized, self.app.settings.history_limit)
        summary = await memory_service.get_summary(sf, user_id)
        facts = await memory_service.list_facts(sf, limit=60)
        system = build_system(
            profile, memory_service.format_facts(facts), summary.summary if summary else None
        )
        model = model or choose_model(self.app, text)
        ctx = ToolContext(app=self.app, user_id=user_id, tz=profile.timezone)
        reply = await self._loop(ctx, model, system, history)
        await memory_service.add_message(sf, user_id, "assistant", reply.text)
        return reply

    async def after_reply(self, user_id: int) -> None:
        """Фоновые дела после ответа: сжатие старой истории."""
        await workflows.maybe_summarize(self.app, user_id)

    async def _loop(
        self, ctx: ToolContext, model: str, system: list[dict], messages: list[dict]
    ) -> AgentReply:
        tool_defs = self.tools.definitions()
        tool_calls: list[str] = []
        messages = list(messages)
        max_iter = max(1, self.app.settings.max_tool_iterations)
        for _ in range(max_iter):
            response = await self.app.llm.create(
                model=model,
                messages=messages,
                system=system,
                tools=tool_defs,
                purpose="chat",
                user_id=ctx.user_id,
                effort="low",
            )
            if response.stop_reason == "refusal":
                if model != self.app.llm.fast:
                    log.warning("Модель %s отказалась, повтор на %s", model, self.app.llm.fast)
                    model = self.app.llm.fast
                    continue
                return AgentReply(
                    "🙅 Не могу помочь с этим запросом. Попробуйте сформулировать иначе.",
                    ctx.outbox,
                    model,
                    tool_calls,
                )

            tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
            if response.stop_reason == "tool_use" and tool_uses:
                # Ответ модели возвращаем как есть (вместе с блоками размышлений), как
                # рекомендует документация SDK.
                messages.append({"role": "assistant", "content": response.content})
                results = []
                for block in tool_uses:
                    tool_calls.append(block.name)
                    output, is_error = await self.tools.execute(ctx, block.name, block.input)
                    log.info("tool %s(%s) → error=%s", block.name, block.input, is_error)
                    item: dict[str, Any] = {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output[:20000],
                    }
                    if is_error:
                        item["is_error"] = True
                    results.append(item)
                messages.append({"role": "user", "content": results})
                continue

            text = response_text(response)
            if response.stop_reason == "max_tokens":
                text += "\n\n✂️ Ответ получился длинным и обрезан. Попросите продолжить."
            if not text:
                text = "Готово ✅" if (tool_calls or ctx.outbox) else "Не понял запрос 🤔"
            return AgentReply(text, ctx.outbox, model, tool_calls)

        return AgentReply(
            "⚠️ Задача оказалась слишком многошаговой — я остановился, чтобы не тратить лишнее. "
            "Разбейте просьбу на части.",
            ctx.outbox,
            model,
            tool_calls,
        )

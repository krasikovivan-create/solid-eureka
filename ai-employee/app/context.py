"""Общий контекст приложения, который получают обработчики и инструменты."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.config import Settings
from app.database.session import SessionFactory

if TYPE_CHECKING:
    from app.agent.llm import LLM
    from app.scheduler.scheduler import BotScheduler
    from app.services.knowledge import KnowledgeBase


@dataclass
class AppContext:
    settings: Settings
    sf: SessionFactory
    llm: LLM
    kb: KnowledgeBase
    scheduler: BotScheduler | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def proposals_dir(self):
        return self.settings.data_dir / "proposals"

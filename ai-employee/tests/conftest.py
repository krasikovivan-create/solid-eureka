"""Общие фикстуры: временная БД, поддельные Anthropic и Telegram."""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import (
    GetFile,
    GetMe,
    GetUpdates,
    SendDocument,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import Chat, Document, File, Message, User

from app.agent.llm import LLM
from app.config import Settings
from app.context import AppContext
from app.database.session import create_engine, init_db, make_session_factory
from app.scheduler.scheduler import BotScheduler
from app.services import profile as profile_service
from app.services.knowledge import KnowledgeBase

TOKEN = "123456:TEST-token-for-tests"
OWNER_ID = 1001


# --- Поддельный Anthropic -------------------------------------------------------


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_block(name: str, input: dict, id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id or f"toolu_{name}", name=name, input=input)


def response(
    *blocks: SimpleNamespace,
    stop_reason: str | None = None,
    model: str = "claude-haiku-4-5",
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> SimpleNamespace:
    if stop_reason is None:
        stop_reason = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        model=model,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


class FakeMessages:
    def __init__(self, owner: FakeAnthropic) -> None:
        self.owner = owner

    async def create(self, **kwargs: Any) -> Any:
        self.owner.calls.append(kwargs)
        if not self.owner.script:
            raise AssertionError("FakeAnthropic: нет заготовленного ответа")
        item = self.owner.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(kwargs)
        return item


class FakeAnthropic:
    """Возвращает заранее заготовленные ответы по очереди и запоминает запросы."""

    def __init__(self, script: list | None = None) -> None:
        self.script: list = list(script or [])
        self.calls: list[dict] = []
        self.messages = FakeMessages(self)

    def add(self, *items: Any) -> None:
        self.script.extend(items)


# --- Поддельный Telegram ----------------------------------------------------------


class MockedSession(BaseSession):
    """Сессия aiogram без сети: запоминает запросы и отвечает правдоподобно."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []
        self.files: dict[str, bytes] = {}
        self._ids = itertools.count(100)

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.requests.append(method)
        now = datetime.now(UTC)
        if isinstance(method, SendMessage):
            return Message(
                message_id=next(self._ids),
                date=now,
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        if isinstance(method, SendDocument):
            return Message(
                message_id=next(self._ids),
                date=now,
                chat=Chat(id=method.chat_id, type="private"),
                document=Document(file_id="doc", file_unique_id="doc", file_name="f.docx"),
            )
        if isinstance(method, GetMe):
            return User(id=42, is_bot=True, first_name="Bot", username="test_bot")
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u", file_path=method.file_id)
        if isinstance(method, GetUpdates):
            await asyncio.sleep(0.05)  # как long polling: отдаём управление циклу
            return []
        return True

    async def stream_content(
        self, url: str, headers=None, timeout=30, chunk_size=65536, raise_for_status=True
    ):
        key = url.rsplit("/", 1)[-1]
        yield self.files.get(key, b"")

    async def close(self) -> None:
        pass

    # Удобные выборки для проверок.
    def sent_texts(self) -> list[str]:
        return [r.text for r in self.requests if isinstance(r, SendMessage)]

    def sent_messages(self) -> list[SendMessage]:
        return [r for r in self.requests if isinstance(r, SendMessage)]

    def sent_documents(self) -> list[SendDocument]:
        return [r for r in self.requests if isinstance(r, SendDocument)]

    def clear(self) -> None:
        self.requests.clear()


# --- Фикстуры -----------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        TELEGRAM_BOT_TOKEN=TOKEN,
        ANTHROPIC_API_KEY="sk-ant-test",
        ALLOWED_USER_IDS="",
        DB_PATH=str(tmp_path / "data" / "bot.db"),
        MODEL_SMART="claude-sonnet-5-5",
        MODEL_FAST="claude-haiku-4-5",
        _env_file=None,
    )


@pytest.fixture
def fake_llm() -> FakeAnthropic:
    return FakeAnthropic()


class SentLog(list):
    async def __call__(self, user_id: int, text: str, markup: Any = None) -> None:
        self.append((user_id, text, markup))


@pytest.fixture
async def app(settings: Settings, fake_llm: FakeAnthropic) -> AsyncGenerator[AppContext, None]:
    engine = create_engine(settings.db_path)
    await init_db(engine)
    sf = make_session_factory(engine)
    ctx = AppContext(
        settings=settings,
        sf=sf,
        llm=LLM(settings, sf, client=fake_llm),
        kb=KnowledgeBase(sf, settings.documents_dir),
    )
    sent = SentLog()
    ctx.scheduler = BotScheduler(ctx, sent)
    ctx.scheduler.scheduler.start()  # как в проде: планировщик запущен до работы с задачами
    ctx.extra["sent"] = sent
    ctx.extra["fake_llm"] = fake_llm
    yield ctx
    ctx.scheduler.shutdown()
    await engine.dispose()


@pytest.fixture
async def onboarded(app: AppContext) -> AppContext:
    await profile_service.try_claim_owner(app.sf, OWNER_ID)
    await profile_service.upsert_user(app.sf, OWNER_ID, "Иван Владелец")
    await profile_service.update_profile(
        app.sf,
        company_name="ИИ Лаб",
        company_description="Внедряем ИИ в бизнес",
        agent_name="Анна",
        agent_role="ассистент руководителя",
        communication_style="Деловой",
        onboarded=True,
        onboarding_step=5,
    )
    return app


@pytest.fixture
def tool_ctx_factory(onboarded: AppContext) -> Callable[..., Any]:
    from app.tools import ToolContext

    def make(user_id: int = OWNER_ID) -> ToolContext:
        return ToolContext(app=onboarded, user_id=user_id, tz="Europe/Moscow")

    return make


@pytest.fixture
def session() -> MockedSession:
    return MockedSession()


@pytest.fixture
def bot(session: MockedSession) -> Bot:
    return Bot(TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
